"""Which models the assistant uses: quality profile + the teacher's own choices, resolved against what is set up."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from emneklar.core.ai import images as image_catalog
from emneklar.core.ai import profiles
from emneklar.core.ai.router import TASKS, route
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
    note: str | None = None  # the teacher's own choice for the role is no longer available

    @property
    def primary(self) -> dict[str, Any] | None:
        return self.models[0] if self.models else None

    def as_dict(self) -> dict[str, Any]:
        def short(m: dict[str, Any]) -> dict[str, Any]:
            return {"provider_id": m["provider_id"], "model_id": m["model_id"], "display_name": m["display_name"],
                    "ref": f"{m['provider_id']}/{m['model_id']}"}

        return {"role": self.role, "label": profiles.role_labels().get(self.role, self.role),
                "primary": short(self.primary) if self.primary else None,
                "fallbacks": [short(m) for m in self.models[1:3]], "reason": self.reason, "note": self.note}


@dataclass
class ImageChoice:
    provider_id: str
    model: dict[str, Any] | None
    quality: str
    size: str
    reason: str
    available: bool
    unavailable_reason: str | None = None
    complexity: str = ""  # "" = not sent (the model's own default, or a model without the parameter)
    note: str | None = None  # the teacher's own choice of image model is no longer available

    def as_dict(self) -> dict[str, Any]:
        return {"provider_id": self.provider_id, "model": self.model, "quality": self.quality, "size": self.size,
                "complexity": self.complexity, "reason": self.reason, "available": self.available,
                "unavailable_reason": self.unavailable_reason, "note": self.note}


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
        vision = role == "illustration_review"
        chosen = profiles.preferred_models(profile, role, models, ready, vision=vision, override=override,
                                           min_quality=TASKS[role].min_quality)
        note = None

        def ref(m: dict[str, Any]) -> str:
            return f"{m['provider_id']}/{m['model_id']}"

        if override and not (chosen and ref(chosen[0]) == override):
            # The model the teacher chose for the role was switched off, removed or reclassified in the registry.
            note = (f"Modellen du valgte ({profiles.split(override)[1]}) er ikke lenger tilgjengelig. "
                    "En annen modell er valgt automatisk.")
        if chosen:
            first = chosen[0]
            if override and ref(first) == override:
                reason = f"Du har valgt {first['display_name']} for denne rollen."
            elif first.get("is_default"):
                reason = f"{first['display_name']} er standardmodellen din."
            elif int(first.get("priority") or 0) > 0:
                reason = f"{first['display_name']} har prioritet hos deg."
            else:
                reason = f"Kvalitetsprofilen «{profile.label}»: {first['display_name']}."
            roles[role] = RoleChoice(role, chosen, reason, note)
            continue
        fallback_settings = app.model_copy(deep=True)
        if fallback_settings.ai.strategy != "manual":
            fallback_settings.ai.strategy = profile.fallback_strategy  # type: ignore[assignment]
        decision = route(role, fallback_settings, models, ready, needs_vision=vision or None)
        found = [m for m in [decision.primary, *decision.fallbacks] if m is not None]
        reason = ("Ingen av kvalitetsprofilens modeller er tilgjengelige. " + decision.reason) if found else (
            decision.reason or "Ingen aktivert modell passer for rollen.")
        roles[role] = RoleChoice(role, found, reason, note)
    image = resolve_image(c, options, profile)
    return Choices(profile=profile, roles=roles, image=image)


def resolve_image(c: AppContainer, options: IllustrationSettings, profile: profiles.QualityProfile) -> ImageChoice:
    """The image model: the teacher's own choice, or the registry's enabled image models at the provider ordered by
    what the quality profile asks for (quality, speed, or the teacher's default and priority)."""
    provider_id = options.image_provider_id
    # «Prioriter lav kostnad» under Innstillinger also applies to the automatic choice of image model.
    strategy = "low_cost" if c.settings.get().ai.strategy == "low_cost" else profile.image_strategy
    plan = c.ai.image_plan(provider_id, options.image_model, summary="", strategy=strategy)
    model = plan.get("model")
    chosen = plan.get("chosen")
    if chosen == "manual":
        reason = "Du har valgt bildemodellen selv."
    elif chosen == "typed":
        reason = "Du har skrevet navnet på bildemodellen selv."
        if model is not None and not model.get("known"):
            reason += " Modellen er ikke i modellregisteret: referansebilder brukes ikke."
    elif model is not None and model.get("default"):
        reason = f"Kvalitetsprofilen «{profile.label}»: {model['label']} er standardmodellen din for bilder."
    else:
        reason = f"Kvalitetsprofilen «{profile.label}»."
    quality = image_catalog.quality_for(model, options.image_quality or profile.image_quality)
    complexity = options.image_complexity if model and options.image_complexity in model.get("complexities", ()) \
        else ""
    aspect = options.image_format if options.image_format != "auto" else "3:2"
    return ImageChoice(provider_id=provider_id, model=model, quality=quality,
                       size=image_catalog.size_for(model, aspect), reason=reason, available=bool(plan["available"]),
                       unavailable_reason=plan["reason"], complexity=complexity, note=plan.get("note"))


def image_providers(c: AppContainer) -> list[dict[str, Any]]:
    """Providers that can make images. Their models are not listed here: selectors read the model registry."""
    app = c.settings.get()
    return [{"id": p.id, "name": p.name, "type": p.type, "configured": c.ai.configured(p),
             "needs_model_name": p.type in image_catalog.NAMED_PROVIDER_TYPES}
            for p in app.ai.providers if p.type in image_catalog.IMAGE_PROVIDER_TYPES]
