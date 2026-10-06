"""Collects the routers of the core and of every feature module."""

from __future__ import annotations

import importlib

from fastapi import APIRouter

ROUTERS = [
    "emneklar.api.routes_system",
    "emneklar.api.routes_canvas",
    "emneklar.features.analysis.api",
    "emneklar.features.findings.api",
    "emneklar.core.changes.api",
    "emneklar.features.accessibility.fixes",
    "emneklar.features.overview.api",
]


def api_routers() -> list[APIRouter]:
    return [importlib.import_module(name).router for name in ROUTERS]
