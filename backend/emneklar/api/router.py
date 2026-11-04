"""Collects the routers of the core and of every feature module."""

from __future__ import annotations

import importlib

from fastapi import APIRouter

ROUTERS = [
    "emneklar.api.routes_system",
    "emneklar.api.routes_canvas",
    "emneklar.api.routes_settings",
    "emneklar.features.analysis.api",
    "emneklar.features.findings.api",
    "emneklar.core.changes.api",
    "emneklar.features.accessibility.fixes",
    "emneklar.features.overview.api",
    "emneklar.features.content_quality.api",
    "emneklar.features.content_quality.video_api",
    "emneklar.features.course_structure.api",
    "emneklar.core.ai.api",
    "emneklar.features.accessibility.ai_alt",
    "emneklar.features.quiz_assistant.api",
    "emneklar.features.module_requirements.api",
    "emneklar.features.blueprint.api",
    "emneklar.features.canvas_settings.api",
    "emneklar.features.homepage_builder.api",
    "emneklar.features.reporting.api",
    "emneklar.features.course_rag.api",
    "emneklar.features.illustrations.api",
]


def api_routers() -> list[APIRouter]:
    return [importlib.import_module(name).router for name in ROUTERS]
