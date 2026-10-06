"""Collects the routers of the core and of every feature module."""

from __future__ import annotations

from fastapi import APIRouter


def api_routers() -> list[APIRouter]:
    from emneklar.api import routes_system

    routers: list[APIRouter] = [routes_system.router]
    return routers
