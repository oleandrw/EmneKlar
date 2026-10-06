"""EmneKlar – oppsett. Started by setup.bat; safe to run again (it repairs whatever is missing or broken).

Steps ("Steg N av 5 – …"):

  1  check Python (3.11 or newer; for a new venv a tested version 3.11–3.14 is preferred if installed)
  2  create or repair the virtual environment backend\\.venv
  3  install the pinned dependencies: pip install -c backend/constraints.txt -e backend
  4  the user interface: release zips include frontend\\dist; otherwise it is built with npm (Node.js LTS)
  5  verify: import emneklar in the venv and check frontend\\dist\\index.html

No administrator rights are needed and nothing outside this folder is changed, except the log file
``<data folder>\\logs\\setup.log`` (normally ``%LOCALAPPDATA%\\EmneKlar\\logs\\setup.log``).
Exit codes: 0 = ready (next step: start.bat), 1 = setup failed (see the message and the log).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

MIN_PYTHON = (3, 11)
NEWEST_TESTED_PYTHON = (3, 14)  # backend/constraints.txt is verified for CPython 3.11-3.14
MIN_NODE_MAJOR = 22  # Node.js LTS; see the "engines" fields in frontend/package-lock.json
TOTAL_STEPS = 5
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"

if sys.version_info < MIN_PYTHON:  # setup.bat checks this too; keep this file importable by old Pythons
    sys.stderr.write("EmneKlar trenger Python 3.11 eller nyere. Installer en nyere Python fra python.org og kjør "
                     "setup.bat på nytt.\n")
    sys.exit(1)

sys.path.insert(0, str(BACKEND))  # emneklar.* (only standard-library modules are imported before the venv exists)

import update  # noqa: E402 - scripts/update.py: shared console, log, command and pip helpers

from emneklar.manage import data_dir_from_env, running_instance  # noqa: E402


class SetupError(Exception):
    """Setup cannot continue; the message tells the user what to do."""


def _venv_python_version(python: Path) -> tuple[int, int] | None:
    if not python.is_file():
        return None
    try:
        done = subprocess.run([str(python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                              capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.fullmatch(r"(\d+)\.(\d+)", done.stdout.strip())
    return (int(match.group(1)), int(match.group(2))) if done.returncode == 0 and match else None


def choose_base_python(reporter: update.Reporter) -> str:
    """The interpreter for a new venv: this one, or a tested version via the py launcher if this one is newer."""
    current = sys.version_info[:2]
    if current <= NEWEST_TESTED_PYTHON:
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
            found = done.stdout.strip()
            if done.returncode == 0 and found and Path(found).is_file():
                reporter.info(f"Bruker Python 3.{minor}, som EmneKlar er testet med ({found}).")
                return found
    reporter.warn(f"Python {current[0]}.{current[1]} er nyere enn versjonene EmneKlar er testet med (3.11–3.14). "
                  "Oppsettet fortsetter likevel.")
    return sys.executable


def check_python(reporter: update.Reporter) -> str:
    reporter.step(1, "Kontrollerer Python")
    reporter.info(f"Python {sys.version.split()[0]} ({sys.executable})")
    if running_instance(data_dir_from_env() / "run") is not None:
        raise SetupError("EmneKlar kjører. Lukk EmneKlar-vinduet og kjør setup.bat på nytt.")
    return choose_base_python(reporter)


def ensure_venv(reporter: update.Reporter, base_python: str) -> Path:
    reporter.step(2, "Python-miljø (backend\\.venv)")
    python = update.venv_python_path(ROOT)
    version = _venv_python_version(python)
    if version is not None and version >= MIN_PYTHON:
        reporter.info(f"Python-miljøet finnes allerede (Python {version[0]}.{version[1]}) – gjenbrukes.")
    else:
        if VENV.exists():
            reporter.info("Python-miljøet virker ikke (eller er for gammelt) og lages på nytt.")
            try:
                update.remove_tree(VENV)
            except OSError as exc:
                raise SetupError(f"Klarte ikke å slette det gamle Python-miljøet ({exc}). Lukk programmer som bruker "
                                 "EmneKlar-mappen, og kjør setup.bat på nytt.") from exc
        reporter.info("Lager Python-miljøet …")
        update.run([base_python, "-m", "venv", VENV], cwd=ROOT, reporter=reporter)
    if update.run([python, "-m", "pip", "--version"], cwd=ROOT, reporter=reporter, capture=True,
                  check=False).returncode != 0:
        reporter.info("pip mangler i Python-miljøet – installerer det …")
        update.run([python, "-m", "ensurepip", "--upgrade", "--default-pip"], cwd=ROOT, reporter=reporter)
    return python


def install_dependencies(reporter: update.Reporter, python: Path) -> None:
    reporter.step(3, "Installerer avhengigheter (testede versjoner)")
    constraints = BACKEND / "constraints.txt"
    if constraints.is_file():
        upgraded = update.run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                               "--upgrade", "pip", "-c", constraints], cwd=ROOT, reporter=reporter, check=False)
        if upgraded.returncode != 0:
            reporter.warn("Klarte ikke å oppdatere pip – fortsetter med versjonen som er installert.")
    update.install_python_dependencies(python, ROOT, reporter)


def _node_major(npm: str) -> int | None:
    node = shutil.which("node") or str(Path(npm).with_name("node.exe"))
    try:
        done = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.match(r"v(\d+)\.", done.stdout.strip())
    return int(match.group(1)) if match else None


def ensure_frontend(reporter: update.Reporter) -> None:
    reporter.step(4, "Brukergrensesnitt (frontend\\dist)")
    index = FRONTEND / "dist" / "index.html"
    if index.is_file():
        reporter.info("Brukergrensesnittet er allerede bygget – ingenting å gjøre.")
        return
    npm = shutil.which("npm")
    if npm is None:
        raise SetupError("Brukergrensesnittet er ikke bygget, og Node.js ble ikke funnet. Velg én av disse:\n"
                         "  a) Last ned en ferdig utgivelse av EmneKlar (EmneKlar-<versjon>.zip fra GitHub). Den har "
                         "ferdigbygd brukergrensesnitt og trenger ikke Node.js.\n"
                         f"  b) Installer Node.js LTS ({MIN_NODE_MAJOR} eller nyere) fra https://nodejs.org og kjør "
                         "setup.bat på nytt.")
    problem = update.npm_path_problem(FRONTEND)
    if problem:
        raise SetupError(problem)
    major = _node_major(npm)
    if major is not None and major < MIN_NODE_MAJOR:
        raise SetupError(f"Node.js {major} er for gammel til å bygge brukergrensesnittet. Installer Node.js LTS "
                         f"({MIN_NODE_MAJOR} eller nyere) fra https://nodejs.org og kjør setup.bat på nytt.")
    reporter.info("Bygger brukergrensesnittet med npm (kan ta noen minutter) …")
    update.run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND, reporter=reporter)
    update.run([npm, "run", "build"], cwd=FRONTEND, reporter=reporter)
    if not index.is_file():
        raise SetupError("Byggingen av brukergrensesnittet ga ingen frontend\\dist\\index.html.")


def verify(reporter: update.Reporter, python: Path) -> str:
    reporter.step(5, "Kontrollerer installasjonen")
    expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    done = update.run([python, "-c", "import emneklar, emneklar.main; print(emneklar.__version__)"], cwd=ROOT,
                      reporter=reporter, capture=True, check=False)
    found = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""
    if done.returncode != 0 or found != expected:
        last = (done.stderr or done.stdout).strip().splitlines()[-3:]
        raise SetupError("EmneKlar kunne ikke lastes i Python-miljøet" + (f": {' / '.join(last)}" if last else ".")
                         + " Kjør setup.bat på nytt.")
    if not (FRONTEND / "dist" / "index.html").is_file():
        raise SetupError("frontend\\dist\\index.html mangler.")
    reporter.info(f"EmneKlar {found} kan startes, og brukergrensesnittet er på plass.")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Installerer eller reparerer EmneKlar i denne mappen.")
    parser.add_argument("--strict", action="store_true",
                        help="bruk bare de testede versjonene av avhengighetene (ingen reserve)")
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)  # handled by setup.bat
    args = parser.parse_args(argv)
    if args.strict:
        os.environ["EMNEKLAR_STRICT_PINS"] = "1"
    update.configure_stdio()
    reporter = update.Reporter(data_dir_from_env() / "logs" / "setup.log", total_steps=TOTAL_STEPS,
                               title="EmneKlar-oppsett")
    print("EmneKlar – oppsett")
    print(f"  Mappe: {ROOT}")
    try:
        base_python = check_python(reporter)
        python = ensure_venv(reporter, base_python)
        install_dependencies(reporter, python)
        ensure_frontend(reporter)
        version = verify(reporter, python)
        reporter.info()
        reporter.info(f"Oppsettet er ferdig – EmneKlar {version} er klar til bruk.")
        reporter.info("Neste steg: Kjør start.bat")
        return 0
    except (SetupError, update.UpdateError) as exc:
        message = update.describe_error(exc) if isinstance(exc, update.UpdateError) else str(exc)
        reporter.error(message)
        reporter.info()
        reporter.info("Oppsettet ble ikke fullført. Rett feilen og kjør setup.bat på nytt – det er trygt å kjøre den "
                      "flere ganger.")
        reporter.info(f"Logg: {reporter.log_path}")
        return 1
    except KeyboardInterrupt:
        reporter.error("Oppsettet ble avbrutt. Kjør setup.bat på nytt for å fullføre det.")
        return 1
    except Exception as exc:  # noqa: BLE001 - last line of defence: log it and keep the message readable
        reporter.log(traceback.format_exc())
        reporter.error(f"Uventet feil: {type(exc).__name__}: {exc}")
        reporter.info(f"Se loggen {reporter.log_path}, og kjør setup.bat på nytt.")
        return 1
    finally:
        reporter.close()


if __name__ == "__main__":
    sys.exit(main())
