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


AnalysisDomain = Literal["accessibility", "content_quality", "structure", "quiz"]


def _default_domains() -> list[AnalysisDomain]:
    return ["accessibility", "content_quality", "structure"]


class AnalysisSettings(_Section):
    default_domains: list[AnalysisDomain] = Field(default_factory=_default_domains)
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
    # GitHub "owner/repo" for update checks. None = use the install's own git remote (if any).
    update_repository: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
    update_channel: Literal["stable", "prerelease"] = "stable"
    check_updates: bool = True
    debug_logging: bool = False


class RagSettings(_Section):
    """Emne-RAG. Model ids refer to core/ai/local_models.json ("" = the catalog default)."""

    # local = sentence-transformers on this machine; provider = an OpenAI-compatible embeddings endpoint
    # (OpenAI, Azure OpenAI, or a local server such as Ollama); none = keyword search (BM25) only.
    embedding_backend: Literal["local", "provider", "none"] = "local"
    embedding_model: str = Field("", max_length=200)
    embedding_provider_id: str = Field("local", max_length=40)
    embedding_provider_model: str = Field("", max_length=200)
    reranker_enabled: bool = True
    reranker_model: str = Field("", max_length=200)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    # Videos without captions: local NB-Whisper, an AI provider (OpenAI, Azure OpenAI, own server) or not at all.
    transcription: Literal["local", "provider", "off"] = "local"
    transcription_provider_id: str = Field("openai", max_length=40)
    transcription_model: str = Field("", max_length=200)  # "" = catalog default (core/ai/transcription_models.json)
    transcription_language: str = Field("", max_length=8, pattern=r"^([a-z]{2,3})?$")  # "" = detected automatically
    whisper_model: Literal["auto", "tiny", "base", "small", "medium", "large"] = "auto"
    whisper_other_language_model: str = Field("", max_length=200)
    youtube_captions: bool = True
    vimeo_captions: bool = True
    candidates: int = Field(40, ge=10, le=100)
    top_k: int = Field(6, ge=3, le=10)
    query_rewrite: bool = False
    max_file_mb: int = Field(50, ge=1, le=500)
    max_video_mb: int = Field(2000, ge=10, le=20000)


class IllustrationSettings(_Section):
    """KI-bildeassistent (Canvas-verktøy). Model choices refer to core/ai/model_profiles.json and image_models.json;
    the per-role overrides are "provider_id/model_id" ("" = the quality profile decides)."""

    quality_profile: Literal["max", "balanced", "fast"] = "max"
    amount: Literal["low", "balanced", "high"] = "balanced"
    analysis_model: str = Field("", max_length=250)
    planning_model: str = Field("", max_length=250)
    review_model: str = Field("", max_length=250)
    image_provider_id: str = Field("openai", max_length=40)
    image_model: str = Field("", max_length=200)  # "" = the quality profile's image model
    image_quality: Literal["", "low", "medium", "high", "xhigh", "max"] = ""
    # "auto" = the planner picks the format per illustration (within the design profile); otherwise fixed.
    image_format: Literal["auto", "16:9", "3:2", "4:3", "1:1", "2:3"] = "auto"
    use_reference_images: bool = True
    captions: bool = True  # visible caption when it adds value (the teacher can switch it per image)
    # Short labels in diagrams, models, infographics and processes when they help understanding; "never" = text-free.
    text_in_images: Literal["auto", "never"] = "auto"
    credit: bool = True  # credit line under the image, separate from the caption
    credit_text: str = Field("KI-generert illustrasjon", max_length=200)
    max_width_px: int = Field(900, ge=240, le=2000)  # maximum display width in Canvas (responsive below it)
    folder: str = Field("EmneKlar-illustrasjoner", min_length=1, max_length=120, pattern=r"^[^\\/:*?\"<>|]+$")
    cost_limit_usd: float | None = Field(default=None, ge=0, le=10_000)
    concurrency: int = Field(2, ge=1, le=4)


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
    rag: RagSettings = Field(default_factory=RagSettings)
    illustrations: IllustrationSettings = Field(default_factory=IllustrationSettings)

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
