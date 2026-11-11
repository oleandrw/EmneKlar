"""The thin layer between EmneKlar and the machine it runs on.

Everything that differs between Windows, macOS and Linux is decided here: where one user's data is kept, how a
folder is shown, how a message reaches the user when EmneKlar runs without a console window, how the user interface
is shown (a window of its own), and which bundled Python runtime belongs to the machine. The rest of the program
asks this module instead of testing ``sys.platform`` in many places.

Only the standard library is imported: ``scripts/setup.py`` and ``scripts/update.py`` use this module before the
dependencies are installed. Windows is the platform EmneKlar is released and tested for; what is known to work on
macOS and Linux – and what is missing – is listed in ``docs/PLATFORMS.md``.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import sysconfig
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path, PureWindowsPath


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


# -- showing the user interface -------------------------------------------------------------------------------------

#: Browsers that can show a page in a window of its own, without address bar or tabs (Chromium's ``--app=<url>``).
#: Microsoft Edge comes with Windows 10 and 11; Google Chrome is used when it is the default browser or Edge is missing.
APP_WINDOW_BROWSERS = ("msedge.exe", "chrome.exe")
_VENDOR_FOLDERS = {"msedge.exe": ("Microsoft", "Edge"), "chrome.exe": ("Google", "Chrome")}


def executable_in_command(command: str | None) -> str | None:
    """The program in a Windows open command, such as ``"C:\\…\\msedge.exe" --single-argument %1``."""
    text = (command or "").strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 1 else None
    end = text.lower().find(".exe")
    return text[:end + 4] if end > 0 else None


def choose_app_window_browser(default_command: str | None, installed: Sequence[Path], *,
                              exists: Callable[[Path], bool] = Path.is_file) -> Path | None:
    """The browser that draws EmneKlar's window: the default browser when it can show an app window, otherwise the
    first of ``installed`` (Edge before Chrome) that is on the machine. None: a normal browser tab is used."""
    default = executable_in_command(default_command)
    candidates = [Path(default)] if default and PureWindowsPath(default).name.lower() in APP_WINDOW_BROWSERS else []
    candidates += [path for path in installed if PureWindowsPath(path).name.lower() in APP_WINDOW_BROWSERS]
    return next((path for path in candidates if exists(path)), None)


def _registry_text(hive: str, key: str, name: str = "") -> str | None:
    """A text value from the registry of this user (``HKCU``), the machine (``HKLM``) or ``HKCR``; None if missing."""
    if sys.platform != "win32":
        return None
    import winreg

    roots = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCR": winreg.HKEY_CLASSES_ROOT}
    try:
        with winreg.OpenKey(roots[hive], key) as handle:
            value, kind = winreg.QueryValueEx(handle, name)
    except OSError:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return os.path.expandvars(value) if kind == winreg.REG_EXPAND_SZ else value


def _default_browser_command() -> str | None:
    """How Windows opens a web address for this user: the open command of the default browser."""
    for scheme in ("https", "http"):
        for choice in ("UserChoiceLatest", "UserChoice"):
            associations = "Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations"
            prog_id = _registry_text("HKCU", f"{associations}\\{scheme}\\{choice}", "ProgId")
            if prog_id:
                return _registry_text("HKCR", f"{prog_id}\\shell\\open\\command")
    return None


def _installed_app_window_browsers() -> list[Path]:
    """Where Edge and Chrome are registered or usually installed, Edge first. Not checked for existence here."""
    found: list[Path] = []
    for exe in APP_WINDOW_BROWSERS:
        for hive in ("HKCU", "HKLM"):
            registered = _registry_text(hive, f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe}")
            if registered:
                found.append(Path(registered.strip().strip('"')))
        for base in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            if os.environ.get(base):
                found.append(Path(os.environ[base], *_VENDOR_FOLDERS[exe], "Application", exe))
    return found


def app_window_browser() -> Path | None:
    """The browser that shows EmneKlar in a window of its own on this machine. None: a normal tab is used."""
    if sys.platform != "win32":
        return None  # only Windows is built and tested (docs/PLATFORMS.md); elsewhere EmneKlar opens in a tab
    return choose_app_window_browser(_default_browser_command(), _installed_app_window_browsers())


def _start_detached(command: list[str], cwd: Path) -> None:
    """Start a program that lives on after EmneKlar has stopped – the user's browser."""
    subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)  # a browser found above, given our own address


def open_user_interface(url: str) -> bool:
    """Show EmneKlar's user interface at ``url`` (EmneKlar's own address on 127.0.0.1).

    In a window of its own – Edge or Chrome in app mode: no address bar or tabs, a button of its own on the taskbar –
    where the machine has one of them; otherwise in a tab of the default browser. False: neither could be opened.
    The browser is started in its own folder, so it never keeps the program folder in use (updates, uninstalling).
    """
    browser = app_window_browser()
    if browser is not None:
        try:
            _start_detached([str(browser), f"--app={url}"], cwd=browser.parent)
            return True
        except OSError:
            pass  # e.g. removed since it was looked up: a normal tab still works
    return webbrowser.open(url)
