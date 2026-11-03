"""Shared types for accessibility checks.

A check receives one piece of Canvas content (:class:`ContentDoc`) and returns
:class:`Issue` objects. Checks only *detect*; classification defaults come from
the rule registry and can be adjusted per instance (e.g. a vague link with
context is an improvement, without context a likely violation).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from bs4 import BeautifulSoup, Tag

from emneklar.core.canvas.html import element_path, parse_html, snippet


@dataclass
class ContentDoc:
    object_type: str  # page|front_page|assignment|discussion|quiz|quiz_question|syllabus
    object_id: str
    title: str
    html: str
    url: str | None = None
    canvas_host: str | None = None
    module: str | None = None
    course_id: str | None = None
    language: str | None = None  # course locale (Canvas sets the page language from it)

    @cached_property
    def soup(self) -> BeautifulSoup:
        return parse_html(self.html)


@dataclass
class Issue:
    rule_id: str
    message: str
    element: Tag | None = None
    snippet: str | None = None
    context: str | None = None
    classification: str | None = None
    confidence: str = "high"
    severity: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    fix: dict[str, Any] | None = None
    key: str | None = None  # stable identity within the document (defaults to the element path)

    def location(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.element is not None:
            data["selector"] = element_path(self.element)
            data["snippet"] = self.snippet or snippet(self.element)
            data["sig"] = element_signature(self.element)
        elif self.snippet:
            data["snippet"] = self.snippet
        if self.context:
            data["context"] = self.context[:400]
        return data

    def identity(self) -> str:
        if self.key:
            return self.key
        if self.element is not None:
            return element_path(self.element)
        return self.snippet or self.message


Check = Callable[[ContentDoc], list[Issue]]


def element_signature(el: Tag) -> str:
    """Identifies an element by its markup, so a fix can find it again even if positions shifted."""
    import hashlib

    return hashlib.sha1(str(el).encode("utf-8")).hexdigest()[:16]  # noqa: S324 - identity, not security


def fix(fix_type: str, label: str, **params: Any) -> dict[str, Any]:
    return {"type": fix_type, "label": label, "params": params}
