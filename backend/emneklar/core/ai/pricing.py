"""Indicative prices (``pricing.json``) for cost *estimates*. Never presented as guaranteed prices."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"


@cache
def pricing() -> dict[str, Any]:
    return json.loads(PRICING_PATH.read_text(encoding="utf-8"))


def text_price(provider_type: str, model_id: str) -> dict[str, Any] | None:
    return next((p for p in pricing()["text"] if p["provider_type"] == provider_type and p["model_id"] == model_id),
                None)


def image_price(provider_type: str, model_id: str) -> dict[str, Any] | None:
    lookup = "openai" if provider_type in ("azure_openai",) else provider_type
    return next((p for p in pricing()["image"] if p["provider_type"] == lookup and p["model_id"] == model_id), None)


def text_cost(provider_type: str, model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    price = text_price(provider_type, model_id)
    if price is None:
        return None
    return input_tokens / 1e6 * float(price["input"]) + output_tokens / 1e6 * float(price["output"])


def image_output_tokens(quality: str, size: str) -> int | None:
    table = pricing().get("image_output_tokens") or {}
    row = table.get(quality)
    if not isinstance(row, dict):
        return None
    value = row.get(size)
    if value is not None:
        return int(value)
    # Sizes without a table entry (e.g. 1536x864 for 16:9): scale the 1536x1024 figure by the number of pixels.
    try:
        width, height = (int(v) for v in size.lower().split("x"))
    except ValueError:
        return None
    base = row.get("1536x1024")
    return int(int(base) * width * height / (1536 * 1024)) if base is not None else None


def image_cost(provider_type: str, model_id: str, *, quality: str, size: str, prompt_tokens: int,
               reference_images: int = 0, output_tokens: int | None = None,
               input_image_tokens: int | None = None) -> float | None:
    """Estimated cost of one image. With real usage (``output_tokens`` …) it is the cost of what was reported."""
    price = image_price(provider_type, model_id)
    if price is None:
        return None
    out = output_tokens if output_tokens is not None else image_output_tokens(quality, size)
    if out is None:
        return None
    image_in = input_image_tokens if input_image_tokens is not None else (
        reference_images * int(pricing().get("reference_image_input_tokens") or 0))
    return (prompt_tokens / 1e6 * float(price["text_input"]) + image_in / 1e6 * float(price["image_input"])
            + out / 1e6 * float(price["image_output"]))


def summary() -> dict[str, Any]:
    data = pricing()
    return {"version": data["version"], "currency": data["currency"], "note": data["note"]}
