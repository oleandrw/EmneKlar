"""Build the Windows installer from a release package and its runtime.

    python scripts/build_installer.py --package dist-release/EmneKlar-<versjon>.zip
                                      --runtime dist-release/EmneKlar-runtime-win-amd64-<id>.zip
                                      [--out dist-release] [--test-build] [--iscc ISCC.exe] [--sign KOMMANDO]

The installer contains exactly what the two files contain: the package is unpacked, the runtime is unpacked into
its ``runtime`` folder, and Inno Setup (packaging/windows/EmneKlar.iss) packs that folder. Nothing else is added, and
the runtime must be the one the package's install.json names (same SHA-256) – so the installer and an installation
that was updated by update.bat end up with the same files.

Writes ``<out>/EmneKlar-<versjon>-setup.exe`` and ``EmneKlar-<versjon>-setup.exe.sha256``.

``--test-build`` makes «EmneKlar (test)»: its own folder, Start-menu name and uninstall entry, so installing and
uninstalling can be tried on a machine without touching a normal installation.

``--sign`` is the Authenticode command for Inno Setup's SignTool (``$f`` is the file to sign), for example
``signtool sign /fd sha256 /tr http://timestamp.example /td sha256 /a $f``. Without it the installer is not signed,
and Windows SmartScreen warns about an unknown publisher. No certificate is stored in this repository.

Needs Inno Setup 6 (ISCC.exe): ``--iscc``, the environment variable ISCC, PATH, or the standard install folders.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # emneklar.* helpers below use only the standard library
sys.path.insert(0, str(ROOT / "scripts"))

import update  # noqa: E402 - scripts/update.py defines the format of a package and of a runtime

from emneklar.core.updates.version import Version  # noqa: E402

SCRIPT = ROOT / "packaging" / "windows" / "EmneKlar.iss"
PLATFORM = "win-amd64"


class InstallerError(Exception):
    pass


def find_iscc(given: str | None) -> Path:
    candidates = [given, os.environ.get("ISCC"), shutil.which("ISCC"), shutil.which("iscc")]
    # Installed for one user, or for everyone (environment variable names are case-insensitive on Windows).
    for variable, sub in (("LOCALAPPDATA", "Programs"), ("PROGRAMFILES(X86)", ""), ("PROGRAMFILES", "")):
        base = os.environ.get(variable)
        if base:
            candidates.append(str(Path(base) / sub / "Inno Setup 6" / "ISCC.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise InstallerError("Fant ikke Inno Setup 6 (ISCC.exe). Installer det fra https://jrsoftware.org/isinfo.php, "
                         "eller oppgi stien med --iscc.")


def stage(package: Path, runtime: Path, folder: Path) -> str:
    """Unpack the package and its runtime into ``folder`` as an installation. Returns the version."""
    try:
        tree = update.extract_release(package, folder.parent / "pakke")
        info = json.loads((tree / "install.json").read_text(encoding="utf-8"))
        version = update.read_version_file(tree / "VERSION")
        if version is None:
            raise InstallerError(f"{package.name} har ingen gyldig VERSION.")
        update.validate_release_tree(tree, version)
        wanted = update.release_runtimes(info).get(PLATFORM)
        if wanted is None:
            raise InstallerError(f"{package.name} er bygget uten kjøretid for {PLATFORM} (package_release.py --runtime).")
        if runtime.name != wanted.asset:
            raise InstallerError(f"Pakken trenger {wanted.asset}, ikke {runtime.name}.")
        update.verify_runtime_archive(runtime, wanted)
        shutil.copytree(tree, folder)
        update.extract_runtime(runtime, folder / update.RUNTIME_DIR, wanted)
    except update.UpdateError as exc:
        raise InstallerError(str(exc)) from exc
    return str(version)


def numeric_version(version: str) -> str:
    """``0.2.0-rc.1`` → ``0.2.0.0``: the four numbers Windows shows in the file properties."""
    parsed = Version.parse(version)
    if parsed is None:
        raise InstallerError(f"Ugyldig versjon: {version}")
    return f"{parsed.major}.{parsed.minor}.{parsed.patch}.0"


def output_name(version: str, *, test_build: bool) -> str:
    return f"EmneKlar-{version}-setup{'-test' if test_build else ''}.exe"


def compiler_arguments(version: str, source: Path, out_dir: Path, *, test_build: bool, sign: str | None) -> list[str]:
    arguments = [f"/DAppVersion={version}", f"/DNumericVersion={numeric_version(version)}", f"/DSourceDir={source}",
                 f"/DOutputDir={out_dir}", "/Qp"]
    if test_build:
        arguments.append("/DTestBuild")
    if sign:
        arguments += ["/DSignToolName=emneklarsign", f"/Semneklarsign={sign}"]
    return [*arguments, str(SCRIPT)]


def build(package: Path, runtime: Path, out_dir: Path, *, test_build: bool = False, iscc: str | None = None,
          sign: str | None = None) -> tuple[Path, Path, str]:
    compiler = find_iscc(iscc)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="emneklar-installer-") as temp:
        source = Path(temp) / "installasjon"
        version = stage(package, runtime, source)
        done = subprocess.run([str(compiler), *compiler_arguments(version, source, out_dir.resolve(),
                                                                 test_build=test_build, sign=sign)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if done.returncode != 0:
            tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-20:])
            raise InstallerError(f"Inno Setup feilet (kode {done.returncode}):\n{tail}")
    installer = out_dir / output_name(version, test_build=test_build)
    if not installer.is_file():
        raise InstallerError(f"Inno Setup laget ikke {installer.name}.")
    digest = update.sha256_file(installer)
    checksum = out_dir / f"{installer.name}.sha256"
    checksum.write_bytes(f"{digest}  {installer.name}\n".encode("ascii"))
    return installer, checksum, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lager installasjonsprogrammet for Windows.")
    parser.add_argument("--package", type=Path, required=True, help="EmneKlar-<versjon>.zip fra package_release.py")
    parser.add_argument("--runtime", type=Path, required=True, help="kjøretiden pakken er bygget med")
    parser.add_argument("--out", type=Path, default=None, help="målmappe (standard: dist-release)")
    parser.add_argument("--test-build", action="store_true",
                        help="lag «EmneKlar (test)» – en egen installasjon ved siden av en vanlig")
    parser.add_argument("--iscc", help="stien til ISCC.exe (Inno Setup 6)")
    parser.add_argument("--sign", help="Authenticode-kommando for Inno Setups SignTool ($f = filen som signeres)")
    args = parser.parse_args(argv)
    update.configure_stdio()
    try:
        installer, checksum, digest = build(args.package, args.runtime, args.out or ROOT / "dist-release",
                                            test_build=args.test_build, iscc=args.iscc, sign=args.sign)
    except (InstallerError, OSError) as exc:
        print(f"Feil: {exc}", file=sys.stderr)
        return 1
    print(f"Installasjonsprogram: {installer} ({installer.stat().st_size / 1_048_576:.1f} MB)")
    print(f"Sjekksum:             {checksum}")
    print(f"SHA-256:              {digest}")
    print("Signert:              " + ("ja (kommandoen i --sign)" if args.sign else
                                       "nei – Windows SmartScreen vil advare om ukjent utgiver"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
