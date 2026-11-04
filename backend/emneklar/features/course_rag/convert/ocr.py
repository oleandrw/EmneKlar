"""OCR for scanned PDFs.

Pages are rendered to images in an isolated worker (``rag_render_pdf``, pypdfium2). Text recognition then uses,
in this order:

1. Tesseract, if it is installed on the machine with the Norwegian language pack (``nor``) – local and free;
2. the image model of the AI layer (task ``rag_image``), when images are enabled for the build and AI is allowed;
3. otherwise the file is skipped with an explanation.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path
from typing import Any

MAX_OCR_PAGES = 40


def render_pdf_pages(path: str, out_dir: str, max_pages: int = MAX_OCR_PAGES, scale: float = 2.0) -> dict[str, Any]:
    """Worker job: render the first ``max_pages`` pages to PNG files."""
    import pypdfium2 as pdfium

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(path)
    pages = []
    try:
        total = len(pdf)
        for index in range(min(total, max_pages)):
            page = pdf[index]
            image = page.render(scale=scale).to_pil()
            file = target / f"side-{index + 1}.png"
            image.save(file, format="PNG")
            pages.append({"number": index + 1, "path": str(file)})
            page.close()
    finally:
        pdf.close()
    return {"pages": pages, "total": total}


@functools.cache
def tesseract_languages() -> tuple[str, ...] | None:
    binary = shutil.which("tesseract")
    if binary is None:
        return None
    try:
        done = subprocess.run([binary, "--list-langs"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    langs = tuple(line.strip() for line in done.stdout.splitlines()[1:] if line.strip())
    return langs if "nor" in langs else None


def tesseract_text(image: Path) -> str:
    langs = tesseract_languages()
    binary = shutil.which("tesseract")
    if not langs or binary is None:
        return ""
    lang = "nor+eng" if "eng" in langs else "nor"
    done = subprocess.run([binary, str(image), "stdout", "-l", lang], capture_output=True, text=True, timeout=180,
                          check=False)
    return done.stdout if done.returncode == 0 else ""
