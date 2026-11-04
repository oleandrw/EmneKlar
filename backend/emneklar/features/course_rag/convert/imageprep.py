"""Images and video frames, prepared inside an isolated worker process (untrusted files).

* ``rag_image_prepare``: decode an image, measure it (size, how uniform it is), compute a perceptual hash (dHash)
  and write a downscaled copy (longest side ≤ 1568 px, the size image models work best with).
* ``rag_keyframes``: sample a video every few seconds and keep the frames where the picture changes (scene
  change – typically a new slide in a lecture recording). Uses PyAV, which comes with faster-whisper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_SIDE = 1568
MAX_PIXELS = 40_000_000
MAX_KEYFRAMES = 30
SAMPLE_SECONDS = 2.0
SCENE_THRESHOLD = 18.0  # mean absolute difference (0–255) between downscaled grey frames


def _dhash(image: Any) -> int:
    from PIL import Image

    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return bits


def _spread(image: Any) -> float:
    from PIL import ImageStat

    return float(ImageStat.Stat(image.convert("L").resize((64, 64))).stddev[0])


def prepare_image(path: str, out_path: str) -> dict[str, Any]:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(path) as opened:
            fmt = (opened.format or "").lower()
            frames = int(getattr(opened, "n_frames", 1) or 1)
            opened.seek(0)
            image = opened.convert("RGBA" if opened.mode in ("RGBA", "LA", "P") else "RGB")
    except Image.DecompressionBombError:
        return {"error": "too_large"}
    except Exception:  # noqa: BLE001 - not an image, or a broken one
        return {"error": "not_image"}
    width, height = image.size
    result: dict[str, Any] = {"format": fmt, "width": width, "height": height, "frames": frames,
                              "dhash": f"{_dhash(image):016x}", "spread": round(_spread(image), 2)}
    scale = min(1.0, MAX_SIDE / max(width, height))
    if scale < 1.0:
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    target = Path(out_path)
    if image.mode == "RGBA":
        image.save(target.with_suffix(".png"), format="PNG", optimize=True)
        result.update(path=str(target.with_suffix(".png")), media_type="image/png")
    else:
        image.save(target.with_suffix(".jpg"), format="JPEG", quality=88)
        result.update(path=str(target.with_suffix(".jpg")), media_type="image/jpeg")
    return result


def extract_keyframes(path: str, out_dir: str, max_frames: int = MAX_KEYFRAMES) -> dict[str, Any]:
    try:
        import av
    except ImportError:
        return {"error": "unsupported"}
    from PIL import ImageChops, ImageStat

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    previous = None
    next_time = 0.0
    with av.open(path) as container:
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            return {"frames": []}
        for frame in container.decode(stream):
            if not isinstance(frame, av.VideoFrame) or frame.time is None or frame.time < next_time:
                continue
            next_time = frame.time + SAMPLE_SECONDS
            image = frame.to_image()
            grey = image.convert("L").resize((64, 36))
            changed = previous is None or ImageStat.Stat(ImageChops.difference(grey, previous)).mean[0] >= SCENE_THRESHOLD
            previous = grey
            if not changed:
                continue
            file = target / f"bilde-{len(frames) + 1}.jpg"
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            image.convert("RGB").save(file, format="JPEG", quality=85)
            frames.append({"time": round(float(frame.time), 2), "path": str(file)})
            if len(frames) >= max_frames:
                break
    return {"frames": frames}
