"""Local speech-to-text with NB-Whisper (Nasjonalbiblioteket) through faster-whisper / CTranslate2.

* Audio is decoded with FFmpeg through PyAV (bundled with faster-whisper – no separate ffmpeg install).
* The language is detected first. Norwegian (and undetermined) speech uses NB-Whisper; other languages use the
  standard Whisper model from the catalog (default large-v3).
* Model size: chosen automatically from the hardware (large on a CUDA GPU; medium on a CPU with ≥ 16 GB RAM and
  ≥ 8 cores, otherwise small) or set under Emne-RAG → Innstillinger.
* NB-Whisper is published in Hugging Face Transformers format. The official model is downloaded and converted to
  CTranslate2 locally once (``<data>/models/ct2``), instead of relying on unofficial conversions.
* Segment timestamps are kept. Transcription runs in a worker thread and can be stopped between segments.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from emneklar.core.ai.local import LocalModelDef, LocalModels
from emneklar.core.errors import AppError

log = logging.getLogger(__name__)

NORWEGIAN = {"no", "nn", "nb"}
NB_FILES = ["*.json", "*.safetensors", "*.txt", "*.model", "tokenizer*", "vocab*", "merges*"]


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "text": self.text}


@dataclass
class Transcript:
    segments: list[Segment]
    language: str | None
    model: str
    source: str  # captions | whisper | youtube
    duration: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"segments": [s.as_dict() for s in self.segments], "language": self.language, "model": self.model,
                "source": self.source, "duration": self.duration, "notes": self.notes}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        return cls([Segment(float(s["start"]), float(s["end"]), str(s["text"])) for s in data.get("segments") or []],
                   data.get("language"), str(data.get("model") or ""), str(data.get("source") or "whisper"),
                   data.get("duration"), list(data.get("notes") or []))


class TranscriptionStopped(Exception):
    pass


def memory_gb() -> float | None:
    try:
        if sys.platform == "win32":
            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys / 1024**3
            return None
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (OSError, ValueError, AttributeError):
        return None


def auto_size(device: str) -> str:
    if device == "cuda":
        return "large"
    ram = memory_gb() or 8
    return "medium" if ram >= 16 and (os.cpu_count() or 4) >= 8 else "small"


def choose_models(local: LocalModels, size_setting: str, other_setting: str, device: str) -> tuple[LocalModelDef,
                                                                                                    LocalModelDef]:
    size = auto_size(device) if size_setting == "auto" else size_setting
    nb = next((m for m in local.catalog("whisper") if m.size == size), None) or local.model("whisper")
    other = local.model("whisper_other", other_setting)
    return nb, other


class Transcriber:
    """Loads the models lazily (and only the ones actually needed) and transcribes files."""

    def __init__(self, local: LocalModels, nb: LocalModelDef, other: LocalModelDef, device: str) -> None:
        self.local = local
        self.nb = nb
        self.other = other
        self.device = device
        self.compute_type = "float16" if device == "cuda" else "int8"
        self._models: dict[str, Any] = {}
        self._lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.local.packages().get("faster_whisper"))

    def downloads_needed(self) -> list[LocalModelDef]:
        return [m for m in (self.nb,) if not self._ready(m)]

    def _converted(self, model: LocalModelDef) -> Path:
        return self.local.converted_dir / model.id.replace("/", "--")

    def _ready(self, model: LocalModelDef) -> bool:
        if model.format == "ct2":
            return self.local.is_downloaded(model.id)
        return (self._converted(model) / "model.bin").is_file()

    def _path(self, model: LocalModelDef) -> str:
        """A local CTranslate2 model directory (downloads and converts the first time)."""
        if model.format == "ct2":
            return model.id  # faster-whisper downloads CTranslate2 repositories itself
        target = self._converted(model)
        if (target / "model.bin").is_file():
            return str(target)
        self.local.prepare_environment()
        from huggingface_hub import snapshot_download

        log.info("Laster ned %s fra Hugging Face", model.id)
        source = Path(snapshot_download(model.id, cache_dir=str(self.local.hub_dir), allow_patterns=NB_FILES))
        if (source / "model.bin").is_file():
            return str(source)
        try:
            import ctranslate2
        except ImportError as exc:
            raise AppError("rag_local_models_missing", status=409) from exc
        log.info("Konverterer %s til CTranslate2 (én gang)", model.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        copy = [name for name in ("tokenizer.json", "preprocessor_config.json") if (source / name).is_file()]
        ctranslate2.converters.TransformersConverter(str(source), copy_files=copy, load_as_float16=True).convert(
            str(tmp), quantization="float16", force=True)
        tmp.replace(target)
        return str(target)

    def _model(self, model: LocalModelDef) -> Any:
        with self._lock:
            if model.id not in self._models:
                from faster_whisper import WhisperModel

                self.local.prepare_environment()
                self._models[model.id] = WhisperModel(self._path(model), device=self.device,
                                                      compute_type=self.compute_type,
                                                      download_root=str(self.local.hub_dir))
            return self._models[model.id]

    def transcribe(self, path: Path, *, stop: Callable[[], bool], progress: Callable[[float], None]) -> Transcript:
        """Blocking – call in a worker thread."""
        if not self.available():
            raise AppError("rag_local_models_missing", status=409)
        from faster_whisper import decode_audio

        audio = decode_audio(str(path))
        duration = len(audio) / 16000
        nb_model = self._model(self.nb)
        language, probability, _ = nb_model.detect_language(audio=audio, language_detection_segments=3)
        notes: list[str] = []
        if language in NORWEGIAN or probability < 0.5:
            model, model_def, lang = nb_model, self.nb, "nn" if language == "nn" else "no"
        else:
            notes.append(f"Talen ser ut til å være på et annet språk ({language}); {self.other.label} er brukt.")
            model, model_def, lang = self._model(self.other), self.other, language
        segments_iter, info = model.transcribe(audio, language=lang, beam_size=5, vad_filter=True,
                                               condition_on_previous_text=False)
        segments: list[Segment] = []
        for segment in segments_iter:
            if stop():
                raise TranscriptionStopped
            text = str(segment.text or "").strip()
            if text:
                segments.append(Segment(float(segment.start), float(segment.end), text))
            if duration:
                progress(min(1.0, float(segment.end) / duration))
        return Transcript(segments, lang, model_def.id, "whisper", float(getattr(info, "duration", duration) or duration),
                          notes)
