"""Version, settings, secrets, redaction, migrations."""

from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path

import pytest

from emneklar import __version__
from emneklar.config import REPO_DIR, ConfigError, RuntimeConfig
from emneklar.core.auth.secrets import MemorySecretStore
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.security.redaction import RedactingFilter, redact, register_secret
from emneklar.core.updates.version import Version


def test_version_is_consistent() -> None:
    version_file = (REPO_DIR / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = tomllib.loads((REPO_DIR / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == version_file == pyproject["project"]["version"]
    # MAJOR.MINOR.PATCH, or a pre-release of it (-alpha.N, -beta.N, -rc.N) as scripts/bump_version.py writes it.
    assert re.fullmatch(r"\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?", version_file), "VERSION must be semantic"
    parsed = Version.parse(version_file)
    assert parsed is not None and str(parsed) == version_file


def test_server_refuses_non_loopback_host(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        RuntimeConfig(host="0.0.0.0", data_dir=tmp_path).validate()


def test_data_dir_is_separate_from_code(config: RuntimeConfig) -> None:
    assert REPO_DIR not in config.data_dir.parents
    assert config.db_path.parent == config.data_dir


def test_migrations_create_schema_and_backup_before_upgrade(container: AppContainer) -> None:
    result = container.db.migrate(container.config.backups_dir)
    assert result.previous is None and result.current == container.db.head_revision()
    # Running again is a no-op and does not create a backup.
    again = container.db.migrate(container.config.backups_dir)
    assert again.previous == again.current and again.backup_path is None


def test_migrations_match_models(container: AppContainer) -> None:
    """Every model change must come with a migration (alembic autogenerate finds no difference)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from emneklar.core.storage.models import Base

    container.migrate()
    with container.db.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection, opts={"render_as_batch": True}), Base.metadata)
    assert diff == [], f"Models and migrations differ – add a migration: {diff}"


def test_settings_roundtrip_has_no_secret_fields(container: AppContainer) -> None:
    container.migrate()
    updated = container.settings.update(lambda s: setattr(s.canvas, "base_url", "https://canvas.example.edu"))
    assert updated.canvas.base_url == "https://canvas.example.edu"
    dumped = str(container.settings.get().model_dump()).lower()
    for word in ("token", "api_key", "password", "secret"):
        assert word not in dumped.replace("token_configured", ""), word


def test_secret_store_validates_and_registers_for_redaction() -> None:
    store = MemorySecretStore()
    with pytest.raises(AppError):
        store.set("canvas_token", "  ")
    with pytest.raises(AppError):
        store.set("not_a_known_name", "value-123456")
    store.set("canvas_token", "9999~supersecretvalue1234567890")
    assert "supersecretvalue" not in redact("token is 9999~supersecretvalue1234567890 ok")
    store.set("ai_key:openai", "sk-proj-abcdefghijklmnopqrstuvwxyz")
    assert store.get("ai_key:openai") == "sk-proj-abcdefghijklmnopqrstuvwxyz"


def test_redaction_patterns() -> None:
    register_secret("my-very-secret-value")
    text = ("Authorization: Bearer abcdefghijklmnop12345 x-api-key: sk-ant-abcdefghijklmnopqrstu "
            "https://x.example/f?verifier=SIGNED123&download=1 my-very-secret-value")
    out = redact(text)
    assert "abcdefghijklmnop12345" not in out
    assert "sk-ant-abcdefghijklmnopqrstu" not in out
    assert "SIGNED123" not in out
    assert "my-very-secret-value" not in out
    masked = redact("Incorrect API key provided: sk-proj-****************************abcd. You can find your API key")
    assert "abcd" not in masked and "sk-proj" not in masked, "the masked form a provider repeats is hidden too"


def test_logging_filter_redacts(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("emneklar.test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO):
        logger.info("Kaller Canvas med Authorization: Bearer 1234~%s", "z" * 30)
    assert "zzzzzzzzzz" not in caplog.text


def test_datetimes_come_back_timezone_aware(container: AppContainer) -> None:
    """SQLite drops UTC offsets; the API must still serialise UTC timestamps with an offset."""
    from datetime import UTC, datetime

    from emneklar.core.storage.models import Report

    container.migrate()
    with container.db.session() as session:
        row = Report(course_id="1", report_type="full", fmt="html", title="x", filename="x.html",
                     created_at=datetime(2026, 10, 6, 19, 33, tzinfo=UTC))
        session.add(row)
        session.flush()
        report_id = row.id
    with container.db.session() as session:
        stored = session.get(Report, report_id)
        assert stored is not None and stored.created_at.tzinfo is not None
        assert stored.created_at.isoformat() == "2026-10-06T19:33:00+00:00"
