"""Change kinds: how to read, compare, apply and (where possible) undo each kind of Canvas change.

Every applier:
* ``current()`` reads the live state of exactly the fields the change touches
  (used for conflict detection and for the backup);
* ``apply()`` writes through the typed API with a WritePermit and returns the
  state read back from Canvas afterwards (Canvas normalises HTML on save, so
  undo compares against what Canvas actually stored);
* ``undo()`` restores the previous state, if the kind supports it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, ClassVar

from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import CanvasError, WritePermit
from emneklar.core.errors import AppError


def normalise_html(html: str | None) -> str:
    text = re.sub(r"\s+", " ", html or "").strip()
    # Canvas adds API helper attributes when serving HTML; they are not content.
    return re.sub(r'\s(data-api-endpoint|data-api-returntype)="[^"]*"', "", text)


def state_fingerprint(state: dict[str, Any]) -> str:
    canonical = {k: (normalise_html(v) if isinstance(v, str) and k in ("body", "description", "message",
                                                                      "syllabus_body") else v)
                 for k, v in state.items() if k not in ("updated_at",)}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass
class ChangeData:
    id: int
    course_id: str
    kind: str
    target: dict[str, Any]
    before: dict[str, Any]
    proposed: dict[str, Any]


class Applier:
    kind: ClassVar[str]
    label: ClassVar[str]
    object_type: ClassVar[str]
    undo_capability: ClassVar[str] = "full"
    undo_note: ClassVar[str] = "Kan angres fra endringsloggen så lenge innholdet ikke er endret av andre etterpå."

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        raise NotImplementedError

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        raise NotImplementedError

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        raise AppError("undo_not_possible", status=409)

    def validate(self, change: ChangeData) -> None:
        return None

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return state_fingerprint(before) != state_fingerprint({k: current.get(k) for k in before})


# ---------------------------------------------------------------------------- HTML content


class _HtmlField(Applier):
    field: ClassVar[str]

    def validate(self, change: ChangeData) -> None:
        if not isinstance(change.proposed.get(self.field), str):
            raise AppError("validation_error", detail=f"Mangler {self.field}")
        if len(change.proposed[self.field].encode("utf-8")) > 500_000:
            raise AppError("validation_error", detail="Innholdet er større enn Canvas tillater (500 kB)")


class PageBody(_HtmlField):
    kind = "page.update_body"
    label = "Oppdater sideinnhold"
    object_type = "page"
    field = "body"

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        page = await api.get_page(change.course_id, change.target["object_id"])
        return {"body": page.get("body") or "", "title": page.get("title"), "updated_at": page.get("updated_at"),
                "page_id": page.get("page_id")}

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_page(change.course_id, change.target["object_id"], {"body": change.proposed["body"]},
                              permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_page(change.course_id, change.target["object_id"], {"body": before["body"]}, permit=permit)
        return await self.current(api, change)


class AssignmentDescription(_HtmlField):
    kind = "assignment.update_description"
    label = "Oppdater oppgavetekst"
    object_type = "assignment"
    field = "description"

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        data = await api.get_assignment(change.course_id, change.target["object_id"])
        return {"description": data.get("description") or "", "updated_at": data.get("updated_at")}

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_assignment(change.course_id, change.target["object_id"],
                                    {"description": change.proposed["description"]}, permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_assignment(change.course_id, change.target["object_id"],
                                    {"description": before["description"]}, permit=permit)
        return await self.current(api, change)


class DiscussionMessage(_HtmlField):
    kind = "discussion.update_message"
    label = "Oppdater diskusjonstekst"
    object_type = "discussion"
    field = "message"

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        data = await api.get_discussion(change.course_id, change.target["object_id"])
        return {"message": data.get("message") or "", "updated_at": data.get("updated_at")}

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_discussion(change.course_id, change.target["object_id"],
                                    {"message": change.proposed["message"]}, permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_discussion(change.course_id, change.target["object_id"], {"message": before["message"]},
                                    permit=permit)
        return await self.current(api, change)


class QuizDescription(_HtmlField):
    kind = "quiz.update_description"
    label = "Oppdater quizbeskrivelse"
    object_type = "quiz"
    field = "description"

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        data = await api.get_quiz(change.course_id, change.target["object_id"])
        return {"description": data.get("description") or ""}

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_quiz(change.course_id, change.target["object_id"],
                              {"description": change.proposed["description"]}, permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_quiz(change.course_id, change.target["object_id"], {"description": before["description"]},
                              permit=permit)
        return await self.current(api, change)


class SyllabusBody(_HtmlField):
    kind = "syllabus.update_body"
    label = "Oppdater emneplan (syllabus)"
    object_type = "syllabus"
    field = "syllabus_body"

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        data = await api.get_course(change.course_id, include=("syllabus_body",))
        return {"syllabus_body": data.get("syllabus_body") or ""}

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_course(change.course_id, {"syllabus_body": change.proposed["syllabus_body"]}, permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_course(change.course_id, {"syllabus_body": before["syllabus_body"]}, permit=permit)
        return await self.current(api, change)


HTML_KIND_BY_OBJECT = {"page": PageBody, "assignment": AssignmentDescription, "discussion": DiscussionMessage,
                       "quiz": QuizDescription, "syllabus": SyllabusBody}


# ---------------------------------------------------------------------------- pages / front page


class PageCreate(Applier):
    kind = "page.create"
    label = "Opprett ny side"
    object_type = "page"
    undo_note = "Kan angres ved å slette siden EmneKlar opprettet, så lenge den ikke er endret etterpå."

    def validate(self, change: ChangeData) -> None:
        if not change.proposed.get("title") or not isinstance(change.proposed.get("body"), str):
            raise AppError("validation_error", detail="Siden må ha tittel og innhold")

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        return {}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return False

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        fields = {k: change.proposed[k] for k in ("title", "body", "published", "front_page") if k in change.proposed}
        fields.setdefault("published", False)
        page = await api.create_page(change.course_id, fields, permit=permit)
        return {"url": page.get("url"), "page_id": page.get("page_id"), "title": page.get("title"),
                "body": page.get("body"), "published": page.get("published"), "html_url": page.get("html_url")}

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        after = change.proposed.get("_created") or {}
        url = after.get("url")
        if not url:
            raise AppError("undo_not_possible", status=409)
        page = await api.get_page(change.course_id, url)
        if page.get("front_page"):
            raise AppError("undo_conflict", status=409, detail="Siden er nå forside og kan ikke slettes")
        await api.delete_page(change.course_id, url, permit=permit)
        return {"deleted": url}


class FrontPageReplace(_HtmlField):
    kind = "front_page.replace"
    label = "Erstatt innholdet på forsiden"
    object_type = "front_page"
    field = "body"
    undo_note = "Forrige innhold er sikkerhetskopiert og kan gjenopprettes fra endringsloggen."

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        page = await api.get_front_page(change.course_id)
        if page is None:
            raise AppError("not_found", status=404, detail="Emnet har ingen forside")
        return {"body": page.get("body") or "", "title": page.get("title"), "url": page.get("url")}

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        current = await self.current(api, change)
        await api.update_page(change.course_id, current["url"], {"body": change.proposed["body"]}, permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        current = await self.current(api, change)
        await api.update_page(change.course_id, current["url"], {"body": before["body"]}, permit=permit)
        return await self.current(api, change)


class FrontPageSet(Applier):
    kind = "front_page.set"
    label = "Gjør siden til emnets forside"
    object_type = "page"
    undo_capability = "partial"
    undo_note = ("Angring gjør den tidligere siden til forside igjen og gjenoppretter startsiden for emnet. "
                 "Publiseringsstatus på siden endres ikke tilbake automatisk.")

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        front = await api.get_front_page(change.course_id)
        course = await api.get_course(change.course_id, include=())
        return {"front_page_url": front.get("url") if front else None, "default_view": course.get("default_view")}

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        url = change.target["object_id"]
        await api.update_page(change.course_id, url, {"published": True, "front_page": True}, permit=permit)
        if change.proposed.get("default_view") == "wiki":
            await api.update_course(change.course_id, {"default_view": "wiki"}, permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        previous = before.get("front_page_url")
        if previous:
            await api.update_page(change.course_id, previous, {"front_page": True, "published": True}, permit=permit)
        if before.get("default_view") and before.get("default_view") != "wiki":
            await api.update_course(change.course_id, {"default_view": before["default_view"]}, permit=permit)
        return await self.current(api, change)


# ---------------------------------------------------------------------------- modules


class ModuleItemUpdate(Applier):
    kind = "module_item.update"
    label = "Endre modulelement"
    object_type = "module_item"
    FIELDS = ("module_id", "position", "title", "indent", "completion_requirement")

    def validate(self, change: ChangeData) -> None:
        unknown = set(change.proposed) - set(self.FIELDS)
        if unknown or not change.proposed:
            raise AppError("validation_error", detail=f"Ugyldige felt: {sorted(unknown)}")
        requirement = change.proposed.get("completion_requirement")
        if requirement:
            from emneklar.core.canvas.requirements import validate_requirement

            validate_requirement(str(change.target.get("item_type")), requirement)

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        module_id = change.target.get("module_id")
        try:
            item = await api.get_module_item(change.course_id, module_id, change.target["object_id"])
        except CanvasError as exc:
            if exc.code != "canvas_not_found" or "module_id" not in change.proposed:
                raise
            # Already moved? Look in the proposed module.
            item = await api.get_module_item(change.course_id, str(change.proposed["module_id"]),
                                             change.target["object_id"])
        requirement = item.get("completion_requirement") or None
        if requirement:
            requirement = {k: v for k, v in requirement.items() if k in ("type", "min_score")}
        return {"module_id": str(item.get("module_id") or module_id), "position": item.get("position"),
                "title": item.get("title"), "indent": item.get("indent"), "completion_requirement": requirement}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        keys = [k for k in before if k in self.FIELDS]
        return any(before.get(k) != current.get(k) for k in keys)

    @staticmethod
    def _payload(values: dict[str, Any]) -> dict[str, Any]:
        payload = dict(values)
        if "completion_requirement" in payload and not payload["completion_requirement"]:
            payload["completion_requirement"] = {}  # Canvas removes a requirement on an empty object
        return payload

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_module_item(change.course_id, change.target["module_id"], change.target["object_id"],
                                     self._payload(change.proposed), permit=permit)
        change.target = {**change.target, "module_id": str(change.proposed.get("module_id") or change.target["module_id"])}
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        current_module = str(change.proposed.get("module_id") or change.target["module_id"])
        restore = {k: before.get(k) for k in change.proposed}
        await api.update_module_item(change.course_id, current_module, change.target["object_id"],
                                     self._payload(restore), permit=permit)
        change.target = {**change.target, "module_id": str(restore.get("module_id") or current_module)}
        return await self.current(api, change)


class ModuleUpdate(Applier):
    kind = "module.update"
    label = "Endre modulinnstillinger"
    object_type = "module"
    FIELDS = ("name", "position", "require_sequential_progress", "requirement_type")

    def validate(self, change: ChangeData) -> None:
        unknown = set(change.proposed) - set(self.FIELDS)
        if unknown or not change.proposed:
            raise AppError("validation_error", detail=f"Ugyldige felt: {sorted(unknown)}")
        if "requirement_type" in change.proposed and change.proposed["requirement_type"] not in ("all", "one"):
            raise AppError("validation_error", detail="requirement_type må være all eller one")

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        module = await api.get_module(change.course_id, change.target["object_id"])
        return {k: module.get(k) for k in self.FIELDS}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return any(before.get(k) != current.get(k) for k in before if k in self.FIELDS)

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_module(change.course_id, change.target["object_id"], dict(change.proposed), permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_module(change.course_id, change.target["object_id"],
                                {k: before.get(k) for k in change.proposed}, permit=permit)
        return await self.current(api, change)


class ModuleItemCreate(Applier):
    kind = "module_item.create"
    label = "Legg til modulelement"
    object_type = "module_item"
    undo_note = "Kan angres ved å fjerne elementet fra modulen (innholdet selv slettes ikke)."

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        return {}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return False

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        item = await api.create_module_item(change.course_id, change.target["module_id"], dict(change.proposed),
                                            permit=permit)
        return {"item_id": str(item.get("id")), "module_id": change.target["module_id"], "title": item.get("title")}

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        created = change.proposed.get("_created") or {}
        if not created.get("item_id"):
            raise AppError("undo_not_possible", status=409)
        await api.delete_module_item(change.course_id, created["module_id"], created["item_id"], permit=permit)
        return {"removed": created["item_id"]}


# ---------------------------------------------------------------------------- course


class CourseSettings(Applier):
    kind = "course.update_settings"
    label = "Endre emneinnstillinger"
    object_type = "course"

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        settings = await api.course_settings(change.course_id)
        return {k: settings.get(k) for k in change.proposed}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return any(before.get(k) != current.get(k) for k in before)

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_course_settings(change.course_id, dict(change.proposed), permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_course_settings(change.course_id, dict(before), permit=permit)
        return await self.current(api, change)


class CourseUpdate(Applier):
    kind = "course.update"
    label = "Endre emneegenskaper"
    object_type = "course"
    FIELDS = ("default_view",)

    def validate(self, change: ChangeData) -> None:
        if set(change.proposed) - set(self.FIELDS):
            raise AppError("validation_error", detail="Bare startside kan endres her")
        if change.proposed.get("default_view") not in (None, "feed", "wiki", "modules", "assignments", "syllabus"):
            raise AppError("validation_error", detail="Ugyldig startside")

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        course = await api.get_course(change.course_id, include=())
        return {k: course.get(k) for k in self.FIELDS}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return any(before.get(k) != current.get(k) for k in before)

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        await api.update_course(change.course_id, dict(change.proposed), permit=permit)
        return await self.current(api, change)

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        await api.update_course(change.course_id, dict(before), permit=permit)
        return await self.current(api, change)


# ---------------------------------------------------------------------------- blueprint


class BlueprintRestrict(Applier):
    kind = "blueprint.restrict"
    label = "Endre Blueprint-låsing"
    object_type = "course"
    undo_capability = "partial"
    undo_note = ("Angring setter låsestatus tilbake for elementer der tidligere status var kjent. "
                 "Innhold i tilknyttede emner påvirkes først ved neste synkronisering.")
    CONTENT_TYPES = ("assignment", "attachment", "discussion_topic", "external_tool", "lti-quiz", "quiz", "wiki_page")

    def validate(self, change: ChangeData) -> None:
        items = change.proposed.get("items") or []
        if not items:
            raise AppError("validation_error", detail="Ingen elementer valgt")
        for item in items:
            if item.get("content_type") not in self.CONTENT_TYPES or not str(item.get("content_id", "")).isdigit():
                raise AppError("validation_error", detail="Ugyldig innholdstype for Blueprint-låsing")

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        return {"items": change.before.get("items", [])}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return False

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        restricted = bool(change.proposed.get("restricted"))
        restrictions = change.proposed.get("restrictions") if restricted else None
        done = []
        for item in change.proposed["items"]:
            await api.restrict_blueprint_item(change.course_id, item["content_type"], str(item["content_id"]),
                                              restricted, restrictions, permit=permit)
            done.append({**item, "restricted": restricted})
        return {"items": done}

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        restored = []
        for item in before.get("items") or []:
            if item.get("restricted") is None:
                continue
            await api.restrict_blueprint_item(change.course_id, item["content_type"], str(item["content_id"]),
                                              bool(item["restricted"]), item.get("restrictions"), permit=permit)
            restored.append(item)
        return {"items": restored}


APPLIERS: dict[str, Applier] = {a.kind: a for a in (
    PageBody(), AssignmentDescription(), DiscussionMessage(), QuizDescription(), SyllabusBody(), PageCreate(),
    FrontPageReplace(), FrontPageSet(), ModuleItemUpdate(), ModuleUpdate(), ModuleItemCreate(), CourseSettings(),
    CourseUpdate(), BlueprintRestrict(),
)}


def register(applier: Applier) -> None:
    """Features with their own change kinds (e.g. quiz creation) register here."""
    APPLIERS[applier.kind] = applier


def get_applier(kind: str) -> Applier:
    applier = APPLIERS.get(kind)
    if applier is None:
        raise AppError("validation_error", detail=f"Ukjent endringstype: {kind}")
    return applier
