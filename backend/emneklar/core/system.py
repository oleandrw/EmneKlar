"""The thin layer between EmneKlar and the machine it runs on.

Everything that differs between Windows, macOS and Linux is decided here: where one user's data is kept, how a
folder is shown, how a message reaches the user when EmneKlar runs without a console window, and which bundled
Python runtime belongs to the machine. The rest of the program asks this module instead of testing
``sys.platform`` in many places.

Only the standard library is imported: ``scripts/setup.py`` and ``scripts/update.py`` use this module before the
dependencies are installed. Windows is the platform EmneKlar is released and tested for; what is known to work on
macOS and Linux – and what is missing – is listed in ``docs/PLATFORMS.md``.
"""

from __future__ import annotations

import os
import platform
import sys
import sysconfig
from pathlib import Path


class UnsupportedOnThisPlatform(RuntimeError):
    """The operation is only implemented (and tested) on Windows."""


# -- where one user's data lives ---------------------------------------------------------------------------------


def user_data_dir(folder: str) -> Path:
    """The per-user data folder of a program called ``folder``.

    Windows: ``%LOCALAPPDATA%\\<folder>``. macOS: ``~/Library/Application Support/<folder>``. Linux and others:
    ``$XDG_DATA_HOME/<folder in lower case>`` (``~/.local/share`` when the variable is not set).
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / folder
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / folder
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / folder.lower()


# -- which build of the bundled runtime fits this machine -----------------------------------------------------------


def platform_tag() -> str:
    """Names the bundled Python runtime for the running interpreter: ``win-amd64``, ``macos-arm64``, ``linux-x86_64`` …

    A release lists one runtime per tag in ``install.json``; a tag that is not listed means there is no bundled
    runtime for this machine (EmneKlar then runs in a Python environment made by ``setup``).
    """
    if sys.platform == "win32":
        return sysconfig.get_platform()  # win-amd64, win-arm64 or win32: the interpreter's own build
    machine = platform.machine().lower() or "unknown"
    if sys.platform == "darwin":
        return f"macos-{'arm64' if machine in ('arm64', 'aarch64') else machine}"
    return f"linux-{'x86_64' if machine == 'amd64' else machine}"


# -- talking to the user without a console window -------------------------------------------------------------------


_console_missing = False


def has_console() -> bool:
    """False when EmneKlar was started without a console window (``pythonw.exe`` from the shortcut): nothing that is
    printed can be seen, so a message the user must read needs :func:`tell_user`."""
    return not _console_missing and sys.stdout is not None and sys.stderr is not None


def prepare_standard_streams() -> None:
    """Without a console window Python has no standard streams (``sys.stdout`` is None), and code that writes to them
    directly would fail. They are replaced by streams that discard everything; :func:`has_console` keeps answering
    False. Called first thing by every process EmneKlar starts (the program, ``manage`` and the parser workers)."""
    global _console_missing
    if sys.stdout is not None and sys.stderr is not None:
        return
    _console_missing = True
    null = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - lives as long as the process
    if sys.stdout is None:
        sys.stdout = null
    if sys.stderr is None:
        sys.stderr = null


def _message_box(title: str, text: str, *, error: bool) -> None:
    """A message box. Implemented for Windows; elsewhere there is no way to show one yet (docs/PLATFORMS.md)."""
    if sys.platform != "win32":
        return
    import ctypes  # pragma: no cover - a real window

    ok, icon_error, icon_information, set_foreground = 0x0, 0x10, 0x40, 0x10000  # pragma: no cover
    flags = ok | (icon_error if error else icon_information) | set_foreground  # pragma: no cover
    ctypes.windll.user32.MessageBoxW(None, text, title, flags)  # pragma: no cover


def tell_user(title: str, text: str, *, error: bool = False) -> None:
    """A message the user must see. With a console it is printed (errors to standard error); without one it is shown
    in a message box. Never used for anything secret that should not stay on the screen."""
    if has_console():
        print(text, file=sys.stderr if error else sys.stdout, flush=True)
        return
    _message_box(title, text, error=error)


# -- showing a folder ---------------------------------------------------------------------------------------------


def open_folder(path: Path) -> None:
    """Show ``path`` in the file manager. Implemented for Windows Explorer; other platforms are not supported yet."""
    if sys.platform != "win32":
        raise UnsupportedOnThisPlatform("Å åpne mapper støttes bare på Windows.")
    os.startfile(path)  # noqa: S606 - callers pass fixed, known folders
