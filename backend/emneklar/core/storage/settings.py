"""User settings: one typed Pydantic model persisted as JSON in the ``settings`` table.

Secrets are NEVER part of these settings – they live in the OS credential store.
New fields must have defaults so older databases keep working; unknown fields
from newer versions are ignored.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from emneklar.core.storage.db import Database
from emneklar.core.storage.models import Setting

SETTINGS_KEY = "app"

StartPage = Literal[
    "oversikt", "universell-utforming", "innholdskvalitet", "emnestruktur", "quizassistent", "emneforside",
    "canvas-verktoy", "rapporter",
]
AIStrategy = Literal["auto", "low_cost", "speed", "quality", "manual"]
ProviderType = Literal["openai", "anthropic", "azure_openai", "openai_compatible"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GeneralSettings(_Section):
    language: Literal["nb"] = "nb"
    theme: Literal["light", "dark", "system"] = "light"
    start_page: StartPage = "oversikt"
    default_course_id: str | None = None
    page_size: int = Field(25, ge=10, le=200)


class CanvasIdentity(_Section):
    id: str
    name: str


class CanvasSettings(_Section):
    base_url: str | None = None
    identity: CanvasIdentity | None = None
    last_verified_at: datetime | None = None


class AnalysisSettings(_Section):
    default_domains: list[Literal["accessibility", "content_quality", "structure", "quiz"]] = Field(
        default_factory=lambda: ["accessibility", "content_quality", "structure"]
    )
    regulatory_profile: str = "no-offentlig-2023"
    check_external_links: bool = True
    link_timeout_seconds: int = Field(10, ge=3, le=60)
    link_concurrency: int = Field(6, ge=1, le=16)
    link_per_host: int = Field(2, ge=1, le=4)
    link_cache_hours: int = Field(24, ge=0, le=336)
    check_documents: bool = True
    max_document_mb: int = Field(25, ge=1, le=200)
    canvas_concurrency: int = Field(3, ge=1, le=6)
    include_unpublished: bool = True


class PrivacySettings(_Section):
    allow_external_ai: bool = False
    confirm_before_send: bool = True
    snapshot_retention_days: int = Field(90, ge=1, le=3650)


class ProviderConfig(_Section):
    id: str
    type: ProviderType
    name: str
    enabled: bool = False
    endpoint: str | None = None
    api_version: str | None = None
    last_status: Literal["unknown", "ok", "error"] = "unknown"
    last_message: str | None = None
    last_checked_at: datetime | None = None


def default_providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(id="openai", type="openai", name="OpenAI", endpoint="https://api.openai.com/v1"),
        ProviderConfig(id="anthropic", type="anthropic", name="Anthropic", endpoint="https://api.anthropic.com"),
        ProviderConfig(id="azure", type="azure_openai", name="Azure OpenAI", api_version="2024-10-21"),
        ProviderConfig(id="local", type="openai_compatible", name="Lokal modell (Ollama / OpenAI-kompatibel)",
                       endpoint="http://127.0.0.1:11434/v1"),
    ]


class AISettings(_Section):
    providers: list[ProviderConfig] = Field(default_factory=default_providers)
    strategy: AIStrategy = "auto"
    # task type -> "provider_id/model_id" (used by strategy "manual", or as a pinned override)
    manual_models: dict[str, str] = Field(default_factory=dict)
    # task type -> provider id the user prefers for that task (soft preference)
    task_providers: dict[str, str] = Field(default_factory=dict)


class AppearanceSettings(_Section):
    text_size: Literal["normal", "large", "larger"] = "normal"
    density: Literal["comfortable", "compact"] = "comfortable"
    reduce_motion: Literal["system", "always"] = "system"
    underline_links: bool = True


class NotificationSettings(_Section):
    notify_job_complete: bool = True
    browser_notifications: bool = False


class AdvancedSettings(_Section):
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    update_repository: str = "oleandrw/EmneKlar"
    update_channel: Literal["stable", "prerelease"] = "stable"
    debug_logging: bool = False


class AppSettings(_Section):
    setup_completed: bool = False
    dry_run: bool = False
    current_course_id: str | None = None
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    canvas: CanvasSettings = Field(default_factory=CanvasSettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    ai: AISettings = Field(default_factory=AISettings)
    appearance: AppearanceSettings = Field(default_factory=AppearanceSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    advanced: AdvancedSettings = Field(default_factory=AdvancedSettings)

    def provider(self, provider_id: str) -> ProviderConfig | None:
        return next((p for p in self.ai.providers if p.id == provider_id), None)


class SettingsStore:
    """Thread-safe, cached access to :class:`AppSettings`."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.RLock()
        self._cache: AppSettings | None = None
        self._listeners: list[Callable[[AppSettings], None]] = []

    def get(self) -> AppSettings:
        with self._lock:
            if self._cache is None:
                with self._db.session() as session:
                    row = session.get(Setting, SETTINGS_KEY)
                    self._cache = AppSettings.model_validate(row.value) if row else AppSettings()
            return self._cache.model_copy(deep=True)

    def update(self, mutate: Callable[[AppSettings], None]) -> AppSettings:
        with self._lock:
            current = self.get()
            mutate(current)
            validated = AppSettings.model_validate(current.model_dump())
            with self._db.session() as session:
                row = session.get(Setting, SETTINGS_KEY)
                data = validated.model_dump(mode="json")
                if row is None:
                    session.add(Setting(key=SETTINGS_KEY, value=data))
                else:
                    row.value = data
            self._cache = validated
            listeners = list(self._listeners)
        for listener in listeners:
            listener(validated.model_copy(deep=True))
        return validated.model_copy(deep=True)

    def on_change(self, listener: Callable[[AppSettings], None]) -> None:
        self._listeners.append(listener)
