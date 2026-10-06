"""Colour contrast (1.4.3).

Judged automatically ONLY when both foreground and background colour are
specified in the content itself. When either comes from Canvas or a theme,
the result is a manual check (with the ratio against Canvas' default colours
as evidence). Thresholds are not rounded: 4.499:1 fails.
"""

from __future__ import annotations

import colorsys
import re

from bs4 import Tag

from emneklar.core.canvas.html import element_path, is_hidden, norm_text
from emneklar.features.accessibility.checks.base import ContentDoc, Issue

CANVAS_TEXT = (0x2D, 0x3B, 0x45)  # Canvas default content text colour (#2D3B45)
WHITE = (0xFF, 0xFF, 0xFF)
NAMED = {
    "black": "000000", "silver": "c0c0c0", "gray": "808080", "grey": "808080", "white": "ffffff", "maroon": "800000",
    "red": "ff0000", "purple": "800080", "fuchsia": "ff00ff", "magenta": "ff00ff", "green": "008000",
    "lime": "00ff00", "olive": "808000", "yellow": "ffff00", "navy": "000080", "blue": "0000ff", "teal": "008080",
    "aqua": "00ffff", "cyan": "00ffff", "orange": "ffa500", "darkred": "8b0000", "darkgreen": "006400",
    "darkblue": "00008b", "lightgray": "d3d3d3", "lightgrey": "d3d3d3", "darkgray": "a9a9a9", "darkgrey": "a9a9a9",
    "lightblue": "add8e6", "lightgreen": "90ee90", "lightyellow": "ffffe0", "pink": "ffc0cb", "gold": "ffd700",
    "brown": "a52a2a", "crimson": "dc143c", "coral": "ff7f50", "tomato": "ff6347", "salmon": "fa8072",
    "orangered": "ff4500", "khaki": "f0e68c", "beige": "f5f5dc", "ivory": "fffff0", "lavender": "e6e6fa",
    "violet": "ee82ee", "indigo": "4b0082", "turquoise": "40e0d0", "skyblue": "87ceeb", "steelblue": "4682b4",
    "royalblue": "4169e1", "dodgerblue": "1e90ff", "slategray": "708090", "dimgray": "696969", "gainsboro": "dcdcdc",
    "whitesmoke": "f5f5f5", "lightcoral": "f08080", "darkorange": "ff8c00", "forestgreen": "228b22",
    "seagreen": "2e8b57", "limegreen": "32cd32", "yellowgreen": "9acd32", "chocolate": "d2691e", "tan": "d2b48c",
    "firebrick": "b22222", "darkviolet": "9400d3", "mediumpurple": "9370db", "plum": "dda0dd", "orchid": "da70d6",
    "hotpink": "ff69b4", "deeppink": "ff1493", "midnightblue": "191970", "cornflowerblue": "6495ed",
    "cadetblue": "5f9ea0", "darkcyan": "008b8b", "lightcyan": "e0ffff", "mintcream": "f5fffa", "honeydew": "f0fff0",
    "aliceblue": "f0f8ff", "ghostwhite": "f8f8ff", "snow": "fffafa", "seashell": "fff5ee", "linen": "faf0e6",
    "oldlace": "fdf5e6", "papayawhip": "ffefd5", "moccasin": "ffe4b5", "wheat": "f5deb3", "goldenrod": "daa520",
    "darkgoldenrod": "b8860b", "olivedrab": "6b8e23", "darkolivegreen": "556b2f", "sienna": "a0522d",
    "saddlebrown": "8b4513", "rosybrown": "bc8f8f", "lightpink": "ffb6c1", "palevioletred": "db7093",
    "mediumvioletred": "c71585", "darkmagenta": "8b008b", "rebeccapurple": "663399", "lightslategray": "778899",
    "darkslategray": "2f4f4f", "lightsteelblue": "b0c4de", "powderblue": "b0e0e6", "paleturquoise": "afeeee",
    "aquamarine": "7fffd4", "mediumseagreen": "3cb371", "springgreen": "00ff7f", "lawngreen": "7cfc00",
    "chartreuse": "7fff00", "greenyellow": "adff2f", "palegreen": "98fb98", "darkseagreen": "8fbc8f",
    "lemonchiffon": "fffacd", "lightgoldenrodyellow": "fafad2", "peachpuff": "ffdab9", "bisque": "ffe4c4",
    "blanchedalmond": "ffebcd", "navajowhite": "ffdead", "burlywood": "deb887", "sandybrown": "f4a460",
    "peru": "cd853f", "indianred": "cd5c5c", "darksalmon": "e9967a", "lightsalmon": "ffa07a", "mistyrose": "ffe4e1",
    "lavenderblush": "fff0f5", "thistle": "d8bfd8", "mediumorchid": "ba55d3", "darkorchid": "9932cc",
    "blueviolet": "8a2be2", "slateblue": "6a5acd", "darkslateblue": "483d8b", "mediumslateblue": "7b68ee",
    "mediumblue": "0000cd", "deepskyblue": "00bfff", "lightskyblue": "87cefa", "mediumturquoise": "48d1cc",
    "darkturquoise": "00ced1", "lightseagreen": "20b2aa", "mediumaquamarine": "66cdaa", "mediumspringgreen": "00fa9a",
}

RGB = tuple[int, int, int]


def parse_color(value: str) -> tuple[RGB | None, bool]:
    """Return (rgb, reliable). ``reliable`` is False for transparency and unparseable colours."""
    v = value.strip().lower().replace(" !important", "").strip()
    if not v or v in ("inherit", "initial", "unset", "currentcolor", "revert"):
        return None, False
    if v == "transparent":
        return None, False
    if v in NAMED:
        v = "#" + NAMED[v]
    if v.startswith("#"):
        h = v[1:]
        if len(h) in (3, 4):
            if len(h) == 4 and h[3] != "f":
                return None, False
            h = "".join(c * 2 for c in h[:3])
        elif len(h) == 8:
            if h[6:] != "ff":
                return None, False
            h = h[:6]
        if len(h) != 6 or not re.fullmatch(r"[0-9a-f]{6}", h):
            return None, False
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)), True
    match = re.fullmatch(r"rgba?\(\s*([\d.]+%?)[\s,]+([\d.]+%?)[\s,]+([\d.]+%?)(?:[\s,/]+([\d.]+%?))?\s*\)", v)
    if match:
        alpha = match.group(4)
        if alpha is not None and float(alpha.rstrip("%")) < (100 if alpha.endswith("%") else 1):
            return None, False

        def channel(x: str) -> int:
            return round(float(x[:-1]) * 2.55) if x.endswith("%") else round(float(x))

        return (channel(match.group(1)), channel(match.group(2)), channel(match.group(3))), True
    match = re.fullmatch(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%(?:[\s,/]+([\d.]+%?))?\s*\)", v)
    if match:
        alpha = match.group(4)
        if alpha is not None and float(alpha.rstrip("%")) < (100 if alpha.endswith("%") else 1):
            return None, False
        r, g, b = colorsys.hls_to_rgb(float(match.group(1)) / 360, float(match.group(3)) / 100,
                                      float(match.group(2)) / 100)
        return (round(r * 255), round(g * 255), round(b * 255)), True
    return None, False


def relative_luminance(rgb: RGB) -> float:
    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _style(el: Tag) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(el.get("style") or "").split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            out[key.strip().lower()] = value.strip()
    return out


def _font_px(el: Tag) -> tuple[float | None, bool]:
    node: Tag | None = el
    bold = False
    size: float | None = None
    while isinstance(node, Tag):
        if node.name in ("strong", "b") or node.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            bold = True
        style = _style(node)
        if size is None and "font-size" in style:
            match = re.match(r"([\d.]+)\s*(px|pt|em|rem|%)", style["font-size"])
            if match:
                value, unit = float(match.group(1)), match.group(2)
                size = value * {"px": 1.0, "pt": 1.333, "em": 16.0, "rem": 16.0, "%": 0.16}[unit]
        if size is None and node.name in ("h1", "h2", "h3"):
            size = {"h1": 32.0, "h2": 28.0, "h3": 24.0}[node.name]
        node = node.parent if isinstance(node.parent, Tag) else None
    return size, bold


def _resolve(el: Tag, prop: str) -> tuple[str | None, bool]:
    """Nearest specified value of ``prop`` (color/background) up the tree; False if blocked by an image."""
    node: Tag | None = el
    while isinstance(node, Tag):
        style = _style(node)
        if prop == "background":
            if "background-image" in style or "url(" in style.get("background", ""):
                return None, False
            for key in ("background-color", "background"):
                if key in style:
                    color = style[key].split()[0] if key == "background" else style[key]
                    return color, True
        elif "color" in style:
            return style["color"], True
        node = node.parent if isinstance(node.parent, Tag) else None
    return None, True


def check_contrast(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[tuple[str, str, bool]] = set()
    for el in doc.soup.find_all(style=True):
        style = _style(el)
        if not ({"color", "background-color", "background"} & style.keys()) or is_hidden(el):
            continue
        targets = [el] + [d for d in el.find_all(True) if not _style(d).keys() & {"color", "background-color"}]
        has_text = any(norm_text("".join(t.find_all(string=True, recursive=False))) for t in targets)
        if not has_text:
            continue
        fg_raw, _ = _resolve(el, "color")
        bg_raw, bg_reliable = _resolve(el, "background")
        fg, fg_ok = parse_color(fg_raw) if fg_raw else (None, True)
        bg, bg_ok = parse_color(bg_raw) if bg_raw else (None, True)
        size, bold = _font_px(el)
        large = size is not None and (size >= 24 or (bold and size >= 18.66))
        threshold = 3.0 if large else 4.5
        if fg is not None and bg is not None and fg_ok and bg_ok and bg_reliable:
            ratio = contrast_ratio(fg, bg)
            key = (fg_raw or "", bg_raw or "", large)
            if ratio < threshold and key not in seen:
                seen.add(key)
                issues.append(Issue(
                    "UU-CONTRAST",
                    f"Kontrasten er {ratio:.2f}:1 (krav {threshold:g}:1 for {'stor' if large else 'vanlig'} tekst).",
                    element=el, key=f"contrast:{element_path(el)}",
                    evidence={"foreground": fg_raw, "background": bg_raw, "ratio": round(ratio, 2),
                              "required": threshold, "large_text": large, "font_px": size}))
            continue
        if (fg_raw and not fg_ok) or (bg_raw and not bg_ok) or not bg_reliable:
            if fg_raw or bg_raw:
                issues.append(Issue(
                    "UU-CONTRAST-UNKNOWN", "Farger med gjennomsiktighet eller bakgrunnsbilde kan ikke måles automatisk.",
                    element=el, key=f"contrast-unknown:{element_path(el)}",
                    evidence={"foreground": fg_raw, "background": bg_raw}))
            continue
        assumed_fg = fg or CANVAS_TEXT
        assumed_bg = bg or WHITE
        ratio = contrast_ratio(assumed_fg, assumed_bg)
        key = (fg_raw or "default", bg_raw or "default", large)
        if ratio < threshold and key not in seen:
            seen.add(key)
            issues.append(Issue(
                "UU-CONTRAST-UNKNOWN",
                f"Mot Canvas' standard{'bakgrunn (hvit)' if bg is None else 'tekstfarge'} ville kontrasten vært "
                f"{ratio:.2f}:1 (krav {threshold:g}:1).",
                element=el, key=f"contrast-unknown:{element_path(el)}",
                evidence={"foreground": fg_raw, "background": bg_raw, "ratio_against_default": round(ratio, 2),
                          "required": threshold, "assumed": "background" if bg is None else "foreground"}))
    return issues
