"""Catalog of image generation models (``image_models.json``) – no model names in features.

Image generation is a separate capability from text models: the router's registry (``ai_models``) describes models
that *read* text and images; this catalog describes models that *create* images. Adding another image generator later
means adding an entry here (and, for a new API family, implementing :meth:`AIProvider.generate_image`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "image_models.json"
#: Provider types whose API has an image generation endpoint (OpenAI Image API or a compatible one).
IMAGE_PROVIDER_TYPES = ("openai", "azure_openai", "openai_compatible")
DEFAULT_QUALITIES = ("low", "medium", "high")
DEFAULT_SIZES = ("1536x1024", "1024x1024", "1024x1536")
ASPECT_RATIOS = ("16:9", "3:2", "4:3", "1:1", "2:3")
#: Models without arbitrary sizes (unknown deployments, own servers) get the nearest standard size.
STANDARD_FOR_ASPECT = {"16:9": "1536x1024", "3:2": "1536x1024", "4:3": "1536x1024", "1:1": "1024x1024",
                       "2:3": "1024x1536"}


@dataclass(frozen=True)
class ImageModel:
    id: str
    label: str
    provider_type: str
    description: str = ""
    quality_class: int = 3
    speed_class: int = 2
    reference_images: bool = False
    max_reference_images: int = 0
    qualities: tuple[str, ...] = DEFAULT_QUALITIES
    sizes: tuple[str, ...] = DEFAULT_SIZES
    input_fidelity: bool = False
    default: bool = False
    known: bool = True  # False for a deployment/model name the user typed (capabilities unknown)
    aspect_sizes: tuple[tuple[str, str], ...] = ()

    def size_for(self, aspect_ratio: str) -> str:
        """The request size for an aspect ratio (exact when the model supports it, else the nearest standard)."""
        sizes = dict(self.aspect_sizes)
        return sizes.get(aspect_ratio) or STANDARD_FOR_ASPECT.get(aspect_ratio, DEFAULT_SIZES[0])

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "provider_type": self.provider_type,
                "description": self.description, "quality_class": self.quality_class,
                "speed_class": self.speed_class, "reference_images": self.reference_images,
                "max_reference_images": self.max_reference_images, "qualities": list(self.qualities),
                "sizes": list(self.sizes), "default": self.default, "known": self.known,
                "aspect_sizes": dict(self.aspect_sizes)}


@cache
def catalog_data() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@cache
def catalog() -> tuple[ImageModel, ...]:
    return tuple(ImageModel(id=m["id"], label=m["label"], provider_type=m["provider_type"],
                            description=m.get("description", ""), quality_class=int(m.get("quality_class", 3)),
                            speed_class=int(m.get("speed_class", 2)), reference_images=bool(m.get("reference_images")),
                            max_reference_images=int(m.get("max_reference_images", 0)),
                            qualities=tuple(m.get("qualities") or DEFAULT_QUALITIES),
                            sizes=tuple(m.get("sizes") or DEFAULT_SIZES), input_fidelity=bool(m.get("input_fidelity")),
                            default=bool(m.get("default")),
                            aspect_sizes=tuple((m.get("aspect_sizes") or {}).items())) for m in catalog_data()["models"])


def resolve(provider_type: str, model_id: str) -> ImageModel | None:
    """The chosen model, or the catalog default for the provider type. A name the user typed (Azure deployment,
    own server) is accepted with conservative capabilities: no reference images, standard sizes and qualities."""
    if provider_type not in IMAGE_PROVIDER_TYPES:
        return None
    options = [m for m in catalog() if m.provider_type == provider_type]
    if model_id:
        known = next((m for m in options if m.id == model_id), None)
        if known is not None:
            return known
        same_id = next((m for m in catalog() if m.id == model_id), None)  # e.g. an Azure deployment named like the model
        if same_id is not None:
            return ImageModel(**{**same_id.__dict__, "provider_type": provider_type})
        return ImageModel(id=model_id, label=model_id, provider_type=provider_type, known=False)
    return next((m for m in options if m.default), None)
