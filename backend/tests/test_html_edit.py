"""Targeted HTML edits: only the element changes, every other byte stays as the teacher (or Canvas) wrote it."""

from __future__ import annotations

import pytest

from emneklar.core.canvas.html import parse_html
from emneklar.core.canvas.html_edit import EditError, EditPlan, edit_start_tag

HTML = ("<p class=\"intro\">Hei&nbsp;der &amp; velkommen<br/>"
        "<a href='https://a.example/x?b=1&amp;c=2' target=_blank data-x=\"1\">Lenke</a></p>"
        "<p><img src=\"/courses/1/files/2/preview\" width=300></p><h4>Tittel</h4>"
        "<ul><li>En<li>To</ul>")


def plan_for(html: str = HTML) -> tuple[EditPlan, object]:
    return EditPlan(html), parse_html(html)


def test_set_attribute_keeps_the_rest_byte_for_byte() -> None:
    plan, soup = plan_for()
    img = soup.find("img")
    plan.set_attrs(soup, img, {"alt": 'Graf "A" & B'})  # type: ignore[arg-type]
    result = plan.apply()
    assert result == HTML.replace('width=300>', 'width=300 alt="Graf &quot;A&quot; &amp; B">')
    assert plan.changes()[0]["before"] == '<img src="/courses/1/files/2/preview" width=300>'


def test_link_href_text_unwrap_and_remove() -> None:
    plan, soup = plan_for()
    a = soup.find("a")
    plan.set_attrs_and_inner(soup, a, {"href": "https://ny.example/"}, "Ny tekst")  # type: ignore[arg-type]
    assert plan.apply() == HTML.replace("href='https://a.example/x?b=1&amp;c=2'", 'href="https://ny.example/"').replace(
        ">Lenke<", ">Ny tekst<")
    plan, soup = plan_for()
    plan.unwrap(soup, soup.find("a"))  # type: ignore[arg-type]
    assert "Lenke</p>" in plan.apply() and "<a " not in plan.apply() and "Hei&nbsp;der &amp;" in plan.apply()
    plan, soup = plan_for()
    plan.remove(soup, soup.find("a"))  # type: ignore[arg-type]
    assert plan.apply() == HTML.replace(
        "<a href='https://a.example/x?b=1&amp;c=2' target=_blank data-x=\"1\">Lenke</a>", "")


def test_rename_heading_and_several_edits_at_once() -> None:
    plan, soup = plan_for()
    plan.rename(soup, soup.find("h4"), "h3")  # type: ignore[arg-type]
    plan.set_attrs(soup, soup.find("p"), {"lang": "nb"})  # type: ignore[arg-type]
    result = plan.apply()
    assert result == HTML.replace("<h4>Tittel</h4>", "<h3>Tittel</h3>").replace('<p class="intro">',
                                                                                '<p class="intro" lang="nb">')


def test_elements_without_an_explicit_end_tag_are_not_spliced() -> None:
    plan, soup = plan_for()
    with pytest.raises(EditError):
        plan.remove(soup, soup.find("li"))  # type: ignore[arg-type]  # «<li>En<li>» has no end tag


def test_mismatched_element_is_refused() -> None:
    plan, soup = plan_for()
    other = parse_html("<a href='https://andre.example/'>x</a>").find("a")
    with pytest.raises(EditError):
        plan.set_attrs(soup, other, {"href": "y"})  # type: ignore[arg-type]


def test_overlapping_edits_are_refused() -> None:
    plan, soup = plan_for()
    a = soup.find("a")
    plan.set_attrs(soup, a, {"href": "https://x.example/"})  # type: ignore[arg-type]
    with pytest.raises(EditError):
        plan.remove(soup, a)  # type: ignore[arg-type]


def test_edit_start_tag_handles_quotes_and_valueless_attributes() -> None:
    assert edit_start_tag('<iframe allowfullscreen src="x">', {"title": "Video"}) == \
        '<iframe allowfullscreen src="x" title="Video">'
    assert edit_start_tag("<img alt='gammel' src=x />", {"alt": None}) == "<img src=x />"
    assert edit_start_tag('<video autoplay controls>', {"autoplay": None}) == "<video controls>"
