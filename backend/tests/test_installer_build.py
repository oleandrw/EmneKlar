"""scripts/build_installer.py and packaging/windows/EmneKlar.iss: the Windows installer.

Compiling and running the installer needs Inno Setup and Windows; that is done in the release workflow (install,
start, health check, uninstall). These tests cover what can be checked everywhere: the installer is put together
from exactly a release package and the runtime that package names, and the installer script keeps its promises
(per user, no administrator rights, no console window, EmneKlar is stopped first, user data is never removed).
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from emneklar.config import REPO_DIR
from tests.script_loader import load_script

update = load_script("update")
build_installer = load_script("build_installer")

ISS = REPO_DIR / "packaging" / "windows" / "EmneKlar.iss"
RUNTIME_ID = "cp314-0123456789ab"


def make_runtime(folder: Path, identifier: str = RUNTIME_ID) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / update.runtime_asset_name("win-amd64", identifier)
    interpreter = update.runtime_interpreter(Path()).as_posix()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(interpreter, "python")
        archive.writestr("Lib/site-packages/pakke.py", "x = 1")
        archive.writestr("runtime.json", json.dumps({"id": identifier, "platform": "win-amd64", "python": "3.14.10"}))
    return path


def make_package(folder: Path, runtime: Path | None, *, version: str = "0.3.0") -> Path:
    install: dict[str, object] = {"type": "release", "version": version, "repository": "acme/EmneKlar"}
    if runtime is not None:
        info = json.loads(zipfile.ZipFile(runtime).read("runtime.json"))
        install["runtimes"] = {"win-amd64": {"id": info["id"], "python": "3.14.10", "asset": runtime.name,
                                             "sha256": update.sha256_file(runtime), "size": runtime.stat().st_size}}
    files = {"VERSION": f"{version}\n", "install.json": json.dumps(install), "backend/pyproject.toml": "[project]\n",
             "backend/emneklar/__init__.py": "", "backend/emneklar/main.py": "APP = 1\n",
             "frontend/dist/index.html": "<!doctype html>",
             "start.bat": "@echo off\r\n", "update.bat": "@echo off\r\n", "scripts/update.py": "# updater\n"}
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"EmneKlar-{version}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(f"EmneKlar-{version}/{name}", text)
    return path


def test_the_installer_is_staged_from_the_package_and_the_runtime_it_names(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path / "ut")
    package = make_package(tmp_path / "ut", runtime)
    staged = tmp_path / "arbeid" / "installasjon"
    staged.parent.mkdir()
    assert build_installer.stage(package, runtime, staged) == "0.3.0"
    names = {p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()}
    interpreter = update.runtime_interpreter(Path()).as_posix()
    assert names == {"VERSION", "install.json", "backend/pyproject.toml", "backend/emneklar/__init__.py",
                     "backend/emneklar/main.py", "frontend/dist/index.html", "start.bat", "update.bat",
                     "scripts/update.py",
                     f"runtime/{interpreter}", "runtime/Lib/site-packages/pakke.py", "runtime/runtime.json"}
    # What is installed is what an installation updated by update.bat has: the runtime id matches install.json.
    assert update.installed_runtime_id(staged) == RUNTIME_ID and update.has_bundled_runtime(staged)


def test_a_runtime_the_package_does_not_name_is_refused(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path / "a")
    package = make_package(tmp_path / "a", runtime)
    other = make_runtime(tmp_path / "b", "cp314-ffffffffffff")
    with pytest.raises(build_installer.InstallerError, match="Pakken trenger"):
        build_installer.stage(package, other, tmp_path / "w1" / "installasjon")
    changed = make_runtime(tmp_path / "c")  # the right name, another content
    with zipfile.ZipFile(changed, "a") as archive:
        archive.writestr("ekstra.txt", "endret etter at pakken ble laget")
    (tmp_path / "w2").mkdir()
    with pytest.raises(build_installer.InstallerError, match="stemmer ikke med sjekksummen"):
        build_installer.stage(package, changed, tmp_path / "w2" / "installasjon")
    plain = make_package(tmp_path / "d", None)  # a package built without --runtime
    (tmp_path / "w3").mkdir()
    with pytest.raises(build_installer.InstallerError, match="uten kjøretid for win-amd64"):
        build_installer.stage(plain, runtime, tmp_path / "w3" / "installasjon")


def test_names_versions_and_compiler_arguments(tmp_path: Path) -> None:
    assert build_installer.output_name("0.3.0", test_build=False) == "EmneKlar-0.3.0-setup.exe"
    assert build_installer.output_name("0.3.0-rc.1", test_build=True) == "EmneKlar-0.3.0-rc.1-setup-test.exe"
    assert build_installer.numeric_version("0.3.0") == "0.3.0.0"
    assert build_installer.numeric_version("1.12.3-rc.2") == "1.12.3.0", "Windows wants four numbers"
    with pytest.raises(build_installer.InstallerError):
        build_installer.numeric_version("ikke-en-versjon")
    arguments = build_installer.compiler_arguments("0.3.0-rc.1", tmp_path / "kilde", tmp_path / "ut", test_build=False,
                                                   sign=None)
    assert arguments == ["/DAppVersion=0.3.0-rc.1", "/DNumericVersion=0.3.0.0", f"/DSourceDir={tmp_path / 'kilde'}",
                         f"/DOutputDir={tmp_path / 'ut'}", "/Qp", str(ISS)]
    assert not any("Sign" in argument for argument in arguments), "nothing is signed unless a command is given"
    signed = build_installer.compiler_arguments("0.3.0", tmp_path, tmp_path, test_build=True,
                                                sign="signtool sign /fd sha256 $f")
    assert "/DTestBuild" in signed and "/DSignToolName=emneklarsign" in signed
    assert "/Semneklarsign=signtool sign /fd sha256 $f" in signed


def test_without_inno_setup_the_build_says_what_is_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("ISCC", "LOCALAPPDATA", "PROGRAMFILES(X86)", "PROGRAMFILES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(build_installer.shutil, "which", lambda _name: None)
    with pytest.raises(build_installer.InstallerError, match="Fant ikke Inno Setup 6"):
        build_installer.find_iscc(None)
    compiler = tmp_path / "ISCC.exe"
    compiler.write_text("", encoding="utf-8")
    assert build_installer.find_iscc(str(compiler)) == compiler


# -- scripts/local_update_test.py: the "next release" it makes is a real one ---------------------------------------------


def test_the_release_made_for_the_local_update_test_is_what_the_updater_accepts(tmp_path: Path) -> None:
    local = load_script("local_update_test")
    runtime = make_runtime(tmp_path / "ut")
    package = make_package(tmp_path / "ut", runtime)
    installed = update.release_runtimes(json.loads(zipfile.ZipFile(package).read("EmneKlar-0.3.0/install.json")))["win-amd64"]
    release_dir = tmp_path / "utgivelse"
    release_dir.mkdir()

    new_runtime = local.next_runtime(runtime, installed, release_dir)
    assert new_runtime.id != installed.id and update.RUNTIME_ID_RE.match(new_runtime.id)
    assert new_runtime.asset == update.runtime_asset_name("win-amd64", new_runtime.id)
    update.verify_runtime_archive(release_dir / new_runtime.asset, new_runtime)
    update.extract_runtime(release_dir / new_runtime.asset, tmp_path / "runtime", new_runtime)

    assert local.next_version("0.3.0") == "0.3.1" and local.next_version("1.9.9-rc.2") == "1.9.10"
    new = local.make_release(package, "0.3.0", new_runtime, release_dir, broken=False)
    assert new == "0.3.1"
    archive = release_dir / "EmneKlar-0.3.1.zip"
    update.verify_checksum(archive, (release_dir / "EmneKlar-0.3.1.zip.sha256").read_text(encoding="ascii"))
    tree = update.extract_release(archive, tmp_path / "staging")
    version = update.read_version_file(tree / "VERSION")
    assert str(version) == "0.3.1"
    update.validate_release_tree(tree, version)
    info = json.loads((tree / "install.json").read_text(encoding="utf-8"))
    assert update.release_runtimes(info)["win-amd64"] == new_runtime and info["repository"] == local.REPOSITORY
    assert (tree / "backend" / "emneklar" / "main.py").read_text(encoding="utf-8") == "APP = 1\n"
    listed = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    assert listed == {"version": "0.3.1", "assets": ["EmneKlar-0.3.1.zip", "EmneKlar-0.3.1.zip.sha256",
                                                     new_runtime.asset]}

    # --same-runtime: nothing to fetch, so the runtime file is not part of the release folder.
    same_dir = tmp_path / "samme"
    same_dir.mkdir()
    local.make_release(package, "0.3.0", installed, same_dir, broken=False)
    assert json.loads((same_dir / "release.json").read_text(encoding="utf-8"))["assets"] == [
        "EmneKlar-0.3.1.zip", "EmneKlar-0.3.1.zip.sha256"]
    # --break-new-version: a release that cannot start – the update must roll back.
    broken_dir = tmp_path / "odelagt"
    broken_dir.mkdir()
    local.make_release(package, "0.3.0", installed, broken_dir, broken=True)
    broken = update.extract_release(broken_dir / "EmneKlar-0.3.1.zip", tmp_path / "staging-odelagt")
    assert (broken / "backend" / "emneklar" / "main.py").read_text(encoding="utf-8").startswith("raise RuntimeError(")


def test_the_local_update_test_never_uses_the_real_data_folder_or_opens_a_browser(tmp_path: Path) -> None:
    local = load_script("local_update_test")
    env = local.environment(tmp_path / "data", 8799)
    assert env["EMNEKLAR_DATA_DIR"] == str(tmp_path / "data") and env["EMNEKLAR_PORT"] == "8799"
    assert env["EMNEKLAR_SECRET_BACKEND"] == "memory", "no entry is written to the Windows Credential Manager"
    assert env["EMNEKLAR_NO_BROWSER"] == "1"


# -- the installer script ------------------------------------------------------------------------------------------------


def script() -> str:
    raw = ISS.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Inno Setup reads the Norwegian texts as UTF-8 only with a byte order mark"
    return raw.decode("utf-8-sig")


def setting(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}=(.*)$", text, re.MULTILINE)
    assert match, f"{name} is missing in [Setup]"
    return match.group(1).strip()


def test_the_installer_is_per_user_and_needs_no_administrator_rights() -> None:
    text = script()
    assert setting(text, "PrivilegesRequired") == "lowest"
    assert setting(text, "DefaultDirName") == "{localappdata}\\Programs\\{#DirName}"
    assert setting(text, "DisableDirPage") == "yes", "a fixed folder the updater can write in"
    assert "{commonpf" not in text and "{autopf" not in text and "HKLM" not in text
    assert setting(text, "ArchitecturesAllowed") == "x64compatible" and setting(text, "MinVersion") == "10.0"
    assert 'MessagesFile: "compiler:Languages\\Norwegian.isl"' in text


def test_the_test_build_is_a_separate_installation() -> None:
    text = script()
    ids = re.findall(r'#define AppIdValue "\{\{([0-9A-F-]{36})\}"', text)
    assert len(ids) == 2 and len(set(ids)) == 2, "the test build never replaces or removes a normal installation"
    assert '#define DirName "EmneKlar-test"' in text and '#define DirName "EmneKlar"' in text
    assert '#define AppName "EmneKlar (test)"' in text and '#define AppName "EmneKlar"' in text


def test_the_test_build_gets_a_data_folder_and_a_port_of_its_own() -> None:
    """«EmneKlar (test)» must never open, copy or change the user's real data – whatever starts it. The installer
    writes emneklar.local.json for the test build only; an ordinary installation uses the standard folder."""
    from emneklar.config import DEFAULT_PORT, LOCAL_FILE

    text = script()
    test_part, normal_part = text.split("#ifdef TestBuild", 1)[1].split("#else", 1)
    normal_part = normal_part.split("#endif", 1)[0]
    assert '#define DataDir "{localappdata}\\EmneKlar-test-data"' in test_part
    assert f'#define LocalPort "{DEFAULT_PORT}"' not in test_part and '#define LocalPort "8791"' in test_part
    assert '#define DataDir "{localappdata}\\EmneKlar"' in normal_part and "LocalPort" not in normal_part
    code = text.split("[Code]", 1)[1]
    writer = code.split("procedure WriteLocalDefaults();", 1)[1].split("#endif", 1)[0]
    assert f"{{app}}\\{LOCAL_FILE}" in writer and '"data_dir": "' in writer and '"port": {#LocalPort}' in writer
    assert '"keyring_service": "{#LocalKeyring}"' in writer and '#define LocalKeyring "EmneKlar-test"' in test_part
    assert "LocalKeyring" not in normal_part, "an ordinary installation keeps its secrets under «EmneKlar»"
    assert "SaveStringsToUTF8File" in writer, "UTF-8: a user name with æøå must survive"
    assert code.count("WriteLocalDefaults();") == 2 and code.count("#ifdef LocalPort") == 2, "only in the test build"
    post_install = code.split("procedure CurStepChanged", 1)[1]
    assert post_install.index("WriteLocalDefaults();") < post_install.index("scripts\\setup.py"), \
        "written before anything of EmneKlar is run"
    assert f'Type: files; Name: "{{app}}\\{LOCAL_FILE}"' in text.split("[UninstallDelete]", 1)[1]
    assert "{localappdata}\\EmneKlar\\logs" not in code and "ExpandConstant('{#DataDir}')" in code


def test_shortcuts_start_emneklar_without_a_console_window_and_there_is_a_way_to_stop_it() -> None:
    text = script()
    icons = text.split("[Icons]", 1)[1].split("[Run]", 1)[0]
    entries = [line for line in icons.splitlines() if line.startswith("Name:")]
    assert len(entries) == 3
    for entry in entries:
        assert 'Filename: "{app}\\runtime\\pythonw.exe"' in entry, "pythonw.exe: no console window"
        assert 'WorkingDir: "{app}"' in entry and 'IconFilename: "{app}\\EmneKlar.ico"' in entry
    start, stop, desktop = entries
    assert start.startswith('Name: "{group}\\{#AppName}"') and 'Parameters: "-m emneklar"' in start
    assert stop.startswith('Name: "{group}\\Avslutt {#AppName}"') and 'Parameters: "-m emneklar.manage stop"' in stop
    assert desktop.startswith('Name: "{autodesktop}\\{#AppName}"') and "Tasks: desktopicon" in desktop
    assert "start.bat" not in icons and "cmd.exe" not in icons


def test_a_running_emneklar_is_stopped_before_files_are_replaced_or_removed() -> None:
    text = script()
    code = text.split("[Code]", 1)[1]
    assert "-m emneklar.manage stop --timeout 30" in code
    for function in ("function PrepareToInstall", "function InitializeUninstall"):
        body = code.split(function, 1)[1].split("\nend;", 1)[0]
        assert "StopEmneKlar()" in body, function
    assert "En nyere versjon av EmneKlar" in code, "an older installer never replaces a newer version"
    assert setting(text, "CloseApplications") == "no"


def test_the_installer_installs_no_python_downloads_nothing_and_checks_the_result() -> None:
    text = script()
    assert not re.search(r"https?://(?!github\.com/oleandrw/EmneKlar)", text), "no download address in the installer"
    assert "pip" not in text.lower().replace("skipifsilent", "") and "python.org" not in text
    code = text.split("[Code]", 1)[1]
    assert "scripts\\setup.py" in code and "--no-pause" in code, "the same check as setup.bat, after the files are in place"


def test_user_data_is_never_removed_by_install_or_uninstall() -> None:
    text = script()
    for section in ("[InstallDelete]", "[UninstallDelete]"):
        body = text.split(section, 1)[1].split("\n[", 1)[0]
        names = re.findall(r'Name: "([^"]+)"', body)
        assert names and all(name.startswith("{app}") for name in names), f"{section} only touches the program folder"
        assert not any("localappdata" in name.lower() or "userappdata" in name.lower() for name in names)
    code = text.split("[Code]", 1)[1]
    assert "DelTree" not in code and "DeleteFile" not in code and "RemoveDir" not in code
    assert "ligger fortsatt i" in code, "the uninstaller says where the data is"


def test_the_icon_is_a_real_ico_file() -> None:
    icon = (REPO_DIR / "packaging" / "windows" / "EmneKlar.ico").read_bytes()
    assert icon[:4] == b"\x00\x00\x01\x00" and int.from_bytes(icon[4:6], "little") >= 5, "several sizes"


def drawing(text: str) -> list[list[tuple[str, str, str]]]:
    """Path data, colours and stroke widths of an SVG drawing, in order (JSX or plain SVG attribute names)."""
    paths = re.findall(r"<path\b(.*?)/>", text, re.DOTALL)
    return [re.findall(r'\bd="([^"]+)"|(?:fill|stroke)="(#[0-9a-f]{6})"|stroke-?[wW]idth="([\d.]+)"', path)
            for path in paths]


def test_the_window_the_shortcuts_and_the_installer_show_the_emneklar_logo() -> None:
    shell = (REPO_DIR / "frontend" / "src" / "core" / "layout" / "AppShell.tsx").read_text(encoding="utf-8")
    logo = shell[shell.index("export function BrandMark"):shell.index("</svg>", shell.index("export function BrandMark"))]
    favicon = (REPO_DIR / "frontend" / "public" / "favicon.svg").read_text(encoding="utf-8")
    assert len(drawing(logo)) == 4 and drawing(favicon) == drawing(logo), "favicon.svg is the logo of the program"

    from PIL import Image

    with Image.open(REPO_DIR / "packaging" / "windows" / "EmneKlar.ico") as icon:
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(icon.info["sizes"])
        icon.size = (256, 256)
        image = icon.convert("RGBA")
    # Points in the logo's own units (the 36 x 36 box of BrandMark); the icon shows the square from (2, 1.75), 32 wide.
    def colour(x: float, y: float) -> tuple[int, ...]:
        return image.getpixel((round((x - 2) * 8), round((y - 1.75) * 8)))

    def near(found: tuple[int, ...], hex_colour: str) -> bool:
        wanted = tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
        return found[3] > 200 and all(abs(a - b) <= 24 for a, b in zip(found[:3], wanted, strict=True))

    assert near(colour(10, 25), "#34d399"), "the green left page"
    assert near(colour(26, 25), "#60a5fa"), "the blue right page"
    assert near(colour(24, 22.3), "#0f2342"), "the check mark"
    assert colour(2.5, 2.5)[3] == 0 and colour(33.5, 33)[3] == 0, "no background: the corners are transparent"
