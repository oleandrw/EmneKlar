"""Which models the assistant uses: quality profile + the teacher's own choices, resolved against what is set up."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from emneklar.core.ai import images as image_catalog
from emneklar.core.ai import profiles
from emneklar.core.ai.router import route
from emneklar.core.container import AppContainer
from emneklar.core.storage.settings import IllustrationSettings

ROLES = ("illustration_analysis", "illustration_planning", "illustration_review", "illustration_design")
OVERRIDE_FIELD = {"illustration_analysis": "analysis_model", "illustration_planning": "planning_model",
                  "illustration_review": "review_model", "illustration_design": "planning_model"}


@dataclass
class RoleChoice:
    role: str
    models: list[dict[str, Any]] = field(default_factory=list)  # usable, in order
    reason: str = ""

    @property
    def primary(self) -> dict[str, Any] | None:
        return self.models[0] if self.models else None

    def as_dict(self) -> dict[str, Any]:
        def short(m: dict[str, Any]) -> dict[str, Any]:
            return {"provider_id": m["provider_id"], "model_id": m["model_id"], "display_name": m["display_name"],
                    "ref": f"{m['provider_id']}/{m['model_id']}"}

        return {"role": self.role, "label": profiles.role_labels().get(self.role, self.role),
                "primary": short(self.primary) if self.primary else None,
                "fallbacks": [short(m) for m in self.models[1:3]], "reason": self.reason}


@dataclass
class ImageChoice:
    provider_id: str
    model: dict[str, Any] | None
    quality: str
    size: str
    reason: str
    available: bool
    unavailable_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"provider_id": self.provider_id, "model": self.model, "quality": self.quality, "size": self.size,
                "reason": self.reason, "available": self.available, "unavailable_reason": self.unavailable_reason}


@dataclass
class Choices:
    profile: profiles.QualityProfile
    roles: dict[str, RoleChoice]
    image: ImageChoice

    def as_dict(self) -> dict[str, Any]:
        return {"profile": self.profile.as_dict(), "roles": {k: v.as_dict() for k, v in self.roles.items()},
                "image": self.image.as_dict()}


def resolve(c: AppContainer, options: IllustrationSettings) -> Choices:
    app = c.settings.get()
    profile = profiles.get(options.quality_profile)
    models = c.ai.registry.list()
    ready = c.ai.readiness(app)
    roles: dict[str, RoleChoice] = {}
    for role in ROLES:
        override = getattr(options, OVERRIDE_FIELD[role]) or None
        chosen = profiles.preferred_models(profile, role, models, ready, vision=role == "illustration_review",
                                           override=override)
        if chosen:
            first = chosen[0]
            if override and f"{first['provider_id']}/{first['model_id']}" == override:
                reason = f"Du har valgt {first['display_name']} for denne rollen."
            else:
                reason = f"Kvalitetsprofilen «{profile.label}»: {first['display_name']}."
            roles[role] = RoleChoice(role, chosen, reason)
            continue
        fallback_settings = app.model_copy(deep=True)
        if fallback_settings.ai.strategy != "manual":
            fallback_settings.ai.strategy = profile.fallback_strategy  # type: ignore[assignment]
        decision = route(role, fallback_settings, models, ready, needs_vision=role == "illustration_review" or None)
        found = [m for m in [decision.primary, *decision.fallbacks] if m is not None]
        reason = ("Ingen av kvalitetsprofilens modeller er tilgjengelige. " + decision.reason) if found else (
            decision.reason or "Ingen aktivert modell passer for rollen.")
        roles[role] = RoleChoice(role, found, reason)
    image = resolve_image(c, options, profile)
    return Choices(profile=profile, roles=roles, image=image)


def resolve_image(c: AppContainer, options: IllustrationSettings, profile: profiles.QualityProfile) -> ImageChoice:
    app = c.settings.get()
    provider_id = options.image_provider_id
    config = app.provider(provider_id)
    model_id = options.image_model
    reason = "Du har valgt bildemodellen selv."
    if not model_id:
        preferred = [profiles.split(ref) for ref in profile.image_models]
        model_id = next((m for p, m in preferred if p == provider_id), "")
        reason = f"Kvalitetsprofilen «{profile.label}»."
    plan = c.ai.image_plan(provider_id, model_id, summary="")
    model = plan.get("model")
    quality = options.image_quality or profile.image_quality
    if model and model.get("qualities") and quality not in model["qualities"]:
        quality = "high" if "high" in model["qualities"] else model["qualities"][-1]
    from emneklar.core.ai.images import resolve as resolve_catalog

    catalog_model = resolve_catalog(config.type, model["id"]) if config is not None and model else None
    aspect = options.image_format if options.image_format != "auto" else "3:2"
    size = catalog_model.size_for(aspect) if catalog_model else "1536x1024"
    if config is not None and config.type == "openai_compatible" and model is not None and not model.get("known"):
        reason += " Modellen er ikke i katalogen: referansebilder brukes ikke."
    return ImageChoice(provider_id=provider_id, model=model, quality=quality, size=size, reason=reason,
                       available=bool(plan["available"]), unavailable_reason=plan["reason"])


def image_providers(c: AppContainer) -> list[dict[str, Any]]:
    app = c.settings.get()
    return [{"id": p.id, "name": p.name, "type": p.type, "configured": c.ai.configured(p),
             "models": [m.as_dict() for m in image_catalog.catalog() if m.provider_type == p.type],
             "needs_model_name": p.type in ("azure_openai", "openai_compatible")}
            for p in app.ai.providers if p.type in image_catalog.IMAGE_PROVIDER_TYPES]
