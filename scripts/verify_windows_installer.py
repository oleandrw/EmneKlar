"""Install, start, stop and uninstall the Windows installer – and check each step.

    python scripts/verify_windows_installer.py --installer dist-release/EmneKlar-<versjon>-setup.exe [--work MAPPE]

Used by the release workflow before anything is published, and by hand with a test build
(``scripts/build_installer.py --test-build`` gives «EmneKlar (test)», which is installed next to a normal
installation and never replaces it). The installer is run silently for the current user; no administrator rights.

What is checked:
  1. the installer installs (exit code 0) into the per-user program folder, and its own check of the installation
     passed (scripts\\setup.py – logged by the installer);
  2. the Start-menu shortcuts (start and «Avslutt») and the desktop shortcut exist, and the uninstall entry is
     registered for the current user;
  3. the installed program starts without a console window and answers with the right version;
  4. it stops when asked to;
  5. installing again over a *running* program stops it first and succeeds;
  6. the uninstaller removes the program folder, the shortcuts and the uninstall entry – and leaves the data folder.

The data folder is ``<work>\\data`` (EMNEKLAR_DATA_DIR), secrets are kept in memory, no browser is opened and a free
port is used: nothing of the user's own EmneKlar is read or changed. Exit code 0 means every check passed.

A test build also has defaults of its own (``emneklar.local.json`` written by the installer: the data folder
``%LOCALAPPDATA%\\EmneKlar-test-data``, port 8791 and the credential-store service «EmneKlar-test»), so it does not use
the real data folder or the real Canvas token even when it is started from its shortcut. That is checked too.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from emneklar.manage import fetch_health, read_instance  # noqa: E402 - standard library only

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
APP_IDS = {False: "{077D937C-0194-43D0-B8E5-D4F21205B360}_is1", True: "{2C012464-A983-487C-B3EF-C3904838110F}_is1"}
SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]


class CheckFailed(Exception):
    pass


def check(condition: bool, text: str) -> None:
    print(f"  [{'OK' if condition else 'FEIL'}] {text}", flush=True)
    if not condition:
        raise CheckFailed(text)


def uninstall_entry(test_build: bool) -> dict[str, str] | None:
    """The uninstall entry the installer registered for the current user, or None."""
    if sys.platform != "win32":  # the registry exists on Windows only – and the type checker elsewhere knows it
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{UNINSTALL_KEY}\\{APP_IDS[test_build]}") as key:
            return {name: str(winreg.QueryValueEx(key, name)[0]) for name in ("DisplayName", "DisplayVersion",
                                                                              "InstallLocation", "UninstallString")}
    except OSError:
        return None


def desktop_dir() -> Path:
    """The user's real desktop folder (it may be redirected, for example into OneDrive)."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(520)
    desktop_directory = 0x10  # CSIDL_DESKTOPDIRECTORY
    getattr(ctypes, "windll").shell32.SHGetFolderPathW(None, desktop_directory, None, 0, buffer)  # noqa: B009
    return Path(buffer.value) if buffer.value else Path(os.environ["USERPROFILE"]) / "Desktop"


def start_without_console(pythonw: Path, app: Path, env: dict[str, str]) -> None:
    """What the shortcut does: pythonw.exe -m emneklar (EMNEKLAR_NO_BROWSER keeps the browser closed here)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(pythonw), "-m", "emneklar"], cwd=app, env=env, close_fds=True, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


#: Asked of the installed program with no EMNEKLAR_* variable set, as when it is started from its shortcut. It only
#: works out which folder, port and credential-store service it *would* use – nothing is started, created or read.
RESOLVE = ("import json; from emneklar.config import default_data_dir, default_port, uses_standard_data_dir; "
           "from emneklar.core.auth.secrets import keyring_service; "
           "print(json.dumps({'data_dir': str(default_data_dir()), 'port': default_port(), "
           "'standard': uses_standard_data_dir(), 'keyring_service': keyring_service()}))")


def resolved_defaults(python: Path, app: Path) -> dict[str, object]:
    clean = {name: value for name, value in os.environ.items() if not name.upper().startswith("EMNEKLAR_")}
    done = subprocess.run([str(python), "-c", RESOLVE], cwd=app, env=clean, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False, timeout=120)
    if done.returncode != 0:
        raise CheckFailed(f"Kunne ikke lese installasjonens standardverdier: {done.stderr.strip()[-300:]}")
    result: dict[str, object] = json.loads(done.stdout.strip().splitlines()[-1])
    return result


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def running_version(data: Path, timeout: float) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = read_instance(data / "run")
        health = fetch_health(info["origin"]) if info else None
        if health is not None:
            return str(health.get("version"))
        time.sleep(0.5)
    return None


def run(command: list[str], env: dict[str, str], *, timeout: float = 900) -> int:
    return subprocess.run(command, env=env, check=False, timeout=timeout).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Installerer, starter og avinstallerer installasjonsprogrammet.")
    parser.add_argument("--installer", type=Path, required=True, help="EmneKlar-<versjon>-setup[-test].exe")
    parser.add_argument("--work", type=Path, help="mappe for testdata og logger (standard: en midlertidig mappe)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # UTF-8 and line by line, also when the output is redirected (CI logs)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if os.name != "nt":
        print("Feil: installasjonsprogrammet kan bare kontrolleres på Windows.", file=sys.stderr)
        return 2
    installer = args.installer.resolve()
    match = re.fullmatch(r"EmneKlar-(.+)-setup(-test)?\.exe", installer.name)
    if not installer.is_file() or not match:
        print(f"Feil: {installer} er ikke et installasjonsprogram for EmneKlar.", file=sys.stderr)
        return 2
    version, test_build = match.group(1), bool(match.group(2))
    name = "EmneKlar (test)" if test_build else "EmneKlar"
    app = Path(os.environ["LOCALAPPDATA"]) / "Programs" / ("EmneKlar-test" if test_build else "EmneKlar")
    start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / name
    desktop = desktop_dir() / f"{name}.lnk"
    work = (args.work or Path(tempfile.mkdtemp(prefix="emneklar-installasjonstest-"))).resolve()
    data = work / "data"
    data.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"EMNEKLAR_DATA_DIR": str(data), "EMNEKLAR_PORT": str(free_port()), "EMNEKLAR_SECRET_BACKEND": "memory",
                "EMNEKLAR_NO_BROWSER": "1", "PYTHONUTF8": "1"})
    python, pythonw = app / "runtime" / "python.exe", app / "runtime" / "pythonw.exe"
    ok = False
    try:
        if app.exists() or uninstall_entry(test_build) is not None:
            raise CheckFailed(f"{name} er allerede installert på denne maskinen ({app}). Avinstaller det først – denne "
                              "kontrollen installerer og avinstallerer.")
        print(f"Installasjonsprogram: {installer.name}\nTestdata: {work}\n\n1. Installerer (stille, for denne brukeren)")
        log = work / "install.log"
        check(run([str(installer), *SILENT, f"/LOG={log}"], env) == 0, "installasjonsprogrammet fullførte (kode 0)")
        check((app / "VERSION").read_text(encoding="utf-8").strip() == version, f"versjon {version} ligger i {app}")
        check(python.is_file() and pythonw.is_file(), "den innebygde kjøretiden er installert (ingen Python på maskinen)")
        check(not (app / "backend" / ".venv").exists(), "ingen pip og intet virtuelt miljø er laget")
        local = app / "emneklar.local.json"
        resolved = resolved_defaults(python, app)
        if test_build:
            # The test build can never open the user's real data: it has a data folder, a port and a credential-store
            # service of its own – also when it is started with no EMNEKLAR_* variable at all (the shortcut).
            defaults = json.loads(local.read_text(encoding="utf-8-sig")) if local.is_file() else {}
            check(str(defaults.get("data_dir", "")).endswith("EmneKlar-test-data") and defaults.get("port") == 8791
                  and defaults.get("keyring_service") == "EmneKlar-test",
                  "testutgaven har egen datamappe, port og tjeneste i Legitimasjonsbehandling (emneklar.local.json)")
            check(str(resolved["data_dir"]).endswith("EmneKlar-test-data") and resolved["port"] == 8791
                  and resolved["keyring_service"] == "EmneKlar-test" and resolved["standard"] is False,
                  "startet uten miljøvariabler ville den brukt sin egen datamappe – ikke den vanlige, og ingenting "
                  "kopieres fra den gamle mappen")
        else:
            check(not local.exists(), "en vanlig installasjon bruker standard datamappe (ingen emneklar.local.json)")
            check(resolved["standard"] is True and resolved["keyring_service"] == "EmneKlar",
                  "startet uten miljøvariabler bruker den standard datamappe og tjenesten «EmneKlar»")
        logged = log.read_text(encoding="utf-8", errors="replace")
        check("Kontroll av installasjonen (scripts\\setup.py): kode 0" in logged, "installasjonens egen kontroll besto")

        print("\n2. Snarveier og avinstalleringsoppføring")
        check((start_menu / f"{name}.lnk").is_file(), f"Start-menyen: {name}")
        check((start_menu / f"Avslutt {name}.lnk").is_file(), f"Start-menyen: Avslutt {name}")
        check(desktop.is_file(), "skrivebordet")
        entry = uninstall_entry(test_build)
        check(entry is not None and entry["DisplayName"] == name and entry["DisplayVersion"] == version,
              "avinstallering er registrert for denne brukeren (Innstillinger → Apper)")

        print("\n3. Starter uten konsollvindu (som snarveien)")
        start_without_console(pythonw, app, env)
        check(running_version(data, 120) == version, f"EmneKlar {version} svarer")

        print("\n4. Avslutter (som «Avslutt EmneKlar» i Start-menyen)")
        check(run([str(python), "-m", "emneklar.manage", "stop", "--timeout", "30"], env) == 0, "EmneKlar avsluttet")
        check(running_version(data, 2) is None, "ingenting svarer lenger")

        print("\n5. Installerer på nytt mens EmneKlar kjører")
        start_without_console(pythonw, app, env)
        check(running_version(data, 120) == version, "EmneKlar kjører")
        check(run([str(installer), *SILENT, f"/LOG={work / 'install-2.log'}"], env) == 0,
              "installasjonsprogrammet stoppet EmneKlar og fullførte")
        check(running_version(data, 2) is None, "EmneKlar kjører ikke etter installasjonen")

        print("\n6. Avinstallerer mens EmneKlar kjører")
        start_without_console(pythonw, app, env)
        check(running_version(data, 120) == version, "EmneKlar kjører")
        # The uninstaller copies itself to a temporary folder and returns at once; wait for the folder to go.
        check(run([str(app / "unins000.exe"), *SILENT, f"/LOG={work / 'uninstall.log'}"], env) == 0,
              "avinstalleringen fullførte (kode 0)")
        deadline = time.monotonic() + 120
        while app.exists() and time.monotonic() < deadline:
            time.sleep(1)
        check(not app.exists(), "programmappen er fjernet")
        check(not start_menu.exists() and not desktop.exists(), "snarveiene er fjernet")
        check(uninstall_entry(test_build) is None, "avinstalleringsoppføringen er fjernet")
        check((data / "database.db").is_file(), "datamappen er urørt")
        ok = True
    except (CheckFailed, OSError, subprocess.TimeoutExpired) as exc:
        print(f"\nFEIL: {exc}", file=sys.stderr)
        if python.is_file():  # never leave a test instance running
            run([str(python), "-m", "emneklar.manage", "stop", "--timeout", "30"], env, timeout=120)
    if ok and args.work is None:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"Testdata og logger: {work}")
    print("\nINSTALLASJONSKONTROLLEN BESTO." if ok else "\nINSTALLASJONSKONTROLLEN FEILET.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
