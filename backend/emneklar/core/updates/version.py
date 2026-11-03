"""Semantic versions and CHANGELOG.md sections (shared by the app and scripts/update.py)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
HEADING = re.compile(r"^## \[([^\]]+)\](.*)$")


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    pre: str | None = None

    @classmethod
    def parse(cls, value: str | None) -> Version | None:
        match = SEMVER.match((value or "").strip())
        if not match:
            return None
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4))

    def key(self) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
        # A pre-release sorts before the release (1.0.0-beta < 1.0.0); numeric parts compare numerically.
        pre = tuple((0, int(p)) if p.isdigit() else (1, p) for p in (self.pre or "").split(".") if p)
        return self.major, self.minor, self.patch, 0 if self.pre else 1, pre

    def __lt__(self, other: Version) -> bool:
        return self.key() < other.key()

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}" + (f"-{self.pre}" if self.pre else "")

    def is_major_upgrade_to(self, other: Version) -> bool:
        """Major per SemVer – and while on 0.x, a minor bump may break things too."""
        if other.major != self.major:
            return other.major > self.major
        return self.major == 0 and other.minor > self.minor


def changelog_sections(path: Path, limit: int = 5) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    sections: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    lines: list[str] = []
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            if current is not None:
                current["body"] = "\n".join(lines).strip()
                sections.append(current)
            current, lines = {"version": match.group(1), "title": match.group(2).strip(" –-")}, []
        elif current is not None:
            lines.append(line)
    if current is not None:
        current["body"] = "\n".join(lines).strip()
        sections.append(current)
    return [s for s in sections if s["body"] or s["version"].lower() != "unreleased"][:limit]
