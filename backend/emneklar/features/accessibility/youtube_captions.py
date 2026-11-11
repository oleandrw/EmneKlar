"""Do embedded YouTube videos have captions? (WCAG 1.2.2)

Checked with ``youtube-transcript-api`` – the same interface Emne-RAG uses for captions. Only the video id is sent to
YouTube; no course content. The interface is unofficial: YouTube can refuse requests from a network that asks too
often, so the check is polite (two at a time, a short pause, at most :data:`MAX_LOOKUPS` new videos per analysis),
stops for the rest of the analysis when YouTube refuses, and caches every answer for a week (``link_checks``, key
``youtube-captions:<id>``; longer if the link cache in Innstillinger → Analyse is set longer). Whatever could not be
checked stays a manual check – never «missing captions».

Result per video:
* ``manual``  – captions made by the uploader (or a contributor): the video has captions; their accuracy is not judged.
* ``auto``    – only YouTube's automatic captions: «Bør vurderes» – automatic captions are often inaccurate.
* ``none``    – no captions at all: «Sannsynlig avvik».
* ``unavailable`` – the video cannot be read (deleted, private …); reported by the content quality check instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from emneklar.core.storage.models import LinkCheck

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

log = logging.getLogger(__name__)

MAX_LOOKUPS = 400  # new videos per analysis – keeps a first analysis to a few minutes and under YouTube's radar
CONCURRENCY = 2
PAUSE_SECONDS = 0.4
CACHE_HOURS = 7 * 24  # captions rarely change; a new analysis after a week asks YouTube again
CACHE_PREFIX = "youtube-captions:"
BLOCKED_NAMES = {"RequestBlocked", "IpBlocked", "PoTokenRequired", "TooManyRequests"}
NONE_NAMES = {"TranscriptsDisabled", "NoTranscriptFound"}
UNAVAILABLE_NAMES = {"VideoUnavailable", "InvalidVideoId", "VideoUnplayable", "AgeRestricted"}
STATES = ("manual", "auto", "none", "unavailable")


class YoutubeBlocked(Exception):
    """YouTube refused the request (too many requests from this network)."""


@dataclass
class CaptionInfo:
    state: str  # manual|auto|none|unavailable|unknown
    languages: list[str] = field(default_factory=list)
    from_cache: bool = False


Lookup = Callable[[str], CaptionInfo]


def library_lookup(video_id: str) -> CaptionInfo:
    """Blocking lookup (run in a thread). Raises :class:`YoutubeBlocked` when YouTube refuses."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return CaptionInfo("unknown")
    try:
        listing = list(YouTubeTranscriptApi().list(video_id))
    except Exception as exc:
        name = type(exc).__name__
        if name in BLOCKED_NAMES or "429" in str(exc):
            raise YoutubeBlocked(name) from exc
        if name in NONE_NAMES:
            return CaptionInfo("none")
        if name in UNAVAILABLE_NAMES:
            return CaptionInfo("unavailable")
        log.info("YouTube-teksting kunne ikke kontrolleres for %s (%s)", video_id, name)
        return CaptionInfo("unknown")
    manual = [str(t.language_code) for t in listing if not getattr(t, "is_generated", False)]
    automatic = [str(t.language_code) for t in listing if getattr(t, "is_generated", False)]
    if manual:
        return CaptionInfo("manual", manual)
    if automatic:
        return CaptionInfo("auto", automatic)
    return CaptionInfo("none")


def offline_lookup(_video_id: str) -> CaptionInfo:
    """Used when the network is replaced by test doubles: nothing is sent, every video stays a manual check."""
    return CaptionInfo("unknown")


def _key(video_id: str) -> str:
    return hashlib.sha256(f"{CACHE_PREFIX}{video_id}".encode()).hexdigest()


class YoutubeCaptionChecker:
    """One per analysis: shared by all pages, so every video is looked up once."""

    def __init__(self, container: AppContainer, *, cache_hours: int, lookup: Lookup | None = None) -> None:
        self.c = container
        self.cache_hours = cache_hours
        self.lookup = lookup or container.youtube_lookup
        self.semaphore = asyncio.Semaphore(CONCURRENCY)
        self.results: dict[str, CaptionInfo | None] = {}
        self.inflight: dict[str, asyncio.Future[CaptionInfo | None]] = {}
        self.blocked = False
        self.lookups = 0
        self.skipped = 0
        self._last = 0.0

    def _cached(self, video_id: str) -> CaptionInfo | None:
        if self.cache_hours <= 0:
            return None
        with self.c.db.session() as session:
            row = session.get(LinkCheck, _key(video_id))
            if row is None or row.state not in STATES:
                return None
            checked = row.checked_at if row.checked_at.tzinfo else row.checked_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - checked > timedelta(hours=self.cache_hours):
                return None
            languages = json.loads(row.detail or "[]") if (row.detail or "").startswith("[") else []
            return CaptionInfo(row.state, languages, from_cache=True)

    def _store(self, video_id: str, info: CaptionInfo) -> None:
        if info.state not in STATES:
            return
        with self.c.db.session() as session:
            key = _key(video_id)
            row = session.get(LinkCheck, key)
            if row is None:
                row = LinkCheck(url_hash=key, url=f"{CACHE_PREFIX}{video_id}", state=info.state)
                session.add(row)
            row.state, row.http_status, row.final_url = info.state, None, None
            row.detail, row.checked_at = json.dumps(info.languages), datetime.now(UTC)

    async def status(self, video_id: str) -> CaptionInfo | None:
        """Caption state of a video, or None when it could not be checked in this analysis."""
        if video_id in self.results:
            return self.results[video_id]
        if video_id in self.inflight:
            return await self.inflight[video_id]
        future: asyncio.Future[CaptionInfo | None] = asyncio.get_running_loop().create_future()
        self.inflight[video_id] = future
        try:
            info = await self._resolve(video_id)
        except BaseException:
            future.set_result(None)
            raise
        finally:
            self.inflight.pop(video_id, None)
        self.results[video_id] = info
        if not future.done():
            future.set_result(info)
        return info

    async def _resolve(self, video_id: str) -> CaptionInfo | None:
        cached = await asyncio.to_thread(self._cached, video_id)
        if cached is not None:
            return cached
        if self.blocked or self.lookups >= MAX_LOOKUPS:
            self.skipped += 1
            return None
        async with self.semaphore:
            if self.blocked or self.lookups >= MAX_LOOKUPS:  # checked again: others may have counted while we waited
                self.skipped += 1
                return None
            wait = self._last + PAUSE_SECONDS - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
            self.lookups += 1
            try:
                info = await asyncio.to_thread(self.lookup, video_id)
            except YoutubeBlocked:
                self.blocked = True
                self.skipped += 1
                log.info("YouTube blokkerte kontroll av teksting – resten av videoene kontrolleres ved neste analyse")
                return None
        if info.state == "unknown":
            return None
        await asyncio.to_thread(self._store, video_id, info)
        return info

    def limitation(self) -> str | None:
        if self.blocked:
            return (f"YouTube avviste kontroll av teksting etter {self.lookups} videoer (for mange forespørsler fra "
                    f"nettverket). {self.skipped} videoer er vist som «Teksting kan ikke verifiseres automatisk» og "
                    "kontrolleres ved neste analyse.")
        if self.skipped:
            return (f"Teksting ble kontrollert for {self.lookups} nye YouTube-videoer i denne analysen (grensen er "
                    f"{MAX_LOOKUPS} for å ikke bli blokkert av YouTube). {self.skipped} videoer kontrolleres ved neste "
                    "analyse.")
        return None
