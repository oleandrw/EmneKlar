"""Accessibility checks over Canvas HTML. See ../rules/ruleset.json for rule metadata."""

from __future__ import annotations

from emneklar.features.accessibility.checks.base import ContentDoc, Issue
from emneklar.features.accessibility.checks.contrast import check_contrast
from emneklar.features.accessibility.checks.embeds import check_iframes, check_markup, check_media
from emneklar.features.accessibility.checks.images import check_images
from emneklar.features.accessibility.checks.language import check_language
from emneklar.features.accessibility.checks.structure import check_headings, check_lists, check_links, check_tables

HTML_CHECKS = (check_images, check_headings, check_links, check_tables, check_lists, check_language,
               check_contrast, check_iframes, check_markup)


def run_html_checks(doc: ContentDoc, media_captions: dict[str, bool | None] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    for check in HTML_CHECKS:
        issues.extend(check(doc))
    issues.extend(check_media(doc, media_captions))
    return issues


__all__ = ["ContentDoc", "Issue", "run_html_checks"]
