"""Audio for transcription by an AI provider: decode, resample and cut into pieces at pauses.

Runs in an isolated worker (job ``rag_audio_pieces``): media files are untrusted. Only the audio leaves the machine,
never the picture: the file is decoded to 16 kHz mono with FFmpeg (through PyAV, or an ``ffmpeg`` program on
PATH) and cut into WAV pieces of 60–120 seconds at the quietest moment, so no word is cut in half and every piece
gives an exact timestamp, also with models that return text without timestamps. Silent pieces are not sent.
"""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 16_000
PIECE_MIN = 60.0
PIECE_TARGET = 90.0
PIECE_MAX = 120.0
WINDOW = 0.25  # seconds per energy window when looking for a pause
MAX_SECONDS = 6 * 3600
SILENCE_RMS = 60.0  # int16 RMS below this is treated as silence


def _decode_pyav(path: str) -> np.ndarray | None:
    import av

    chunks: list[np.ndarray] = []
    with av.open(path) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            return None
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        total = 0
        for frame in container.decode(stream):
            if not isinstance(frame, av.AudioFrame):
                continue
            for out in resampler.resample(frame):
                data = out.to_ndarray().reshape(-1)
                chunks.append(data)
                total += len(data)
            if total > MAX_SECONDS * SAMPLE_RATE:
                break
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.int16) if chunks else np.zeros(0, dtype=np.int16)


def _decode_ffmpeg(path: str) -> np.ndarray | None:
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise ImportError("ffmpeg")
    done = subprocess.run([binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-ac", "1",
                           "-ar", str(SAMPLE_RATE), "-t", str(MAX_SECONDS), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
                          capture_output=True, timeout=1800, check=False)
    if done.returncode != 0:
        return None
    return np.frombuffer(done.stdout, dtype=np.int16)


def decode(path: str) -> np.ndarray | None:
    """16 kHz mono int16 samples, or None when the file has no audio stream."""
    try:
        return _decode_pyav(path)
    except ImportError:
        return _decode_ffmpeg(path)


def cut_points(samples: np.ndarray, *, minimum: float = PIECE_MIN, target: float = PIECE_TARGET,
               maximum: float = PIECE_MAX) -> list[tuple[int, int]]:
    """Piece boundaries (sample indices): each piece is minimum–maximum seconds, cut at the quietest window."""
    total = len(samples)
    if total == 0:
        return []
    step = int(WINDOW * SAMPLE_RATE)
    windows = len(samples) // step
    energy = np.sqrt(np.mean(samples[: windows * step].astype(np.float32).reshape(windows, step) ** 2, axis=1)) \
        if windows else np.zeros(0)
    pieces: list[tuple[int, int]] = []
    start = 0
    while start < total:
        if total - start <= maximum * SAMPLE_RATE:
            pieces.append((start, total))
            break
        first = int((start + minimum * SAMPLE_RATE) // step)
        last = min(windows - 1, int((start + maximum * SAMPLE_RATE) // step))
        if last <= first:
            end = min(total, start + int(maximum * SAMPLE_RATE))
        else:
            candidates = energy[first:last + 1]
            positions = np.arange(first, last + 1) * step
            # Prefer quiet windows; among equally quiet ones, the one nearest the target length.
            distance = np.abs(positions - (start + target * SAMPLE_RATE)) / (SAMPLE_RATE * maximum)
            score = candidates / (float(candidates.max()) + 1e-6) + 0.15 * distance
            end = int(positions[int(np.argmin(score))] + step // 2)
        pieces.append((start, end))
        start = end
    return pieces


def audio_pieces(path: str, out_dir: str) -> dict[str, Any]:
    """Worker job: write WAV pieces and return their paths and times (seconds)."""
    try:
        samples = decode(path)
    except ImportError:
        return {"error": "no_decoder"}
    except Exception:  # noqa: BLE001 - a broken or unsupported media file
        return {"error": "decode_failed"}
    if samples is None or len(samples) == 0:
        return {"error": "no_audio"}
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    pieces = []
    for index, (begin, end) in enumerate(cut_points(samples), start=1):
        chunk = samples[begin:end]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) if len(chunk) else 0.0
        file = target / f"lyd-{index:03d}.wav"
        silent = rms < SILENCE_RMS
        if not silent:
            with wave.open(str(file), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(SAMPLE_RATE)
                out.writeframes(chunk.tobytes())
        pieces.append({"path": str(file), "start": round(begin / SAMPLE_RATE, 2), "end": round(end / SAMPLE_RATE, 2),
                       "silent": silent})
    return {"pieces": pieces, "duration": round(len(samples) / SAMPLE_RATE, 2)}
