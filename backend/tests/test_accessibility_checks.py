"""Accessibility checks: what is flagged, what is NOT flagged, and how it is classified."""

from __future__ import annotations

from emneklar.features.accessibility.checks import ContentDoc, run_html_checks
from emneklar.features.accessibility.checks.contrast import contrast_ratio, parse_color
from emneklar.features.accessibility.checks.embeds import EXTERNAL_CAPTIONS_MESSAGE, check_media
from emneklar.features.accessibility.checks.language import detect_language
from emneklar.features.accessibility.profiles import get_profile, legal_status, load_profiles
from emneklar.features.accessibility.rules import load_ruleset


def ids(html: str, **kw: object) -> list[str]:
    doc = ContentDoc(object_type="page", object_id="1", title="T", html=html, canvas_host="canvas.test")
    return [i.rule_id for i in run_html_checks(doc, kw.get("captions"))]  # type: ignore[arg-type]


def issues(html: str):  # type: ignore[no-untyped-def]
    return run_html_checks(ContentDoc(object_type="page", object_id="1", title="T", html=html,
                                      canvas_host="canvas.test"))


# -------------------------------------------------------------------------------- registry


def test_every_rule_used_in_checks_exists_and_has_sources() -> None:
    rules = load_ruleset().rules
    assert len(rules) >= 45
    for rule in rules.values():
        assert rule.sources, rule.id
        assert rule.explanation and rule.remediation and rule.affected_users


def test_profiles_counts_and_legal_status() -> None:
    profiles = load_profiles()
    assert profiles["no-offentlig-2023"].required_count() == 48
    assert profiles["no-offentlig-2023"].required_count(document=True) == 44
    assert profiles["no-privat-2013"].required_count() == 35
    assert profiles["wcag22-aa"].required_count() == 55
    public = get_profile("no-offentlig-2023")
    assert legal_status(public, ["1.1.1"])["status"] == "required"
    assert legal_status(public, ["1.2.5"])["status"] == "conditional"
    assert legal_status(public, ["2.4.9"])["status"] == "not_required"
    assert legal_status(public, ["2.4.5"], document=True)["status"] == "not_required"
    assert legal_status(public, [])["status"] == "none"
    assert legal_status(get_profile("wcag22-aa"), ["1.4.3"])["status"] == "best_practice"
    assert legal_status(get_profile("no-privat-2013"), ["1.4.11"])["status"] == "not_required"


# ---------------------------------------------------------------------------------- images


def test_missing_alt_is_violation_but_empty_alt_is_decorative() -> None:
    assert "UU-IMG-MISSING-ALT" in ids('<img src="/a/foto.jpg">')
    assert ids('<p><img src="/a/pynt.png" alt=""></p>') == []
    assert ids('<img src="/a/pynt.png" role="presentation">') == []


def test_caption_is_not_alt_text() -> None:
    found = issues('<figure><img src="/x/graf.png"><figcaption>Figur 1: Vekst</figcaption></figure>')
    missing = next(i for i in found if i.rule_id == "UU-IMG-MISSING-ALT")
    assert "erstatter ikke" in missing.message


def test_suspicious_empty_alt_is_review_not_violation() -> None:
    found = issues('<figure><img src="/x/diagram.png" alt=""><figcaption>Diagram</figcaption></figure>')
    review = [i for i in found if i.rule_id == "UU-IMG-EMPTY-ALT-REVIEW"]
    assert review and review[0].confidence == "medium"


def test_filename_generic_and_linked_empty_alt() -> None:
    assert "UU-IMG-FILENAME-ALT" in ids('<img src="/f/IMG_2034.JPG" alt="IMG_2034.JPG">')
    assert "UU-IMG-GENERIC-ALT" in ids('<img src="/f/x.png" alt="Bilde">')
    assert "UU-IMG-EMPTY-ALT-LINK" in ids('<a href="https://ex.org"><img src="/f/x.png" alt=""></a>')
    assert "UU-LINK-EMPTY" not in ids('<a href="https://ex.org"><img src="/f/x.png" alt=""></a>')


def test_duplicate_alt_across_different_images() -> None:
    html = '<img src="/a.png" alt="Hund som løper"><img src="/b.png" alt="Hund som løper">'
    assert "UU-IMG-DUPLICATE-ALT" in ids(html)
    assert "UU-IMG-DUPLICATE-ALT" not in ids('<img src="/a.png" alt="Hund"><img src="/a.png" alt="Hund">')


# -------------------------------------------------------------------------------- headings


def test_canvas_h1_context_and_skips() -> None:
    found = ids("<h1>Tittel</h1><p>x</p>")
    assert "UU-HEAD-H1" in found
    assert "UU-HEAD-SKIP" in ids("<h2>A</h2><p>x</p><h4>B</h4><p>y</p>")
    assert "UU-HEAD-SKIP" in ids("<h3>Starter for dypt</h3><p>x</p>")
    assert ids("<h2>A</h2><p>x</p><h3>B</h3><p>y</p><h2>C</h2>") == []


def test_empty_heading_and_fake_heading() -> None:
    assert "UU-HEAD-EMPTY" in ids("<h2>&nbsp;</h2><p>tekst</p>")
    assert "UU-HEAD-FAKE" in ids("<p><strong>Praktisk informasjon</strong></p><p>Undervisning på tirsdager.</p>")
    # A bold sentence inside running text is not a heading.
    assert "UU-HEAD-FAKE" not in ids("<p><strong>Husk å levere innen fredag.</strong></p><p>Mer tekst.</p>")


# ----------------------------------------------------------------------------------- links


def test_vague_link_depends_on_context() -> None:
    no_context = issues('<p><a href="https://ex.org/plan">Klikk her</a></p>')
    assert [i.rule_id for i in no_context] == ["UU-LINK-VAGUE"]
    with_context = issues('<p>Pensumlisten for uke tre med alle artikler finner du <a href="https://ex.org">her</a>.</p>')
    assert [i.rule_id for i in with_context] == ["UU-LINK-VAGUE-CONTEXT"]


def test_empty_link_rawurl_and_same_text() -> None:
    assert "UU-LINK-EMPTY" in ids('<p><a href="https://ex.org/missing"></a></p>')
    assert "UU-LINK-RAWURL" in ids('<p><a href="https://www.example.org/en/very/long/path/to/a/resource">'
                                    'https://www.example.org/en/very/long/path/to/a/resource</a></p>')
    html = '<p><a href="https://a.org/1">Oppgavetekst</a></p><p><a href="https://b.org/2">Oppgavetekst</a></p>'
    assert "UU-LINK-SAME-TEXT" in ids(html)
    assert ids('<p><a href="https://ex.org/plan">Les emneplanen for høsten 2026</a></p>') == []


# ---------------------------------------------------------------------------------- tables


def test_tables() -> None:
    assert "UU-TABLE-NO-HEADERS" in ids("<table><tr><td>Farge</td><td>Kode</td></tr><tr><td>Rød</td><td>#f00</td></tr></table>")
    ok = "<table><caption>Farger</caption><tr><th scope='col'>Farge</th><th scope='col'>Kode</th></tr>" \
         "<tr><td>Rød</td><td>#f00</td></tr><tr><td>Blå</td><td>#00f</td></tr></table>"
    assert ids(ok) == []
    assert "UU-TABLE-LAYOUT" in ids("<table><tr><td><p>Tekst</p></td><td><img src='/a.png' alt='A'></td></tr></table>")
    assert "UU-TABLE-COMPLEX" in ids("<table><tr><th colspan='2'>Hode</th></tr><tr><td>1</td><td>2</td></tr></table>")
    assert "UU-TABLE-EMPTY" in ids("<table><tr><td></td></tr></table>")


# ----------------------------------------------------------------------------------- lists


def test_fake_lists_and_nesting() -> None:
    assert "UU-LIST-FAKE" in ids("<p>- JPEG for foto</p><p>- PNG for grafikk</p><p>- SVG for vektor</p>")
    assert "UU-LIST-FAKE" in ids("<p>1. Først<br>2. Deretter<br>3. Til slutt</p>")
    assert "UU-LIST-FAKE" not in ids("<p>- Bare én linje med strek</p><p>Vanlig avsnitt</p>")
    assert "UU-LIST-NESTING" in ids("<ul><li>A</li><ul><li>B</li></ul></ul>")
    assert "UU-LIST-EMPTY-ITEM" in ids("<ul><li>A</li><li> </li></ul>")


# --------------------------------------------------------------------------- language etc.


def test_language_detection_and_parts() -> None:
    english = "This paragraph is written entirely in English so that the detector can find it and suggest a language."
    assert detect_language(english) == "en"
    assert detect_language("Dette avsnittet er skrevet på norsk og handler om hvordan du kan levere oppgaven din.") == "nb"
    html = f"<p>Dette emnet handler om digital kompetanse og hvordan vi kan bruke det i skolen i dag.</p><p>{english}</p>"
    assert "UU-LANG-PARTS" in ids(html)
    assert "UU-LANG-PARTS" not in ids(html.replace("<p>This", '<p lang="en">This'))
    assert "UU-LANG-INVALID" in ids('<p lang="norsk">x</p>')


def test_sensory_caps_and_underline() -> None:
    assert "UU-SENSORY" in ids("<p>Klikk på den grønne knappen til høyre for å fortsette.</p>")
    assert "UU-CAPS" in ids("<p>DENNE TEKSTEN ER SKREVET MED STORE BOKSTAVER OG ER VANSKELIG Å LESE</p>")
    assert "UU-UNDERLINE" in ids("<p><u>Viktig</u> informasjon</p>")


# -------------------------------------------------------------------------------- contrast


def test_contrast_math_and_parsing() -> None:
    assert round(contrast_ratio((0, 0, 0), (255, 255, 255)), 2) == 21.0
    assert parse_color("#777")[0] == (0x77, 0x77, 0x77)
    assert parse_color("rgba(0,0,0,0.5)") == (None, False)
    assert parse_color("navy")[0] == (0, 0, 128)


def test_contrast_deterministic_only_when_both_colours_known() -> None:
    found = issues('<p style="color:#aaaaaa;background-color:#ffffff">Lys grå tekst</p>')
    assert [i.rule_id for i in found] == ["UU-CONTRAST"]
    assert found[0].evidence["ratio"] < 4.5
    unknown = issues('<p style="color:#aaaaaa">Lys grå tekst uten bakgrunn</p>')
    assert [i.rule_id for i in unknown] == ["UU-CONTRAST-UNKNOWN"]
    assert ids('<p style="color:#000000">Svart tekst</p>') == []
    # 4.499:1 must fail – no rounding. #767676 on white is 4.54:1 (passes); #777777 is 4.48:1 (fails).
    assert ids('<p style="color:#767676;background:#ffffff">Grå</p>') == []
    assert "UU-CONTRAST" in ids('<p style="color:#777777;background:#ffffff">Grå</p>')


def test_large_text_threshold() -> None:
    # #959595 on white ≈ 3.0:1 – fails for normal text, passes for 24px text.
    assert "UU-CONTRAST" in ids('<p style="color:#949494;background:#fff">Tekst</p>')
    assert ids('<p style="color:#949494;background:#fff;font-size:24px">Stor tekst</p>') == []


# ---------------------------------------------------------------------------- iframes/media


def test_iframes() -> None:
    assert "UU-IFRAME-NO-TITLE" in ids('<iframe src="https://www.youtube.com/embed/abc123xyz"></iframe>')
    assert "UU-IFRAME-GENERIC-TITLE" in ids('<iframe title="video" src="https://player.vimeo.com/video/1"></iframe>')
    found = ids('<iframe title="Skjema for påmelding" src="https://forms.example.org/x"></iframe>')
    assert found == ["UU-IFRAME-EXTERNAL"], "a title does not prove the external tool is accessible"
    assert "UU-IFRAME-NO-TITLE" not in ids('<iframe aria-hidden="true" tabindex="-1" src="https://x.org"></iframe>')


def test_media_captions_and_autoplay() -> None:
    youtube = issues('<iframe title="Video: Intro" src="https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1"></iframe>')
    rules = [i.rule_id for i in youtube]
    assert "UU-MEDIA-AUTOPLAY" in rules
    external = next(i for i in youtube if i.rule_id == "UU-MEDIA-EXTERNAL-CAPTIONS")
    assert external.message == EXTERNAL_CAPTIONS_MESSAGE
    canvas = '<iframe title="Forelesning" data-media-id="m-1" src="/media_attachments_iframe/77?type=video"></iframe>'
    doc = ContentDoc(object_type="page", object_id="1", title="T", html=canvas, canvas_host="canvas.test")
    assert [i.rule_id for i in check_media(doc, {"77": False})] == ["UU-MEDIA-CANVAS-CAPTIONS"]
    assert check_media(doc, {"77": True}) == []
    assert "UU-MEDIA-HTML5-TRACK" in ids('<video src="/x.mp4" controls></video>')
    assert "UU-MEDIA-HTML5-TRACK" not in ids('<video src="/x.mp4"><track kind="captions" src="/x.vtt"></video>')


def test_markup_checks() -> None:
    assert "UU-MOVING" in ids("<marquee>Nyhet!</marquee>")
    assert "UU-ARIA-HIDDEN-FOCUS" in ids('<div aria-hidden="true"><a href="https://x.org">Lenke</a></div>')
    assert "UU-DUPLICATE-ID" in ids('<p id="a">1</p><p id="a">2</p>')


def test_clean_page_has_no_findings() -> None:
    html = """<h2>Om emnet</h2><p>Emnet gir en innføring i digital kompetanse.</p>
    <p><img src="/f/foto.jpg" alt="Studenter som samarbeider rundt en datamaskin"></p>
    <ul><li>Uke 1: Introduksjon</li><li>Uke 2: Bilder</li></ul>
    <p>Les <a href="https://www.example.org/plan">emneplanen for høsten 2026</a> før første samling.</p>"""
    assert ids(html) == []
