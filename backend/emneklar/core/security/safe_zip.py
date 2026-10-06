"""Defensive ZIP handling for ZIP-based document formats (DOCX/PPTX/XLSX).

Adapted from the KI-vurderingsstøtte project.

Used for plain .zip submissions *and* for DOCX/XLSX/PPTX/ODF/EPUB containers,
so every container format gets the same protection against:

* zip bombs (declared and actual sizes are both enforced; compression ratio cap),
* enormous numbers of entries,
* path traversal / zip slip (members are never extracted to a path derived
  from their name - we write to random temp names),
* symbolic links and special files,
* encrypted members.
"""

from __future__ import annotations

import secrets
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class ZipLimits:
    max_archive_entries: int = 500
    max_archive_total_bytes: int = 300 * 1024 * 1024
    max_archive_entry_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 120.0
    max_xml_part_bytes: int = 60 * 1024 * 1024


CONTAINER_MAX_ENTRIES = 5000  # OOXML/ODF can legitimately have many parts
_RATIO_MIN_SIZE = 1024 * 1024  # small files may compress extremely well; only check larger ones


class ZipLimitError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ExtractedMember:
    temp_path: Path
    display_name: str  # sanitised member name (display only)
    size: int


def is_unsafe_member_name(name: str) -> bool:
    if not name or "\x00" in name:
        return True
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or (len(normalised) > 1 and normalised[1] == ":"):
        return True
    return any(part == ".." for part in PurePosixPath(normalised).parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """True for symlinks and other special files (only when a Unix file type is recorded)."""
    file_type = stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)
    return file_type not in (0, stat.S_IFREG, stat.S_IFDIR)


class SafeZip:
    def __init__(self, path: Path, limits: ZipLimits, *, container: bool = False) -> None:
        self.limits = limits
        try:
            self._zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ZipLimitError("corrupt_archive", "Arkivet er ødelagt eller ugyldig") from exc
        infos = self._zf.infolist()
        max_entries = CONTAINER_MAX_ENTRIES if container else limits.max_archive_entries
        if len(infos) > max_entries:
            self._zf.close()
            raise ZipLimitError("too_many_entries", f"Arkivet har for mange filer ({len(infos)})")
        total = sum(i.file_size for i in infos)
        if total > limits.max_archive_total_bytes:
            self._zf.close()
            raise ZipLimitError("archive_too_large", "Arkivet er for stort når det pakkes ut")
        self._infos = {i.filename: i for i in infos}

    def __enter__(self) -> SafeZip:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._zf.close()

    def names(self) -> list[str]:
        return list(self._infos)

    def infos(self) -> list[zipfile.ZipInfo]:
        return list(self._infos.values())

    def has(self, name: str) -> bool:
        return name in self._infos

    def _check(self, info: zipfile.ZipInfo, max_bytes: int) -> None:
        if info.flag_bits & 0x1:
            raise ZipLimitError("encrypted_member", f"{info.filename} er kryptert")
        if info.file_size > max_bytes:
            raise ZipLimitError("member_too_large", f"{info.filename} er for stor")
        if info.file_size >= _RATIO_MIN_SIZE:
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > self.limits.max_compression_ratio:
                raise ZipLimitError("compression_ratio", f"{info.filename} har mistenkelig høy komprimeringsgrad")

    def read(self, name: str, max_bytes: int | None = None) -> bytes:
        info = self._infos.get(name)
        if info is None:
            raise KeyError(name)
        limit = max_bytes if max_bytes is not None else self.limits.max_xml_part_bytes
        self._check(info, limit)
        # The declared size can lie; count what is actually decompressed.
        chunks: list[bytes] = []
        size = 0
        try:
            with self._zf.open(info) as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise ZipLimitError("member_too_large", f"{info.filename} er større enn oppgitt")
                    chunks.append(chunk)
        except (zipfile.BadZipFile, EOFError, zlib.error) as exc:
            raise ZipLimitError("corrupt_member", f"{info.filename} er ødelagt") from exc
        return b"".join(chunks)

    def extract_all(self, dest_dir: Path) -> tuple[list[ExtractedMember], list[tuple[str, str]]]:
        """Extract regular files to random names in ``dest_dir``.

        Returns (extracted members, skipped [(name, reason_code)]).
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        extracted: list[ExtractedMember] = []
        skipped: list[tuple[str, str]] = []
        total = 0
        for info in self._infos.values():
            if info.is_dir():
                continue
            name = info.filename
            if is_unsafe_member_name(name):
                skipped.append((name, "path_traversal"))
                continue
            if _is_symlink(info):
                skipped.append((name, "symlink"))
                continue
            parts = PurePosixPath(name.replace("\\", "/")).parts
            if any(p.startswith(".") and p not in {".", ".."} for p in parts) or "__MACOSX" in parts:
                skipped.append((name, "hidden"))
                continue
            try:
                self._check(info, self.limits.max_archive_entry_bytes)
            except ZipLimitError as exc:
                skipped.append((name, exc.code))
                continue
            target = dest_dir / f"m_{secrets.token_hex(8)}"
            size = 0
            try:
                with self._zf.open(info) as src, target.open("wb") as out:
                    while True:
                        chunk = src.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        total += len(chunk)
                        if size > self.limits.max_archive_entry_bytes:
                            raise ZipLimitError("member_too_large", name)
                        if total > self.limits.max_archive_total_bytes:
                            raise ZipLimitError("archive_too_large", name)
                        out.write(chunk)
            except ZipLimitError as exc:
                target.unlink(missing_ok=True)
                skipped.append((name, exc.code))
                if exc.code == "archive_too_large":
                    break
                continue
            except (zipfile.BadZipFile, OSError, EOFError, zlib.error):
                target.unlink(missing_ok=True)
                skipped.append((name, "corrupt"))
                continue
            extracted.append(ExtractedMember(target, name.replace("\\", "/"), size))
        return extracted, skipped
