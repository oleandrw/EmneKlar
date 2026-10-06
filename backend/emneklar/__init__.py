"""EmneKlar – lokal analyse, kvalitetssikring og forbedring av Canvas-emner."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "EmneKlar"


def _read_version() -> str:
    """The repository's VERSION file is the single source of truth."""
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        from importlib.metadata import version

        return version("emneklar")
    except Exception:  # noqa: BLE001 - never fail on version lookup
        return "0.0.0"


__version__ = _read_version()
