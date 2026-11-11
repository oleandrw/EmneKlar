"""EmneKlar stops by itself when its last window has been closed – as a program does.

Every EmneKlar window keeps one connection open to ``GET /api/system/presence`` for as long as it is open. When the
last connection has closed, :class:`WindowPresence` waits :data:`GRACE_SECONDS` (a reload or a short break reconnects
well within that), lets running jobs finish, and then asks the server to stop.

It is armed only when the launcher showed a window itself (the shortcut, ``start.bat``) – never with ``--no-browser``
or ``EMNEKLAR_NO_BROWSER=1``, so tests, CI, the end-to-end tests and the update scripts are not affected – and only
after a window has connected at all: EmneKlar never stops because a browser could not be opened.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

log = logging.getLogger("emneklar.presence")

#: How long EmneKlar waits after the last window has closed before it stops.
GRACE_SECONDS = 15.0
#: How often it looks again while jobs are still running.
JOB_POLL_SECONDS = 2.0


class WindowPresence:
    def __init__(self, *, running_jobs: Callable[[], int], grace: float = GRACE_SECONDS,
                 poll: float = JOB_POLL_SECONDS) -> None:
        self._running_jobs = running_jobs
        self._grace = grace
        self._poll = poll
        #: Called to stop EmneKlar. None (the default): EmneKlar does not stop by itself.
        self.stop: Callable[[], None] | None = None
        #: Set when EmneKlar is stopping, for whatever reason: the open connections end at once.
        self.stopping = asyncio.Event()
        self._open = 0
        self._watch: asyncio.Task[None] | None = None

    @property
    def open_windows(self) -> int:
        return self._open

    def opened(self) -> None:
        self._open += 1

    def closed(self) -> None:
        self._open = max(0, self._open - 1)
        if self._open == 0 and self.stop is not None and not self.stopping.is_set() and self._watch is None:
            self._watch = asyncio.get_running_loop().create_task(self._stop_when_still_closed())

    async def _stop_when_still_closed(self) -> None:
        try:
            await asyncio.sleep(self._grace)
            told = False
            while self._open == 0 and not self.stopping.is_set():
                jobs = self._running_jobs()
                if not jobs:
                    log.info("Alle vinduer er lukket – EmneKlar avsluttes.")
                    if self.stop is not None:
                        self.stop()
                    return
                if not told:
                    log.info("Alle vinduer er lukket. EmneKlar avsluttes når %s jobb(er) er ferdige.", jobs)
                    told = True
                await asyncio.sleep(self._poll)
        finally:
            self._watch = None
