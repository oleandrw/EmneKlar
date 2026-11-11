r"""Draw packaging/windows/EmneKlar.ico: the EmneKlar logo – an open book with a check mark, the same drawing as
``BrandMark`` in frontend/src/core/layout/AppShell.tsx and frontend/public/favicon.svg – in the sizes Windows uses for
shortcuts, the taskbar and the installer.

    backend\.venv\Scripts\python packaging\windows\make_icon.py

Run it again only when the logo changes; the .ico file is committed. ``test_installer_build`` checks that the three
drawings agree.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
GREEN, BLUE, YELLOW, INK = "#34d399", "#60a5fa", "#fbbf24", "#0f2342"
#: The square the icon shows, in the units of the logo (its 36 x 36 box): left, top and size. The logo fills it
#: edge to edge, like favicon.svg (``viewBox="2 1.75 32 32"``).
LEFT, TOP, SIDE = 2.0, 1.75, 32.0

Point = tuple[float, float]


def cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = 32) -> list[Point]:
    """A cubic Bézier curve (the ``c`` of an SVG path) as a line of ``steps`` pieces."""
    points = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        points.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return points


def mirrored(points: list[Point]) -> list[Point]:
    return [(36 - x, y) for x, y in points]


# The paths of BrandMark, written out: M3.5 10.2 c4.9-2 9.8-1.7 14.5 1.1 v18.4 c-4.7-2.8 -9.6-3.1 -14.5-1.1 z
LEFT_PAGE = cubic((3.5, 10.2), (8.4, 8.2), (13.3, 8.5), (18, 11.3)) + cubic((18, 29.7), (13.3, 26.9), (8.4, 26.6),
                                                                            (3.5, 28.6))
RIGHT_PAGE = mirrored(LEFT_PAGE)
# M6.5 7.6 c3.9-1.3 7.8-1 11.5 1.3 3.7-2.3 7.6-2.6 11.5-1.3 (stroke 2.2) and M21.3 19.6 l2.7 2.7 4.6-5.3 (stroke 2.4)
ARC = cubic((6.5, 7.6), (10.4, 6.3), (14.3, 6.6), (18, 8.9)) + cubic((18, 8.9), (21.7, 6.6), (25.6, 6.3),
                                                                      (29.5, 7.6))[1:]
CHECK: list[Point] = [(21.3, 19.6), (24, 22.3), (28.6, 17)]


def draw(size: int) -> Image.Image:
    over = 8  # supersampling for smooth edges
    scale = size * over / SIDE
    image = Image.new("RGBA", (size * over, size * over), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    def at(points: list[Point]) -> list[Point]:
        return [((x - LEFT) * scale, (y - TOP) * scale) for x, y in points]

    def stroke(points: list[Point], colour: str, width: float) -> None:
        width *= scale * (1.3 if size < 24 else 1.0)  # a little heavier where there are few pixels
        pen.line(at(points), fill=colour, width=round(width), joint="curve")
        for x, y in at([points[0], points[-1]]):  # round caps, as in the SVG
            pen.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=colour)

    pen.polygon(at(LEFT_PAGE), fill=GREEN)
    pen.polygon(at(RIGHT_PAGE), fill=BLUE)
    stroke(ARC, YELLOW, 2.2)
    stroke(CHECK, INK, 2.4)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    target = Path(__file__).with_name("EmneKlar.ico")
    images = [draw(size) for size in SIZES]
    images[-1].save(target, format="ICO", sizes=[(size, size) for size in SIZES], append_images=images[:-1])
    print(f"{target} ({target.stat().st_size} byte, {len(SIZES)} størrelser)")


if __name__ == "__main__":
    main()
