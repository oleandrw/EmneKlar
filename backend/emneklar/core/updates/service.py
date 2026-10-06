"""Update status for Innstillinger → Generelt: installed version, latest release on GitHub, changelog.

The actual update is done by ``update.bat`` (scripts/update.py): it stops EmneKlar,
backs up the database, fetches the new version, installs dependencies, runs
migrations, checks health and restarts – and rolls back if something fails. Major
versions are never installed without explicit confirmation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from emneklar import __version__
from emneklar.config import REPO_DIR
from emneklar.core.errors import AppError
from emneklar.core.storage.models import Setting
from emneklar.core.updates.version import Version, changelog_sections

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

log = logging.getLogger(__name__)
STATUS_KEY = "update_status"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
REMOTE_RE = re.compile(r"github\.com[:/]+([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$")
CHECK_INTERVAL = timedelta(hours=24)


def git_remote_repository(repo_dir: Path) -> str | None:
    """owner/repo from .git/config's origin (no git process needed)."""
    try:
        text = (repo_dir / ".git" / "config").read_text(encoding="utf-8")
    except OSError:
        return None
    section = re.search(r'\[remote "origin"\]([^\[]*)', text)
    url = re.search(r"^\s*url\s*=\s*(\S+)", section.group(1), re.MULTILINE) if section else None
    match = REMOTE_RE.search(url.group(1)) if url else None
    return match.group(1) if match else None


def git_branch(repo_dir: Path) -> str | None:
    try:
        head = (repo_dir / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: ") else head[:12]


class UpdateService:
    def __init__(self, container: AppContainer, repo_dir: Path = REPO_DIR) -> None:
        self.c = container
        self.repo_dir = repo_dir
        self._task: asyncio.Task[Any] | None = None

    # -- installation ---------------------------------------------------------------------------

    def install_info(self) -> dict[str, Any]:
        if (self.repo_dir / ".git").exists():
            kind, label = "git", "Utviklerinstallasjon (Git)"
        elif (self.repo_dir / "install.json").exists():
            kind, label = "release", "Stabil utgivelse"
        else:
            kind, label = "source", "Kopi av kildekoden"
        return {"type": kind, "label": label, "path": str(self.repo_dir),
                "branch": git_branch(self.repo_dir) if kind == "git" else None,
                "can_start_from_app": os.name == "nt" and (self.repo_dir / "update.bat").exists()}

    def repository(self) -> str | None:
        configured = self.c.settings.get().advanced.update_repository
        if configured and REPO_RE.match(configured):
            return configured
        return git_remote_repository(self.repo_dir)

    # -- status ---------------------------------------------------------------------------------

    def _stored(self) -> dict[str, Any]:
        with self.c.db.session() as session:
            row = session.get(Setting, STATUS_KEY)
            return dict(row.value) if row else {}

    def _store(self, value: dict[str, Any]) -> None:
        with self.c.db.session() as session:
            row = session.get(Setting, STATUS_KEY)
            if row is None:
                session.add(Setting(key=STATUS_KEY, value=value))
            else:
                row.value = value

    def status(self) -> dict[str, Any]:
        settings = self.c.settings.get()
        stored = self._stored()
        current = Version.parse(__version__)
        latest = Version.parse((stored.get("latest") or {}).get("version"))
        available = bool(current and latest and current < latest)
        return {
            "current_version": __version__, "install": self.install_info(), "repository": self.repository(),
            "channel": settings.advanced.update_channel, "check_enabled": settings.advanced.check_updates,
            "last_checked_at": stored.get("checked_at"), "last_error": stored.get("error"),
            "latest": stored.get("latest"), "update_available": available,
            "is_major": bool(available and current and latest and current.is_major_upgrade_to(latest)),
            "checking": self._task is not None and not self._task.done(),
            "changelog": changelog_sections(self.repo_dir / "CHANGELOG.md"),
        }

    def check_due(self) -> bool:
        if not self.c.settings.get().advanced.check_updates or not self.repository():
            return False
        checked = self._stored().get("checked_at")
        try:
            return checked is None or datetime.now(UTC) - datetime.fromisoformat(checked) > CHECK_INTERVAL
        except ValueError:
            return True

    def check_in_background(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._safe_check(), name="update-check")

    async def _safe_check(self) -> None:
        with contextlib.suppress(AppError):  # the error is stored as last_error
            await self.check()

    async def check(self) -> dict[str, Any]:
        repo = self.repository()
        if not repo:
            raise AppError("update_check_failed", status=409, message="Oppdateringskilden er ikke satt. Angi "
                           "GitHub-repositoriet under Avanserte innstillinger.")
        prerelease = self.c.settings.get().advanced.update_channel == "prerelease"
        url = f"https://api.github.com/repos/{repo}/releases" + ("?per_page=20" if prerelease else "/latest")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": f"EmneKlar/{__version__}",
                   "X-GitHub-Api-Version": "2022-11-28"}
        now = datetime.now(UTC).isoformat()
        try:
            async with httpx.AsyncClient(transport=self.c.update_transport, timeout=15.0) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            self._store({**self._stored(), "checked_at": now, "error": "Fikk ikke kontakt med GitHub."})
            raise AppError("update_check_failed", status=502, detail=type(exc).__name__) from exc
        if response.status_code == 404:
            self._store({"checked_at": now, "error": "Fant ingen utgivelser for EmneKlar i dette repositoriet.",
                         "latest": None})
            raise AppError("update_check_failed", status=404, message="Fant ingen utgivelser i repositoriet.")
        if response.status_code != 200:
            self._store({**self._stored(), "checked_at": now, "error": f"GitHub svarte {response.status_code}."})
            raise AppError("update_check_failed", status=502, detail=str(response.status_code))
        data = response.json()
        releases = data if isinstance(data, list) else [data]
        candidates = [(Version.parse(r.get("tag_name")), r) for r in releases if isinstance(r, dict)
                      and not r.get("draft") and (prerelease or not r.get("prerelease"))]
        valid = [(v, r) for v, r in candidates if v is not None]
        if not valid:
            self._store({"checked_at": now, "error": "Fant ingen gyldige versjoner.", "latest": None})
            raise AppError("update_check_failed", status=404, message="Fant ingen gyldige versjoner.")
        version, release = max(valid, key=lambda vr: vr[0].key())
        latest = {"version": str(version), "tag": release.get("tag_name"), "name": release.get("name"),
                  "notes": str(release.get("body") or "")[:20000], "url": release.get("html_url"),
                  "published_at": release.get("published_at"), "prerelease": bool(release.get("prerelease"))}
        self._store({"checked_at": now, "error": None, "latest": latest})
        return self.status()

    # -- start ----------------------------------------------------------------------------------

    def start(self, *, confirm_major: bool) -> dict[str, Any]:
        status = self.status()
        if not status["install"]["can_start_from_app"]:
            raise AppError("unsupported", status=409, message="Oppdatering fra appen støttes bare på Windows med "
                           "update.bat. Kjør update.bat i EmneKlar-mappen.")
        if not status["update_available"]:
            raise AppError("conflict", status=409, message="Det finnes ingen nyere versjon å installere.")
        if status["is_major"] and not confirm_major:
            raise AppError("confirmation_required", status=409, message="Dette er en større oppdatering. Les "
                           "endringene og bekreft før du oppdaterer.")
        args = ["cmd.exe", "/c", str(self.repo_dir / "update.bat"), "--from-app"]
        if confirm_major:
            args.append("--allow-major")
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(args, cwd=self.repo_dir, creationflags=flags, close_fds=True)
        log.info("Oppdatering startet fra appen (til %s)", status["latest"]["version"])
        return {"started": True, "message": "Oppdateringen kjører i et eget vindu. EmneKlar starter på nytt når den er "
                                            "ferdig."}
