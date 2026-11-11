"""Blueprint context: where a change is made and which courses it reaches.

EmneKlar does not block Blueprint content itself – Canvas decides what the connected user may change. This module
only *describes* the situation truthfully (docs/CANVAS_API.md → Blueprint):

* **Blueprint course** (``GET …/blueprint_templates/default`` answers): changes are made here and reach the associated
  courses at the next sync (``POST …/blueprint_templates/default/migrations``). Locked content is overwritten in the
  associated courses; for unlocked content Canvas keeps local edits in an associated course («conflicting changes»).
* **Associated course** (``GET …/blueprint_subscriptions`` lists the Blueprint course): unlocked content can be changed
  here, and Canvas then stops syncing the changed parts of that item. Locked content (``restricted_by_master_course``
  with ``master_course_restrictions.content``) is normally refused by Canvas («locked by Master Course») – the
  practical alternative is to make the change in the Blueprint course and sync.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from emneklar.core.canvas.api import CanvasAPI

CACHE_SECONDS = 300.0
_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


async def blueprint_info(api: CanvasAPI, course_id: str, *, fresh: bool = False) -> dict[str, Any]:
    key = (api.client.base_url, course_id)
    cached = _cache.get(key)
    if cached and not fresh and time.monotonic() - cached[0] < CACHE_SECONDS:
        return dict(cached[1])
    template, subscriptions = await asyncio.gather(api.blueprint_template(course_id),
                                                   api.blueprint_subscriptions(course_id))
    parent = (subscriptions[0].get("blueprint_course") or {}) if subscriptions else {}
    info: dict[str, Any] = {
        "is_blueprint": template is not None,
        "associated_course_count": (template or {}).get("associated_course_count"),
        "is_child": bool(subscriptions),
        "parent": {"id": str(parent.get("id")), "name": parent.get("name"), "course_code": parent.get("course_code")}
        if parent.get("id") is not None else None,
    }
    _cache[key] = (time.monotonic(), info)
    return dict(info)


def forget(api: CanvasAPI, course_id: str) -> None:
    _cache.pop((api.client.base_url, course_id), None)


def is_locked(meta_or_evidence: dict[str, Any] | None) -> bool:
    """Content lock as Canvas reports it on list calls (pages, assignments, discussions, quizzes)."""
    data = meta_or_evidence or {}
    restrictions = data.get("master_course_restrictions") or data.get("restrictions") or {}
    restricted = data.get("restricted_by_master_course", data.get("locked"))
    return bool(restricted) and bool(restrictions.get("content") or restrictions.get("all"))


def describe(info: dict[str, Any], lock: dict[str, Any] | None = None) -> dict[str, Any]:
    """Where a change to this course's content is made, in words the teacher understands."""
    lock = lock or {}
    locked = is_locked(lock)
    parent = info.get("parent") or {}
    parent_name = f"«{parent['name']}»" if parent.get("name") else "Blueprint-emnet"
    if info.get("is_blueprint"):
        count = info.get("associated_course_count")
        reach = ("det tilknyttede emnet" if count == 1 else f"de {count} tilknyttede emnene") if count \
            else "de tilknyttede emnene"
        if locked:
            # In the Blueprint course itself the lock applies to the copies in the associated courses, not here.
            detail = (f"Elementet er låst i de tilknyttede emnene, så endringen erstatter innholdet i {reach} ved "
                      "neste synkronisering.")
        else:
            detail = ("Elementet er ikke låst: det oppdateres i tilknyttede emner bare der ingen har endret det "
                      "lokalt.")
        return {"role": "blueprint", "locked": False, "locked_downstream": locked, "parent": None,
                "associated_course_count": count, "sync_needed": True,
                "message": (f"Dette er Blueprint-emnet, og du kan endre innholdet her. Endringen når {reach} først når "
                            f"Blueprint-emnet synkroniseres. {detail}")}
    if info.get("is_child"):
        if locked:
            message = (f"Innholdet er låst av Blueprint-emnet {parent_name}. Canvas tillater vanligvis ikke at låst "
                       "innhold endres her. EmneKlar sender likevel endringen med dine rettigheter. Avviser Canvas den, "
                       "kan du flytte rettingen til Blueprint-emnet (krever tilgang dit) og synkronisere derfra.")
        else:
            message = (f"Emnet er knyttet til Blueprint-emnet {parent_name}. Endringen gjøres bare i dette emnet. Etter "
                       "en lokal endring tar Canvas ikke lenger inn endringer fra Blueprint-emnet for de samme delene av "
                       "elementet.")
        return {"role": "associated", "locked": locked, "parent": parent or None, "associated_course_count": None,
                "sync_needed": False, "message": message}
    return {"role": "course", "locked": False, "parent": None, "associated_course_count": None, "sync_needed": False,
            "message": "Endringen gjøres bare i dette emnet."}


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def describe_selection(info: dict[str, Any], *, total: int, locked: int) -> dict[str, Any] | None:
    """Blueprint in words for a *selection* of content (an overview, so never «Elementet …»): what kind of course this
    is, how many of the selected items are locked, and how changes travel. ``None`` for an ordinary course.

    * Blueprint course: everything can be changed here; locked items are overwritten in the associated courses at the
      next sync, unlocked ones only where nobody changed them locally (Canvas keeps local edits).
    * Associated course: unlocked items change only here (Canvas then stops syncing the changed parts); Canvas normally
      refuses changes to locked items – they can be moved to the Blueprint course from the change queue.
    """
    unlocked = max(0, total - locked)
    if info.get("is_blueprint"):
        count = info.get("associated_course_count")
        reach = _n(count, "tilknyttet emne", "tilknyttede emner") if count else "tilknyttede emner"
        details = []
        if locked:
            details.append(f"{locked} av {total} elementer i utvalget er låst i de tilknyttede emnene. Ved synkronisering "
                           "erstatter innholdet herfra innholdet der.")
        if unlocked:
            details.append(f"{unlocked} av {total} elementer er ikke låst. De oppdateres i et tilknyttet emne bare der "
                           "ingen har endret dem lokalt – lokale endringer beholdes.")
        details.append("Etter publisering tilbyr endringskøen å synkronisere Blueprint-emnet. Synkroniseringen tar med alle "
                       "usynkroniserte endringer i Blueprint-emnet, også dem som er gjort utenfor EmneKlar.")
        return {"role": "blueprint", "locked": locked, "total": total, "limitation": None, "details": details,
                "summary": (f"Dette er et Blueprint-emne med {reach}. Endringene gjøres her og når de tilknyttede emnene "
                            "først når Blueprint-emnet synkroniseres.")}
    if info.get("is_child"):
        parent = info.get("parent") or {}
        name = f"«{parent['name']}»" if parent.get("name") else "et Blueprint-emne"
        details = []
        if unlocked:
            details.append(f"{unlocked} av {total} elementer er ikke låst. De endres bare i dette emnet, og Canvas tar "
                           "deretter ikke lenger inn endringer fra Blueprint-emnet for de samme delene av elementene.")
        if locked:
            details.append(f"{locked} av {total} elementer er låst fra Blueprint-emnet. Canvas avviser vanligvis endringer "
                           "av låst innhold her. EmneKlar sender endringen med dine rettigheter; avviser Canvas den, kan "
                           "du flytte den til Blueprint-emnet fra endringskøen (krever tilgang dit) og synkronisere derfra.")
        limitation = (f"{locked} av {total} elementer er låst fra Blueprint-emnet og må trolig endres der."
                      if locked else None)
        return {"role": "associated", "locked": locked, "total": total, "limitation": limitation, "details": details,
                "summary": (f"Emnet er knyttet til Blueprint-emnet {name}. "
                            + (f"{locked} av {total} elementer i utvalget er låst derfra." if locked
                               else "Ingen av elementene i utvalget er låst derfra."))}
    return None


def is_blueprint_lock_error(detail: str | None) -> bool:
    text = (detail or "").lower()
    return "master course" in text or ("blueprint" in text and "lock" in text)
