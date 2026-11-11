"""Try the whole update of an installed EmneKlar on this machine – without GitHub and without touching your data.

    python scripts/local_update_test.py --package dist-release/EmneKlar-<versjon>.zip
                                        --runtime dist-release/EmneKlar-runtime-win-amd64-<id>.zip
                                        [--work MAPPE] [--same-runtime] [--break-new-version] [--keep]

What it does, in a folder of its own (default: a temporary folder; ``--work`` to choose one):

1. Makes a test installation exactly like the installer does: the package unpacked, the runtime in ``runtime\\``.
   Its data folder is ``<work>\\data`` (EMNEKLAR_DATA_DIR) – never your own data folder – and it uses a free port.
2. Starts the installed version without a console window and checks that it answers.
3. Makes the "next release" from the same files: the version number is raised, and (unless ``--same-runtime``) the
   runtime gets a new id, so the update has to fetch and swap the runtime too.
4. Runs the installation's own updater (``scripts\\update.py``, with a copy of the interpreter – as update.bat does):
   it stops the running program, backs up the database, verifies the checksums, swaps the program files and the
   runtime, migrates, health-checks the new version and starts it again. The only thing replaced is where the
   release comes from: a folder on this machine instead of GitHub.
5. Checks the result: the new version answers, the runtime is the new one, nothing is left behind.

``--break-new-version`` makes the next release unable to start. The update must then fail in the health check and put
everything back: the old program files, the old runtime and the database – and the old version must run again.

Exit code 0 means every check passed. The updater's own window output is shown as it runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import update  # noqa: E402 - the format of packages and runtimes, and the helpers to unpack them

from emneklar.core.system import platform_tag  # noqa: E402
from emneklar.core.updates.version import Version  # noqa: E402
from emneklar.manage import fetch_health, read_instance, stop_instance  # noqa: E402

REPOSITORY = "lokal-test/EmneKlar"

#: Run by the installation's interpreter copy: the installation's own updater, with the release served from a folder.
DRIVER = '''\
import json, shutil, sys
from pathlib import Path

app, release_dir = Path(sys.argv[1]), Path(sys.argv[2])
sys.argv = ["update.py", "--repo", str(app)]
sys.path.insert(0, str(app / "scripts"))
import update

info = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
release = update.Release(version=update.Version.parse(info["version"]), tag="v" + info["version"],
                         name="EmneKlar " + info["version"], notes="- Lokal test av oppdateringen.",
                         prerelease=False, assets={name: "https://local.invalid/" + name for name in info["assets"]})
update.fetch_latest_release = lambda repo, *, channel: release


def local_download(url, dest, *, max_bytes):
    source = release_dir / url.rsplit("/", 1)[-1]
    if source.stat().st_size > max_bytes:
        raise update.UpdateError(dest.name + " er større enn forventet – nedlastingen er avbrutt.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)


update.download = local_download
sys.exit(update.main(["--repo", str(app), "--from-app", "--allow-major", "--no-pause"]))
'''


class TestFailed(Exception):
    pass


def check(condition: bool, text: str) -> None:
    print(f"  [{'OK' if condition else 'FEIL'}] {text}", flush=True)
    if not condition:
        raise TestFailed(text)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def install(package: Path, runtime: Path, app: Path) -> tuple[str, update.RuntimeRef]:
    """A test installation as the installer makes it. Returns (version, runtime)."""
    tree = update.extract_release(package, app.parent / "pakke")
    info = json.loads((tree / "install.json").read_text(encoding="utf-8"))
    wanted = update.release_runtimes(info).get(platform_tag())
    if wanted is None:
        raise TestFailed(f"{package.name} er bygget uten kjøretid for {platform_tag()} (package_release.py --runtime).")
    if runtime.name != wanted.asset:
        raise TestFailed(f"Pakken trenger {wanted.asset}, ikke {runtime.name}.")
    update.verify_runtime_archive(runtime, wanted)
    shutil.copytree(tree, app)
    update.extract_runtime(runtime, app / update.RUNTIME_DIR, wanted)
    shutil.rmtree(app.parent / "pakke", ignore_errors=True)
    return str(update.read_version_file(app / "VERSION")), wanted


def next_version(version: str) -> str:
    parsed = Version.parse(version)
    assert parsed is not None
    return f"{parsed.major}.{parsed.minor}.{parsed.patch + 1}"


def next_runtime(runtime: Path, wanted: update.RuntimeRef, release_dir: Path) -> update.RuntimeRef:
    """The same runtime under a new id: what a release with changed dependencies looks like to the updater."""
    identifier = f"{wanted.id.split('-')[0]}-{hashlib.sha256(wanted.id.encode()).hexdigest()[:12]}"
    target = release_dir / update.runtime_asset_name(wanted.platform, identifier)
    with zipfile.ZipFile(runtime) as source, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as out:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == update.RUNTIME_INFO:
                data = json.dumps({**json.loads(data), "id": identifier}, indent=2).encode("utf-8")
            out.writestr(item, data)
    return update.RuntimeRef(platform=wanted.platform, id=identifier, python=wanted.python, asset=target.name,
                             sha256=update.sha256_file(target), size=target.stat().st_size)


def make_release(package: Path, version: str, runtime: update.RuntimeRef, release_dir: Path, *, broken: bool) -> str:
    """``EmneKlar-<next>.zip`` with its checksum in ``release_dir``. Returns the new version."""
    new = next_version(version)
    target = release_dir / f"EmneKlar-{new}.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for item in source.infolist():
            relative = item.filename.split("/", 1)[1] if "/" in item.filename else item.filename
            data = source.read(item)
            if relative == "VERSION":
                data = f"{new}\n".encode()
            elif relative == "install.json":
                info = json.loads(data)
                info.update({"version": new, "repository": REPOSITORY})
                info["runtimes"] = {runtime.platform: {"id": runtime.id, "python": runtime.python,
                                                       "asset": runtime.asset, "sha256": runtime.sha256,
                                                       "size": runtime.size}}
                data = (json.dumps(info, indent=2) + "\n").encode("utf-8")
            elif broken and relative == "backend/emneklar/main.py":
                data = b"raise RuntimeError('lokal test: denne versjonen kan ikke starte')\n" + data
            out.writestr(f"EmneKlar-{new}/{relative}", data)
    (release_dir / f"{target.name}.sha256").write_text(f"{update.sha256_file(target)}  {target.name}\n",
                                                       encoding="ascii")
    assets = [target.name, f"{target.name}.sha256"] + ([runtime.asset] if (release_dir / runtime.asset).is_file() else [])
    (release_dir / "release.json").write_text(json.dumps({"version": new, "assets": assets}), encoding="utf-8")
    return new


def environment(data: Path, port: int) -> dict[str, str]:
    env = dict(os.environ)
    # EMNEKLAR_NO_BROWSER: the updater starts EmneKlar itself after the update; no browser tab is opened for a test.
    env.update({"EMNEKLAR_DATA_DIR": str(data), "EMNEKLAR_PORT": str(port), "EMNEKLAR_SECRET_BACKEND": "memory",
                "EMNEKLAR_NO_BROWSER": "1", "PYTHONUTF8": "1"})
    return env


def start(app: Path, env: dict[str, str]) -> None:
    """As the shortcut does (no console window) – but without opening a browser."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(update.bundled_python_path(app, windowed=True)), "-m", "emneklar", "--no-browser"], cwd=app,
                     env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)


def running_version(data: Path, timeout: float = 90.0) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = read_instance(data / "run")
        health = fetch_health(info["origin"]) if info else None
        if health is not None:
            return str(health.get("version"))
        time.sleep(0.5)
    return None


def run_updater(app: Path, release_dir: Path, work: Path, env: dict[str, str]) -> int:
    """The installation's own update.py, run by a copy of its interpreter – what update.bat does."""
    copy = app / ".update" / "python"
    shutil.rmtree(copy, ignore_errors=True)
    copy.mkdir(parents=True)
    for item in (app / update.RUNTIME_DIR).iterdir():
        if item.is_file():
            shutil.copy2(item, copy / item.name)
    driver = work / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    # --no-start is not used: the updater starts the new version itself, as it does for a user.
    return subprocess.run([str(update.runtime_interpreter(copy)), str(driver), str(app), str(release_dir)], env=env,
                          check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prøver oppdateringen av en installert EmneKlar lokalt, uten GitHub.")
    parser.add_argument("--package", type=Path, required=True, help="EmneKlar-<versjon>.zip fra package_release.py")
    parser.add_argument("--runtime", type=Path, required=True, help="kjøretiden pakken er bygget med")
    parser.add_argument("--work", type=Path, help="mappe for testinstallasjonen (standard: en midlertidig mappe)")
    parser.add_argument("--same-runtime", action="store_true",
                        help="den nye versjonen bruker samme kjøretid (ingenting å hente); standard er ny kjøretid")
    parser.add_argument("--break-new-version", action="store_true",
                        help="den nye versjonen kan ikke starte: oppdateringen skal feile og rulle alt tilbake")
    parser.add_argument("--keep", action="store_true", help="behold testmappen etterpå")
    args = parser.parse_args(argv)
    update.configure_stdio()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]  # in step with the updater's output
    work = (args.work or Path(tempfile.mkdtemp(prefix="emneklar-oppdateringstest-"))).resolve()
    if work.exists() and any(work.iterdir()):
        print(f"Feil: {work} er ikke tom. Velg en tom eller ny mappe.", file=sys.stderr)
        return 2
    app, data, release_dir = work / "app", work / "data", work / "utgivelse"
    for folder in (work, data, release_dir):
        folder.mkdir(parents=True, exist_ok=True)
    env = environment(data, free_port())
    ok = False
    try:
        print(f"Testmappe: {work}\n\n1. Testinstallasjon")
        version, runtime = install(args.package.resolve(), args.runtime.resolve(), app)
        check(update.install_kind(app) == "release" and not (app / ".git").exists(), f"installert utgivelse {version} "
              "(install.json, uten .git)")
        check(update.installed_runtime_id(app) == runtime.id, f"innebygd kjøretid {runtime.id}")

        print("\n2. Starter den installerte versjonen uten konsollvindu")
        start(app, env)
        check(running_version(data) == version, f"EmneKlar {version} svarer")

        print("\n3. Lager neste utgivelse i en lokal mappe")
        new_runtime = runtime if args.same_runtime else next_runtime(args.runtime.resolve(), runtime, release_dir)
        new = make_release(args.package.resolve(), version, new_runtime, release_dir, broken=args.break_new_version)
        print(f"  versjon {new}, kjøretid {new_runtime.id}" + (" (samme som før)" if args.same_runtime else " (ny)")
              + (" – kan ikke starte" if args.break_new_version else ""))

        print("\n4. Kjører installasjonens egen oppdatering\n" + "-" * 78)
        code = run_updater(app, release_dir, work, env)
        print("-" * 78)

        print("\n5. Kontroll")
        installed = str(update.read_version_file(app / "VERSION"))
        if args.break_new_version:
            check(code == update.EXIT_FAILED, "oppdateringen feilet (kode 1), slik den skal når ny versjon ikke starter")
            check(installed == version, f"programfilene er satt tilbake til {version}")
            check(update.installed_runtime_id(app) == runtime.id, f"den forrige kjøretiden er satt tilbake ({runtime.id})")
            check(running_version(data) == version, f"EmneKlar {version} kjører igjen")
        else:
            check(code == update.EXIT_OK, "oppdateringen fullførte (kode 0)")
            check(installed == new, f"installert versjon er {new}")
            check(update.installed_runtime_id(app) == new_runtime.id, f"kjøretiden er {new_runtime.id}")
            check(running_version(data) == new, f"EmneKlar {new} er startet og svarer")
            check((app / ".update" / f"previous-{version}" / "VERSION").is_file(), "forrige programversjon er tatt vare på")
        leftovers = [name for name in ("runtime-new", "runtime-previous", "runtime-failed", "staging", "download")
                     if (app / ".update" / name).exists()]
        check(not leftovers, "ingen midlertidige filer ligger igjen" + (f" ({', '.join(leftovers)})" if leftovers else ""))
        backups = list((data / "backups" / "database").glob("for-oppdatering-*.db"))
        check(len(backups) == 1, "databasen ble sikkerhetskopiert før oppdateringen")
        check((data / "logs" / "update.log").is_file(), f"logg: {data / 'logs' / 'update.log'}")
        ok = True
    except (TestFailed, update.UpdateError, OSError) as exc:
        print(f"\nFEIL: {exc}", file=sys.stderr)
    finally:
        os.environ["EMNEKLAR_DATA_DIR"] = str(data)
        result = stop_instance(data / "run", timeout=30)
        print(f"\nTestinstallasjonen er stoppet ({result}).")
        if args.keep or not ok:
            print(f"Testmappen er beholdt: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print("\nOPPDATERINGSTESTEN BESTO." if ok else "\nOPPDATERINGSTESTEN FEILET.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
