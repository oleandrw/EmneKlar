"""Defaults for one installation (``emneklar.local.json`` in the program folder, see config.py).

The test build of the installer writes the file, so that «EmneKlar (test)» keeps its own data folder and port
whatever starts it – the shortcut, start.bat, update.bat or setup.bat – and can never open, copy or change the
user's real data by accident. The file is never part of a release.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emneklar import config as config_module
from emneklar import manage
from emneklar.config import DEFAULT_PORT, LOCAL_FILE, RuntimeConfig
from emneklar.core import system
from tests.script_loader import load_script

package_release = load_script("package_release")


@pytest.fixture
def program_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A program folder of its own, with no EMNEKLAR_* variables set (as when EmneKlar is started from a shortcut)."""
    folder = tmp_path / "Programs" / "EmneKlar-test"
    folder.mkdir(parents=True)
    monkeypatch.setattr(config_module, "REPO_DIR", folder)
    for name in ("EMNEKLAR_DATA_DIR", "EMNEKLAR_PORT", "EMNEKLAR_HOST", "EMNEKLAR_DEV"):
        monkeypatch.delenv(name, raising=False)
    # The "standard" folder of this test – never the real one.
    monkeypatch.setattr(system, "user_data_dir", lambda name: tmp_path / "Local" / name)
    monkeypatch.setattr(config_module, "user_data_dir", lambda name: tmp_path / "Local" / name)
    return folder


def write_local(folder: Path, content: object, *, bom: bool = False) -> None:
    text = content if isinstance(content, str) else json.dumps(content)
    (folder / LOCAL_FILE).write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def test_without_the_file_everything_is_standard(program_folder: Path, tmp_path: Path) -> None:
    assert config_module.installation_defaults() == {}
    assert config_module.default_data_dir() == tmp_path / "Local" / "EmneKlar" == config_module.standard_data_dir()
    assert config_module.default_port() == DEFAULT_PORT and config_module.uses_standard_data_dir()
    loaded = RuntimeConfig.from_env()
    assert loaded.data_dir == tmp_path / "Local" / "EmneKlar" and loaded.port == DEFAULT_PORT


@pytest.mark.parametrize("bom", [False, True])
def test_an_installation_with_the_file_has_its_own_data_folder_and_port(program_folder: Path, tmp_path: Path,
                                                                       bom: bool) -> None:
    own = tmp_path / "Local" / "EmneKlar-test-data æøå"
    write_local(program_folder, {"data_dir": str(own), "port": 8791}, bom=bom)
    assert config_module.default_data_dir() == own and config_module.default_port() == 8791
    assert not config_module.uses_standard_data_dir(), "nothing is copied from the old folder name"
    loaded = RuntimeConfig.from_env()
    assert loaded.data_dir == own and loaded.port == 8791 and loaded.db_path == own / "database.db"
    # The maintenance commands – and with them update.bat and setup.bat – use the same folder.
    assert manage.data_dir_from_env() == own


def test_environment_variables_win_over_the_file(program_folder: Path, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    write_local(program_folder, {"data_dir": str(tmp_path / "egen"), "port": 8791})
    monkeypatch.setenv("EMNEKLAR_DATA_DIR", str(tmp_path / "valgt"))
    monkeypatch.setenv("EMNEKLAR_PORT", "8802")
    loaded = RuntimeConfig.from_env()
    assert loaded.data_dir == tmp_path / "valgt" and loaded.port == 8802
    assert manage.data_dir_from_env() == tmp_path / "valgt"
    assert not config_module.uses_standard_data_dir()


@pytest.mark.parametrize("content", ["ikke json", "[]", '{"data_dir": "relativ\\\\mappe"}', '{"data_dir": ""}',
                                     '{"data_dir": 5, "port": "8791"}', '{"port": 80}', '{"port": true}'])
def test_a_file_that_is_not_understood_changes_nothing(program_folder: Path, tmp_path: Path, content: str) -> None:
    write_local(program_folder, content)
    assert config_module.default_data_dir() == tmp_path / "Local" / "EmneKlar"
    assert config_module.default_port() == DEFAULT_PORT


def test_an_installation_can_keep_its_secrets_apart(program_folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A token saved in «EmneKlar (test)» must not replace the one an ordinary installation uses: the credential
    store service is part of the installation's defaults too."""
    from emneklar.core.auth import secrets

    made: list[str] = []
    monkeypatch.setattr(secrets, "KeyringSecretStore", lambda service: made.append(service) or object())
    assert secrets.keyring_service() == "EmneKlar" == secrets.KEYRING_SERVICE
    secrets.create_secret_store("keyring")
    write_local(program_folder, {"data_dir": str(program_folder / "data"), "keyring_service": "EmneKlar-test"})
    assert secrets.keyring_service() == "EmneKlar-test"
    secrets.create_secret_store("keyring")
    assert made == ["EmneKlar", "EmneKlar-test"]
    assert isinstance(secrets.create_secret_store("memory"), secrets.MemorySecretStore)
    for bad in ("", "   ", "../annet", "a" * 80, 5, None):
        write_local(program_folder, {"keyring_service": bad})
        assert secrets.keyring_service() == "EmneKlar", bad


def test_the_file_is_never_part_of_a_release() -> None:
    assert package_release.classify(LOCAL_FILE) == "unknown", "not a program file: a package with it would not build"
    assert LOCAL_FILE not in package_release.PACKAGED_FILES
    assert not (config_module.REPO_DIR / LOCAL_FILE).exists(), "the development folder has none"
