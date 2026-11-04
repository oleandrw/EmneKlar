"""Publishing illustrations – always through the shared change engine.

One staged change per page («Sett inn illustrasjoner»):

* **before** – the live page (body, title, published) when the change is staged; the engine re-reads the page before
  applying and stops with a conflict if anything changed since the preview, so manual edits are never overwritten;
* **backup** – the engine stores the live page before the write (restorable original HTML);
* **apply** – each image is uploaded to the course files (folder «EmneKlar-illustrasjoner», file name from the image's
  hash, so a re-run or a retry after a failure reuses the file instead of uploading it twice); then the figures are
  spliced into the live HTML at their anchors and only ``body`` is sent – the publish state is not touched;
* **verify** – the page is read back: every figure must be there and the publish state unchanged;
* **undo** – removes exactly the figures EmneKlar inserted (``data-emneklar-illustration``). Everything else on the
  page, including what the teacher changed after publishing, stays. If the teacher edited one of the figures, undo
  stops instead of deleting their edit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from emneklar.core.canvas.api import USE_JUSTIFICATIONS, CanvasAPI, is_block_editor_page
from emneklar.core.canvas.client import WritePermit
from emneklar.core.changes.appliers import Applier, ChangeData, register, state_fingerprint
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.features.illustrations.assets import EXT, AssetStore
from emneklar.features.illustrations.placement import (
    Anchor,
    Insertion,
    PlacementError,
    figure_html,
    find_figures,
    insert,
    remove,
)
from emneklar.features.illustrations.store import Store, marker_for
from emneklar.features.illustrations.structure import parse_page

KIND = "page.insert_illustrations"
DOMAIN = "illustrations"
MAX_BODY = 500_000


def _stale_markers(existing: set[str], items: list[dict[str, Any]]) -> set[str]:
    """Older versions of the same illustrations already on the page (replaced when a new image is published)."""
    stale = set()
    for item in items:
        prefix = f"ill-{item['illustration_id']}-"
        stale |= {m for m in existing if m.startswith(prefix) and m != item["marker"]}
    return stale


class InsertIllustrations(Applier):
    kind = KIND
    label = "Sett inn illustrasjoner"
    object_type = "page"
    undo_capability = "partial"
    undo_note = ("Angring fjerner bare figurene EmneKlar satte inn. Alt annet på siden beholdes – også endringer "
                 "gjort etterpå. Bildefilene blir liggende i Canvas-filene og kan slettes der.")

    def validate(self, change: ChangeData) -> None:
        proposed = change.proposed
        items = proposed.get("illustrations")
        if not isinstance(proposed.get("body"), str) or not isinstance(items, list) or not items:
            raise AppError("validation_error", detail="Mangler illustrasjoner")
        if len(proposed["body"].encode("utf-8")) > MAX_BODY:
            raise AppError("validation_error", detail="Innholdet er større enn Canvas tillater (500 kB)")
        for item in items:
            missing = {"illustration_id", "marker", "path", "sha256", "file_name", "media_type", "anchor", "alt"} - set(
                item)
            if missing:
                raise AppError("validation_error", detail=f"Ufullstendig illustrasjon: {sorted(missing)}")
        rights = proposed.get("usage_rights")
        if rights and rights.get("use_justification") not in USE_JUSTIFICATIONS:
            raise AppError("validation_error", detail="Ugyldig opphavsrettsgrunnlag")

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        page = await api.get_page(change.course_id, change.target["object_id"])
        if is_block_editor_page(page):
            raise AppError("unsupported", message="Siden er laget i blokkredigereren og kan ikke endres som HTML.")
        body = page.get("body") or ""
        return {"body": body, "title": page.get("title"), "published": page.get("published"),
                "figures": find_figures(body)}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        if "applied_figures" in before:
            # Undo: only EmneKlar's own figures matter. A figure the teacher edited must not be deleted.
            figures = current.get("figures") or {}
            return any(marker in figures and figures[marker] != html
                       for marker, html in (before.get("applied_figures") or {}).items() if html)
        keys = ("body", "title", "published")
        return state_fingerprint({k: before.get(k) for k in keys}) != state_fingerprint(
            {k: current.get(k) for k in keys})

    async def _file(self, api: CanvasAPI, change: ChangeData, item: dict[str, Any], permit: WritePermit
                    ) -> tuple[dict[str, Any], bool]:
        path = Path(item["path"])
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise AppError("not_found", message="Bildefilen finnes ikke lenger i EmneKlars datamappe.") from exc
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise AppError("file_parse_failed", message="Bildefilen er endret eller skadet i datamappen.")
        existing = [f for f in await api.find_course_file(change.course_id, item["file_name"])
                    if int(f.get("size") or -1) == len(data)]
        if existing:
            return existing[0], True
        uploaded = await api.upload_course_file(change.course_id, name=item["file_name"], data=data,
                                                content_type=item["media_type"],
                                                folder_path=str(change.proposed.get("folder") or "EmneKlar-illustrasjoner"),
                                                permit=permit)
        return uploaded, False

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        items = list(change.proposed["illustrations"])
        files: list[dict[str, Any]] = []
        insertions: list[Insertion] = []
        rights = change.proposed.get("usage_rights") or None
        # 1. Upload first (slow). The page is read only afterwards, right before the write, so a save the teacher
        #    makes while images are uploading is detected instead of overwritten.
        for item in items:
            file, reused = await self._file(api, change, item, permit)
            if file.get("locked"):
                if not rights:
                    raise AppError("illustration_file_locked", status=409)
                await api.set_usage_rights(change.course_id, [str(file["id"])],
                                           use_justification=rights["use_justification"],
                                           legal_copyright=rights.get("legal_copyright"), publish=True, permit=permit)
            src = f"/courses/{change.course_id}/files/{file['id']}/preview"
            insertions.append(Insertion(item["marker"], Anchor.from_dict(item["anchor"]), figure_html(
                marker=item["marker"], src=src, alt=item.get("alt") or "",
                caption=item.get("caption") if item.get("caption_enabled", True) else None,
                width=item.get("width"), height=item.get("height"), decorative=bool(item.get("decorative")))))
            files.append({"illustration_id": item["illustration_id"], "file_id": str(file["id"]),
                          "marker": item["marker"], "src": src, "reused": reused, "file_name": file.get("display_name")})
        # 2. Re-read and compare with the state the engine checked before the backup. Anything else → stop.
        live = await self.current(api, change)
        keys = ("body", "title", "published")
        if state_fingerprint({k: change.before.get(k) for k in keys}) != state_fingerprint({k: live.get(k) for k in keys}):
            raise AppError("change_conflict", status=409,
                           message="Siden ble endret i Canvas mens bildene ble lastet opp. Ingenting på siden er endret "
                                   "– se over forslaget og publiser på nytt.")
        body = str(live["body"])
        replace = dict(change.proposed.get("replace") or {})
        stale = _stale_markers(set(live["figures"]), items)
        for marker in stale:
            if replace.get(marker) is None or live["figures"].get(marker) != replace[marker]:
                raise AppError("change_conflict", status=409,
                               message="En tidligere versjon av illustrasjonen er endret på siden. EmneKlar fjerner den "
                                       "ikke automatisk – angre eller fjern den selv først.")
        # 3. Splice and write straight away.
        try:
            if stale:
                body, _ = remove(body, stale)
            new_body = insert(body, insertions)
        except PlacementError as exc:
            raise AppError("illustration_page_changed", status=409, message=str(exc)) from exc
        await api.update_page(change.course_id, change.target["object_id"], {"body": new_body}, permit=permit)
        after = await self.current(api, change)
        markers = [i.marker for i in insertions]
        return {**after, "applied_figures": {m: after["figures"].get(m) for m in markers}, "files": files,
                "page_hash": hashlib.sha256(str(after["body"]).encode("utf-8")).hexdigest()}

    def verify(self, proposed: dict[str, Any], after: dict[str, Any]) -> list[str]:
        problems = []
        figures = after.get("figures") or {}
        if any(item["marker"] not in figures for item in proposed.get("illustrations") or []):
            problems.append("illustrasjonene")
        if "_published" in proposed and after.get("published") != proposed["_published"]:
            problems.append("publiseringsstatus")
        return problems

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit
                   ) -> dict[str, Any]:
        live = await self.current(api, change)
        markers = {item["marker"] for item in change.proposed.get("illustrations") or []}
        try:
            new_body, removed = remove(str(live["body"]), markers)
        except PlacementError as exc:
            raise AppError("undo_conflict", status=409, message=str(exc)) from exc
        if removed:
            await api.update_page(change.course_id, change.target["object_id"], {"body": new_body}, permit=permit)
        after = await self.current(api, change)
        return {**after, "removed": removed}


register(InsertIllustrations())


async def build_page_change(c: AppContainer, course_id: str, page_url: str, illustrations: list[dict[str, Any]],
                            *, usage_rights: dict[str, Any] | None, folder: str) -> dict[str, Any]:
    """Read the live page and compute exactly what publishing would change (no write, nothing staged)."""
    assets = AssetStore(c.db, c.config.illustrations_dir)
    api = CanvasAPI(c.canvas())
    page = await api.get_page(course_id, page_url)
    if is_block_editor_page(page):
        raise AppError("unsupported", message="Siden er laget i blokkredigereren og kan ikke endres som HTML.")
    body = page.get("body") or ""
    items: list[dict[str, Any]] = []
    for ill in illustrations:
        if not ill.get("asset_id"):
            raise AppError("validation_error", message=f"Illustrasjon {ill['id']} har ikke noe bilde ennå.")
        asset = assets.get(ill["asset_id"])
        path = assets.path(ill["asset_id"])
        marker = marker_for(ill)
        items.append({"illustration_id": ill["id"], "marker": marker, "asset_id": ill["asset_id"], "path": str(path),
                      "sha256": asset["sha256"], "media_type": asset["media_type"],
                      "file_name": f"emneklar-{asset['sha256'][:16]}.{EXT.get(asset['media_type'], 'png')}",
                      "width": asset["width"], "height": asset["height"], "anchor": ill["anchor"],
                      "alt": "" if ill["decorative"] else ill["alt_text"], "decorative": ill["decorative"],
                      "caption": ill["caption"], "caption_enabled": ill["caption_enabled"] and bool(ill["caption"])})
    figures = find_figures(body)
    existing = set(figures)
    stale = _stale_markers(existing, items)
    replace: dict[str, str] = {}
    published = {ill["id"]: ill.get("published") or {} for ill in illustrations}
    for marker in stale:
        illustration_id = int(marker.split("-")[1])
        known = published.get(illustration_id) or {}
        if known.get("marker") != marker or not known.get("figure") or figures.get(marker) != known["figure"]:
            raise AppError("illustration_page_changed", status=409,
                           message="En tidligere versjon av illustrasjonen på siden er endret etter publisering (eller "
                                   "kopiert). EmneKlar erstatter den ikke automatisk – angre eller fjern den selv først.")
        replace[marker] = known["figure"]
    try:
        base, _ = remove(body, stale) if stale else (body, [])
    except PlacementError as exc:
        raise AppError("illustration_page_changed", status=409, message=str(exc)) from exc
    structure = parse_page(base)
    if not structure.reliable:
        raise AppError("illustration_page_changed", status=409,
                       message="Sidens HTML er for uryddig til at bilder kan settes inn automatisk.")
    previews = []
    for item in items:
        previews.append(Insertion(item["marker"], Anchor.from_dict(item["anchor"]), figure_html(
            marker=item["marker"], src=f"/api/illustrations/assets/{item['asset_id']}", alt=item["alt"],
            caption=item["caption"] if item["caption_enabled"] else None, width=item["width"], height=item["height"],
            decorative=item["decorative"])))
    try:
        preview_body = insert(base, previews)
    except PlacementError as exc:
        raise AppError("illustration_page_changed", status=409, message=str(exc)) from exc
    already = [i["marker"] for i in items if i["marker"] in existing]
    return {"page": page, "body": body, "items": items, "preview_body": preview_body, "replaces": sorted(stale),
            "replace": replace, "already_on_page": already, "folder": folder, "usage_rights": usage_rights}


def with_queued(store: Store, course_id: str, page_url: str, chosen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The page's change replaces the open change for the page in the queue, so illustrations of the page that are
    already queued (from any run) are carried over – nothing queued is silently dropped."""
    ids = {i["id"] for i in chosen}
    queued = [i for i in store.for_page(course_id, page_url, statuses=("staged",)) if i["id"] not in ids and i["asset_id"]]
    return [*chosen, *queued]


async def stage_page(c: AppContainer, course_id: str, page_url: str, illustrations: list[dict[str, Any]], *,
                     usage_rights: dict[str, Any] | None, folder: str) -> dict[str, Any]:
    """Stage one change for a page with its approved illustrations and those already queued for the page."""
    illustrations = with_queued(Store(c.db), course_id, page_url, illustrations)
    built = await build_page_change(c, course_id, page_url, illustrations, usage_rights=usage_rights, folder=folder)
    page, items = built["page"], built["items"]
    purposes = "; ".join(str((ill.get("plan") or {}).get("pedagogical_purpose") or "") for ill in illustrations)
    title = page.get("title") or page_url
    change = c.changes.stage(
        course_id=course_id, domain=DOMAIN, kind=KIND,
        title=f"{title}: {len(items)} illustrasjon{'er' if len(items) != 1 else ''}",
        target={"object_type": "page", "object_id": page_url, "title": title},
        before={"body": built["body"], "title": page.get("title"), "published": page.get("published")},
        proposed={"body": built["preview_body"], "illustrations": items, "folder": folder,
                  "usage_rights": usage_rights or None, "replace": built["replace"],
                  "_published": page.get("published")},
        rationale=("KI-bildeassistenten: " + purposes)[:4000], risk="medium",
        source={"feature": "illustrations", "illustration_ids": [i["id"] for i in illustrations]},
        ai_generated=True, merge=True)
    store = Store(c.db)
    for ill in illustrations:
        store.update(ill["id"], status="staged", change_id=change["id"], error=None)
    return change
