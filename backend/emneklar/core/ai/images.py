"""Image generation models as features see them – built from the model registry, never from a list of its own.

Image generation is a kind of model in the registry (``ai_models.kind == "image"``, :mod:`emneklar.core.ai.catalog`).
This module turns a registry row into the description the KI-bildeassistent works with (which qualities, sizes,
reference images and other parameters the model supports) and makes a request fit the model: a parameter the model
does not support is never sent.
"""

from __future__ import annotations

from typing import Any

from emneklar.core.ai.base import ImageGenerationRequest
from emneklar.core.ai.catalog import ASPECT_RATIOS, DEFAULT_PARAMS, STANDARD_SIZES, load_catalog

__all__ = ["ASPECT_RATIOS", "IMAGE_PROVIDER_TYPES", "NAMED_PROVIDER_TYPES", "describe", "fit", "note", "size_for"]

#: Provider types whose API has an image generation endpoint (OpenAI Image API or a compatible one).
IMAGE_PROVIDER_TYPES = ("openai", "azure_openai", "openai_compatible")
#: Providers where the model is a name the user decides (an Azure deployment, a model on an own server): a name that
#: is not in the registry is accepted, with the capabilities every OpenAI-compatible image API has.
NAMED_PROVIDER_TYPES = ("azure_openai", "openai_compatible")
#: Models without arbitrary sizes (unknown deployments, own servers) get the nearest standard size.
STANDARD_FOR_ASPECT = {"16:9": "1536x1024", "3:2": "1536x1024", "4:3": "1536x1024", "1:1": "1024x1024",
                       "2:3": "1024x1536"}


def note() -> str:
    return str(load_catalog().get("image_note") or "")


def describe(row: dict[str, Any] | None, *, model_id: str = "", provider_type: str = "",
             known: bool = True) -> dict[str, Any]:
    """An image model as the assistant uses it. ``row`` is a registry row; without one (a typed name) the model gets
    the conservative defaults and ``known`` False."""
    params = dict(DEFAULT_PARAMS["image"]) if row is None else dict(row["params"])
    name = model_id or (row["model_id"] if row else "")
    return {"id": name, "label": (row["display_name"] if row and known else name) or name,
            "provider_id": row["provider_id"] if row else "", "provider_type": provider_type,
            "description": (row.get("description") or "") if row else "",
            "quality_class": row["quality_class"] if row else 3, "speed_class": row["speed_class"] if row else 2,
            "reference_images": bool(params["reference_images"]),
            "max_reference_images": int(params["max_reference_images"]), "qualities": list(params["qualities"]),
            "sizes": list(params["sizes"]), "aspect_sizes": dict(params["aspect_sizes"]),
            "complexities": list(params["complexities"]), "input_fidelity": bool(params["input_fidelity"]),
            "default": bool(row.get("is_default")) if row else False, "known": known and row is not None}


def size_for(model: dict[str, Any] | None, aspect_ratio: str) -> str:
    """The request size for an aspect ratio: exact when the model supports it, else the nearest standard size."""
    exact = ((model or {}).get("aspect_sizes") or {}).get(aspect_ratio)
    return str(exact) if exact else STANDARD_FOR_ASPECT.get(aspect_ratio, STANDARD_SIZES[0])


def quality_for(model: dict[str, Any] | None, wanted: str) -> str:
    """The wanted quality when the model has it, else the best one it has up to «high»."""
    qualities = list((model or {}).get("qualities") or DEFAULT_PARAMS["image"]["qualities"])
    if wanted in qualities:
        return wanted
    return "high" if "high" in qualities else qualities[-1]


def fit(request: ImageGenerationRequest, model: dict[str, Any]) -> ImageGenerationRequest:
    """The request with only what ``model`` supports: quality within its levels, complexity and input fidelity only
    when it has them, reference images only when it takes them (and never more than it takes)."""
    references = list(request.reference_images[: int(model.get("max_reference_images") or 0)]) \
        if model.get("reference_images") else []
    return request.model_copy(update={
        "quality": quality_for(model, request.quality),
        "complexity": request.complexity if request.complexity in (model.get("complexities") or ()) else None,
        "input_fidelity": request.input_fidelity if model.get("input_fidelity") and references else None,
        "reference_images": references,
    })
