r"""Draw packaging/windows/EmneKlar.ico: the same mark as frontend/public/favicon.svg (a check mark on a rounded
dark-blue square), in the sizes Windows uses for shortcuts, the taskbar and the installer.

    backend\.venv\Scripts\python packaging\windows\make_icon.py

Run it again only when the mark changes; the .ico file is committed.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
BACKGROUND, MARK = "#13254a", "#9ec1ff"
SCALE = 32  # favicon.svg is drawn in a 32 x 32 box; everything below is in those units


def draw(size: int) -> Image.Image:
    over = 8  # supersampling for smooth edges
    px = size * over / SCALE
    image = Image.new("RGBA", (size * over, size * over), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((0, 0, size * over - 1, size * over - 1), radius=7 * px, fill=BACKGROUND)
    points = [(9 * px, 16.5 * px), (13.5 * px, 21 * px), (23 * px, 11.5 * px)]
    width = 3.2 * px if size >= 24 else 3.8 * px  # a little heavier where there are few pixels
    pen.line(points, fill=MARK, width=round(width), joint="curve")
    for x, y in points:  # round caps and a round joint, as in the SVG
        pen.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=MARK)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    target = Path(__file__).with_name("EmneKlar.ico")
    images = [draw(size) for size in SIZES]
    images[-1].save(target, format="ICO", sizes=[(size, size) for size in SIZES], append_images=images[:-1])
    print(f"{target} ({target.stat().st_size} byte, {len(SIZES)} størrelser)")


if __name__ == "__main__":
    main()
