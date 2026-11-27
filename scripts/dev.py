"""EmneKlar for developers: one command per task, also on a new machine.

    py scripts/dev.py setup  [--playwright] [--dry-run]
    py scripts/dev.py start  [--port 8771] [--data-dir MAPPE] [--no-build] [--no-browser] [--dry-run]
    py scripts/dev.py stop   [--data-dir MAPPE]
    py scripts/dev.py demo   [--port 8769] [--canvas-port 8793] [--no-build] [--dry-run]
    py scripts/dev.py check  [--backend | --frontend] [--e2e] [--dry-run]

setup  The Python environment ``backend/.venv`` with the development tools (``pip install -c backend/constraints.txt
       -e "backend[dev]"``, as in CI), ``npm ci`` and the user interface (``npm run build``). ``--playwright`` also
       downloads Playwright's Chromium for the end-to-end tests. Safe to run again.
start  EmneKlar from the source code against a real Canvas, in a window of its own. The first time, the setup
       asks for the Canvas address and an access token. It is a development instance of its own, apart from an
       installed EmneKlar: the data folder ``EmneKlar-dev`` (``%LOCALAPPDATA%\\EmneKlar-dev`` on Windows), port 8771
       and the credential-store service «EmneKlar-dev» (EMNEKLAR_DATA_DIR, EMNEKLAR_PORT, EMNEKLAR_KEYRING_SERVICE).
       The ordinary data folder, port 8770 and the service «EmneKlar» are refused. Nothing is written to Canvas
       unless it is published from the change queue.
stop   Stops the development instance.
demo   A fake Canvas with test courses and a fake AI provider (``backend/tests/fakes/dev_server.py --demo``). Data and
       secrets are thrown away when it stops.
check  What CI checks: ruff, mypy for Windows and Linux, pytest; typecheck, lint and unit tests for the user
       interface. ``--e2e`` adds the end-to-end tests (Playwright + axe against a fake Canvas).

Only the standard library is used, so ``setup`` runs with any Python 3.11 or newer. Commands never go through a
shell. Exit codes: 0 = done, 1 = a step or a check failed, 2 = the command cannot be run (the message says why).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # update.py: venv path, npm path check, child environment
sys.path.insert(0, str(BACKEND))  # emneklar.core.system uses only the standard library

import update  # noqa: E402

from emneklar.core.system import user_data_dir  # noqa: E402 - the same folder rules as the program

MIN_PYTHON = (3, 11)
NEWEST_TESTED_PYTHON = (3, 14)  # backend/constraints.txt is verified for CPython 3.11-3.14
MIN_NODE_MAJOR = 22

#: The development instance against a real Canvas – never the ordinary installation's folder, port or service.
DEV_FOLDER = "EmneKlar-dev"
DEV_PORT = 8771
DEV_KEYRING_SERVICE = "EmneKlar-dev"
ORDINARY_PORT = 8770
ORDINARY_FOLDERS = ("EmneKlar", "EmneKlar-Claude")
ORDINARY_KEYRING_SERVICES = ("EmneKlar", "EmneKlar-Claude")

DEMO_PORT = 8769
DEMO_CANVAS_PORT = 8793
DEMO_TOKEN = "dev-preview-token"  # backend/tests/fakes/dev_server.py: a fixed login token for the fake set-up


class DevError(Exception):
    """The command cannot be run; the message says what to do."""


@dataclass
class Step:
    label: str
    argv: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)  # added to the environment


def venv_python() -> Path:
    return update.venv_python_path(ROOT)


def require_venv() -> Path:
    python = venv_python()
    if not python.is_file():
        raise DevError("Python-miljøet backend/.venv finnes ikke. Kjør først: py scripts/dev.py setup")
    return python


def tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise DevError(f"Fant ikke {name}. Installer Node.js LTS ({MIN_NODE_MAJOR} eller nyere) fra https://nodejs.org, "
                       "åpne et nytt terminalvindu og prøv igjen.")
    return found


def node_major() -> int | None:
    node = shutil.which("node")
    if node is None:
        return None
    try:
        done = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.match(r"v(\d+)\.", done.stdout.strip())
    return int(match.group(1)) if match else None


def python_version(python: Path | str) -> tuple[int, int] | None:
    try:
        done = subprocess.run([str(python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                              capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.fullmatch(r"(\d+)\.(\d+)", done.stdout.strip())
    return (int(match.group(1)), int(match.group(2))) if done.returncode == 0 and match else None


def base_python() -> str:
    """The interpreter for a new venv: this one, or the newest tested version via the py launcher if this one is
    newer than the tested versions."""
    if sys.version_info[:2] < MIN_PYTHON:
        raise DevError(f"Python {sys.version_info[0]}.{sys.version_info[1]} er for gammel. EmneKlar trenger Python 3.11 "
                       "eller nyere (testet med 3.11–3.14).")
    if sys.version_info[:2] <= NEWEST_TESTED_PYTHON:
        return sys.executable
    launcher = shutil.which("py")
    if launcher:
        for minor in range(NEWEST_TESTED_PYTHON[1], MIN_PYTHON[1] - 1, -1):
            try:
                done = subprocess.run([launcher, f"-3.{minor}", "-c", "import sys; print(sys.executable)"],
                                      capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                                      check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
    print(f"Merk: Python {sys.version_info[0]}.{sys.version_info[1]} er nyere enn versjonene EmneKlar er testet med "
          "(3.11–3.14). Oppsettet fortsetter likevel.")
    return sys.executable


# ----------------------------------------------------------------------------------------------- the development instance


def dev_data_dir() -> Path:
    return user_data_dir(DEV_FOLDER)


def check_apart(data_dir: Path, port: int) -> None:
    """A development instance never uses the ordinary installation's data folder or port."""
    if port == ORDINARY_PORT:
        raise DevError(f"Port {ORDINARY_PORT} er den vanlige EmneKlar sin. Velg en annen port (standard: {DEV_PORT}).")
    ordinary = {os.path.normcase(str(user_data_dir(name).resolve())) for name in ORDINARY_FOLDERS}
    if os.path.normcase(str(data_dir.resolve())) in ordinary:
        raise DevError(f"{data_dir} er datamappen til den vanlige EmneKlar. En utviklingsinstans bruker sin egen "
                       f"(standard: {dev_data_dir()}).")


def start_environment(base: Mapping[str, str], *, data_dir: Path, port: int) -> dict[str, str]:
    """The environment of the development instance: its own data folder, port and credential-store service."""
    check_apart(data_dir, port)
    if DEV_KEYRING_SERVICE in ORDINARY_KEYRING_SERVICES:  # pragma: no cover - a guard against a careless edit
        raise DevError("Utviklingsinstansen må ha sin egen tjeneste i nøkkelringen.")
    env = dict(base)
    env.update({"EMNEKLAR_DATA_DIR": str(data_dir), "EMNEKLAR_PORT": str(port),
                "EMNEKLAR_KEYRING_SERVICE": DEV_KEYRING_SERVICE})
    return env


def build_step() -> Step:
    return Step("Bygger brukergrensesnittet (npm run build)", [tool("npm"), "run", "build"], FRONTEND)


def require_node_modules() -> None:
    if not (FRONTEND / "node_modules").is_dir():
        raise DevError("frontend/node_modules mangler. Kjør først: py scripts/dev.py setup")


# ----------------------------------------------------------------------------------------------- running steps


def _where(folder: Path) -> str:
    return str(folder.relative_to(ROOT) or ".") if folder.is_relative_to(ROOT) else str(folder)


def run_steps(steps: Sequence[Step], *, dry_run: bool, keep_going: bool = False) -> list[tuple[Step, int]]:
    """Run the steps in order (never through a shell). Stops at the first failure unless ``keep_going``."""
    results: list[tuple[Step, int]] = []
    for step in steps:
        print(f"\n== {step.label}")
        print(f"   $ {subprocess.list2cmdline(step.argv)}   (i {_where(step.cwd)})")
        if dry_run:
            results.append((step, 0))
            continue
        env = update.child_env()
        env.update(step.env)
        try:
            code = subprocess.run(step.argv, cwd=step.cwd, env=env, check=False).returncode
        except OSError as exc:
            print(f"   Klarte ikke å starte kommandoen: {exc}")
            code = 1
        results.append((step, code))
        if code != 0 and not keep_going:
            break
    return results


def summary(results: Sequence[tuple[Step, int]]) -> int:
    print()
    for step, code in results:
        print(f"  {'OK  ' if code == 0 else 'FEIL'}  {step.label}")
    return 0 if results and all(code == 0 for _, code in results) else 1


# ----------------------------------------------------------------------------------------------- commands


def setup_steps(*, playwright: bool, dry_run: bool) -> list[Step]:
    python = venv_python()
    steps: list[Step] = []
    existing = python_version(python) if python.is_file() else None
    if existing is None or existing < MIN_PYTHON:
        steps.append(Step("Lager Python-miljøet backend/.venv", [base_python(), "-m", "venv", str(BACKEND / ".venv")],
                          ROOT))
    steps.append(Step("Installerer EmneKlar med utviklingsverktøyene (testede versjoner, som i CI)",
                      [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                       "-c", "backend/constraints.txt", "-e", "backend[dev]"], ROOT))
    npm = tool("npm")
    problem = update.npm_path_problem(FRONTEND)
    if problem:
        raise DevError(problem)
    major = node_major()
    if major is not None and major < MIN_NODE_MAJOR:
        raise DevError(f"Node.js {major} er for gammel. Installer Node.js LTS ({MIN_NODE_MAJOR} eller nyere) fra "
                       "https://nodejs.org.")
    steps.append(Step("Installerer pakkene til brukergrensesnittet (npm ci)", [npm, "ci", "--no-audit", "--no-fund"],
                      FRONTEND))
    steps.append(Step("Bygger brukergrensesnittet (npm run build)", [npm, "run", "build"], FRONTEND))
    if playwright:
        steps.append(Step("Laster ned Playwrights Chromium (for ende-til-ende-testene)",
                          [tool("npx"), "playwright", "install", "chromium"], FRONTEND))
    steps.append(Step("Kontrollerer at EmneKlar kan lastes",
                      [str(python), "-c", "import emneklar, emneklar.main; print('EmneKlar', emneklar.__version__)"],
                      BACKEND))
    return steps


def cmd_setup(args: argparse.Namespace) -> int:
    print(f"EmneKlar – utvikleroppsett i {ROOT}")
    code = summary(run_steps(setup_steps(playwright=args.playwright, dry_run=args.dry_run), dry_run=args.dry_run))
    if code == 0 and not args.dry_run:
        print("\nKlart. Neste steg:\n"
              "  py scripts/dev.py start   EmneKlar mot ekte Canvas (egen datamappe, port og nøkkel)\n"
              "  py scripts/dev.py demo    falsk Canvas med testemner\n"
              "  py scripts/dev.py check   testene og kontrollene CI kjører")
    return code


def cmd_start(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else dev_data_dir()
    env = start_environment({}, data_dir=data_dir, port=args.port)
    python = venv_python() if args.dry_run else require_venv()
    steps: list[Step] = []
    if not args.no_build:
        if not args.dry_run:
            require_node_modules()
        steps.append(build_step())
    argv = [str(python), "-m", "emneklar"] + (["--no-browser"] if args.no_browser else [])
    steps.append(Step("Starter EmneKlar fra kildekoden", argv, BACKEND, env))
    print("EmneKlar fra kildekoden – utviklingsinstans mot ekte Canvas\n"
          f"  Datamappe:   {data_dir}\n"
          f"  Adresse:     http://127.0.0.1:{args.port}\n"
          f"  Canvas-token: tjenesten «{DEV_KEYRING_SERVICE}» i nøkkelringen (Windows Legitimasjonsbehandling)\n"
          "Første gang: koble til Canvas i oppsettet. Ingenting skrives til Canvas før du publiserer fra endringskøen.\n"
          "Den vanlige EmneKlar (port 8770, egen datamappe og nøkkel) berøres ikke. Lukk vinduet eller trykk Ctrl+C "
          "her for å stoppe.")
    return summary(run_steps(steps, dry_run=args.dry_run))


def cmd_stop(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else dev_data_dir()
    env = start_environment({}, data_dir=data_dir, port=DEV_PORT)
    step = Step("Stopper utviklingsinstansen", [str(require_venv()), "-m", "emneklar.manage", "stop"], BACKEND, env)
    return summary(run_steps([step], dry_run=False))


def _open_when_ready(url: str, port: int, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.5)


def cmd_demo(args: argparse.Namespace) -> int:
    if ORDINARY_PORT in (args.port, args.canvas_port):
        raise DevError(f"Port {ORDINARY_PORT} er den vanlige EmneKlar sin. Velg en annen port.")
    python = venv_python() if args.dry_run else require_venv()
    steps: list[Step] = []
    if not args.no_build:
        if not args.dry_run:
            require_node_modules()
        steps.append(build_step())
    steps.append(Step("Starter EmneKlar med falsk Canvas og testdata",
                      [str(python), "backend/tests/fakes/dev_server.py", "--port", str(args.port), "--canvas-port",
                       str(args.canvas_port), "--demo"], ROOT))
    url = f"http://127.0.0.1:{args.port}/auth/launch?token={DEMO_TOKEN}"
    print(f"Falsk Canvas med testemner. Åpnes på {url} når den er klar. Ctrl+C stopper; data og nøkler kastes.")
    if not args.dry_run and not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, args.port), daemon=True).start()
    return summary(run_steps(steps, dry_run=args.dry_run))


def check_steps(*, backend: bool, frontend: bool, e2e: bool, dry_run: bool) -> list[Step]:
    steps: list[Step] = []
    if backend:
        python = str(venv_python() if dry_run else require_venv())
        steps += [
            Step("Ruff", [python, "-m", "ruff", "check", "--config", "pyproject.toml", ".", "../scripts"], BACKEND),
            Step("Mypy (Windows)", [python, "-m", "mypy", "--platform", "win32", "emneklar", "../scripts"], BACKEND),
            Step("Mypy (Linux)", [python, "-m", "mypy", "--platform", "linux", "emneklar", "../scripts"], BACKEND),
            Step("Pytest", [python, "-m", "pytest", "-q"], BACKEND),
        ]
    if frontend:
        if not dry_run:
            require_node_modules()
        npm = tool("npm")
        steps += [Step("Typesjekk", [npm, "run", "typecheck"], FRONTEND), Step("Lint", [npm, "run", "lint"], FRONTEND),
                  Step("Enhetstester", [npm, "test"], FRONTEND)]
        if e2e:
            steps += [build_step(), Step("Ende-til-ende (Playwright + axe, falsk Canvas)", [npm, "run", "e2e"], FRONTEND)]
    return steps


def cmd_check(args: argparse.Namespace) -> int:
    both = not args.backend and not args.frontend
    steps = check_steps(backend=args.backend or both, frontend=args.frontend or both, e2e=args.e2e,
                        dry_run=args.dry_run)
    return summary(run_steps(steps, dry_run=args.dry_run, keep_going=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py scripts/dev.py", description="EmneKlar for utviklere.")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="Python-miljø, utviklingsverktøy og brukergrensesnitt")
    setup.add_argument("--playwright", action="store_true", help="last også ned Chromium for ende-til-ende-testene")
    setup.set_defaults(func=cmd_setup)

    start = commands.add_parser("start", help="EmneKlar fra kildekoden mot ekte Canvas (egen datamappe og nøkkel)")
    start.add_argument("--port", type=int, default=DEV_PORT)
    start.add_argument("--data-dir", help=f"datamappe (standard: {dev_data_dir()})")
    start.add_argument("--no-build", action="store_true", help="ikke bygg brukergrensesnittet først")
    start.add_argument("--no-browser", action="store_true", help="ikke åpne noe vindu")
    start.set_defaults(func=cmd_start)

    stop = commands.add_parser("stop", help="stopp utviklingsinstansen")
    stop.add_argument("--data-dir", help=f"datamappe (standard: {dev_data_dir()})")
    stop.set_defaults(func=cmd_stop, dry_run=False)

    demo = commands.add_parser("demo", help="falsk Canvas med testemner og falsk KI")
    demo.add_argument("--port", type=int, default=DEMO_PORT)
    demo.add_argument("--canvas-port", type=int, default=DEMO_CANVAS_PORT)
    demo.add_argument("--no-build", action="store_true", help="ikke bygg brukergrensesnittet først")
    demo.add_argument("--no-browser", action="store_true", help="ikke åpne nettleseren")
    demo.set_defaults(func=cmd_demo)

    check = commands.add_parser("check", help="testene og kontrollene CI kjører")
    only = check.add_mutually_exclusive_group()
    only.add_argument("--backend", action="store_true", help="bare backend")
    only.add_argument("--frontend", action="store_true", help="bare brukergrensesnittet")
    check.add_argument("--e2e", action="store_true", help="også ende-til-ende-testene")
    check.set_defaults(func=cmd_check)

    for sub in (setup, start, demo, check):
        sub.add_argument("--dry-run", action="store_true", help="vis kommandoene uten å kjøre dem")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # UTF-8 also when the output is piped (Git Bash, a log file); never a crash on a console that cannot show it
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # in order with the commands' output
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except DevError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nAvbrutt.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
