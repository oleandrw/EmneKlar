"""Typed access to the Canvas REST API endpoints EmneKlar uses.

All endpoint knowledge lives here (see docs/CANVAS_API.md for the verified
parameters). Read methods are free to call; every write method requires a
:class:`WritePermit` and is therefore only reachable through the change engine.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

from emneklar.core.canvas.client import CanvasClient, CanvasError, WritePermit

log = logging.getLogger(__name__)

TEACHING_ENROLLMENTS = {"teacher", "ta", "designer", "teacherenrollment", "taenrollment", "designerenrollment"}

# Permission keys checked during setup and before feature use (granular Canvas permissions).
PERMISSION_KEYS = [
    "manage",
    "update",
    "read_as_admin",
    "manage_wiki_update",
    "manage_wiki_create",
    "manage_course_content_edit",
    "manage_course_content_add",
    "manage_assignments_edit",
    "manage_assignments_add",
    "manage_files_edit",
    "update_course_details",
]


#: ``usage_rights[use_justification]`` values (canvas-lms UsageRightsController, checked 4.11.2026).
USE_JUSTIFICATIONS = ("own_copyright", "used_by_permission", "fair_use", "public_domain", "creative_commons")


def _page_ref(url_or_id: str) -> str:
    return quote(str(url_or_id), safe="")


class CanvasAPI:
    def __init__(self, client: CanvasClient) -> None:
        self.client = client

    # -- identity, courses, permissions ----------------------------------------------------

    async def users_self(self) -> dict[str, Any]:
        return await self.client.get_json("/api/v1/users/self")

    async def list_courses(self, *, include_completed: bool = False) -> list[dict[str, Any]]:
        params: list[tuple[str, Any]] = [("include[]", "term"), ("state[]", "available"), ("state[]", "unpublished")]
        if include_completed:
            params.append(("state[]", "completed"))
        courses = await self.client.get_paginated("/api/v1/courses", params)
        result = []
        for course in courses:
            if not isinstance(course, dict) or course.get("access_restricted_by_date"):
                continue
            roles = {str(e.get("type") or e.get("role") or "").lower() for e in course.get("enrollments") or []}
            course["_teaching_roles"] = sorted(r for r in roles if r in TEACHING_ENROLLMENTS)
            if course["_teaching_roles"]:
                result.append(course)
        return result

    async def get_course(self, course_id: str, *, include: tuple[str, ...] = ("term",)) -> dict[str, Any]:
        params = [("include[]", i) for i in include]
        return await self.client.get_json(f"/api/v1/courses/{course_id}", params)

    async def course_settings(self, course_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/courses/{course_id}/settings")

    async def course_permissions(self, course_id: str, keys: list[str] | None = None) -> dict[str, bool]:
        params = [("permissions[]", k) for k in (keys or PERMISSION_KEYS)]
        data = await self.client.get_json(f"/api/v1/courses/{course_id}/permissions", params)
        return {str(k): bool(v) for k, v in (data or {}).items()}

    async def course_tabs(self, course_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/tabs")

    # -- content ---------------------------------------------------------------------------

    async def list_pages(self, course_id: str, *, include_body: bool = True) -> list[dict[str, Any]]:
        params: list[tuple[str, Any]] = [("sort", "title")]
        if include_body:
            params.append(("include[]", "body"))
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/pages", params)

    async def get_page(self, course_id: str, url_or_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/courses/{course_id}/pages/{_page_ref(url_or_id)}")

    async def get_front_page(self, course_id: str) -> dict[str, Any] | None:
        try:
            return await self.client.get_json(f"/api/v1/courses/{course_id}/front_page")
        except CanvasError as exc:
            if exc.code == "canvas_not_found":
                return None
            raise

    async def page_revisions(self, course_id: str, url_or_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/pages/{_page_ref(url_or_id)}/revisions")

    async def list_modules(self, course_id: str) -> list[dict[str, Any]]:
        modules = await self.client.get_paginated(
            f"/api/v1/courses/{course_id}/modules", [("include[]", "items"), ("include[]", "content_details")]
        )
        # Canvas only inlines items for modules with ≤ 100 items.
        missing = [m for m in modules if m.get("items") is None and int(m.get("items_count") or 0) > 0]
        if missing:
            results = await asyncio.gather(*(self.list_module_items(course_id, str(m["id"])) for m in missing))
            for module, items in zip(missing, results, strict=True):
                module["items"] = items
        for module in modules:
            module.setdefault("items", [])
        return modules

    async def list_module_items(self, course_id: str, module_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(
            f"/api/v1/courses/{course_id}/modules/{module_id}/items", [("include[]", "content_details")]
        )

    async def get_module_item(self, course_id: str, module_id: str, item_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/courses/{course_id}/modules/{module_id}/items/{item_id}")

    async def get_module(self, course_id: str, module_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/courses/{course_id}/modules/{module_id}")

    async def list_assignments(self, course_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/assignments", [("order_by", "position")])

    async def get_assignment(self, course_id: str, assignment_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/courses/{course_id}/assignments/{assignment_id}")

    async def list_discussions(self, course_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/discussion_topics",
                                               [("order_by", "position")])

    async def get_discussion(self, course_id: str, topic_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/courses/{course_id}/discussion_topics/{topic_id}")

    async def list_files(self, course_id: str, *, include_user: bool = False) -> list[dict[str, Any]]:
        params: list[tuple[str, Any]] = [("sort", "name")]
        if include_user:
            params.append(("include[]", "user"))  # uploader – Emne-RAG only indexes files uploaded by teachers
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/files", params)

    async def list_teaching_user_ids(self, course_id: str) -> set[str]:
        """Ids of the course's teachers, TAs and designers (``GET …/users?enrollment_type[]=…``).

        Only the ids are used – to tell teacher-written discussion topics and files from student content.
        """
        users = await self.client.get_paginated(
            f"/api/v1/courses/{course_id}/users",
            [("enrollment_type[]", "teacher"), ("enrollment_type[]", "ta"), ("enrollment_type[]", "designer")])
        return {str(u.get("id")) for u in users if isinstance(u, dict) and u.get("id") is not None}

    async def get_file(self, file_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/files/{file_id}")

    async def file_bytes(self, url: str, *, max_bytes: int) -> tuple[bytes, str | None]:
        """Download a Canvas-hosted file referenced in content (…/files/:id/preview etc.) via the Files API."""
        from emneklar.core.canvas.html import canvas_ref

        host = self.client.base_url.split("://", 1)[-1].split("/")[0].split(":")[0]
        ref = canvas_ref(url, host)
        match = None if ref else re.match(r"^(?:https?://[^/]+)?/files/(\d+)", url)
        file_id = ref.ident if ref and ref.kind == "files" and ref.ident and ref.ident.isdigit() else (
            match.group(1) if match else None)
        if file_id:
            meta = await self.get_file(file_id)
            target = str(meta.get("url") or "")
            if not target:
                raise CanvasError("canvas_not_found", status=404, detail="Filen har ingen nedlastingsadresse")
            return await self.client.fetch_bytes(target, max_bytes=max_bytes)
        return await self.client.fetch_bytes(url, max_bytes=max_bytes)

    async def list_media_objects(self, course_id: str, *, include_sources: bool = False) -> list[dict[str, Any]]:
        params = [] if include_sources else [("exclude[]", "sources")]
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/media_objects", params)

    async def media_attachment_tracks(self, attachment_id: str, *, include_content: bool = False) -> list[dict[str, Any]]:
        """Caption tracks of an uploaded media file. ``include[]=webvtt_content`` adds the text as WebVTT."""
        params = [("include[]", "webvtt_content")] if include_content else None
        data = await self.client.get_json(f"/api/v1/media_attachments/{attachment_id}/media_tracks", params)
        return data if isinstance(data, list) else []

    async def media_track_text(self, url: str) -> str:
        """The WebVTT text behind a ``media_tracks[].url`` (``/media_objects/:id/media_tracks/:track_id``)."""
        response = await self.client.request("GET", url)
        return response.text

    # -- classic quizzes -----------------------------------------------------------------------

    async def list_quizzes(self, course_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/quizzes")

    async def get_quiz(self, course_id: str, quiz_id: str) -> dict[str, Any]:
        return await self.client.get_json(f"/api/v1/courses/{course_id}/quizzes/{quiz_id}")

    async def list_quiz_questions(self, course_id: str, quiz_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/questions")

    async def list_quiz_groups(self, course_id: str, quiz_id: str) -> list[dict[str, Any]]:
        try:
            data = await self.client.get_json(f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/groups")
        except CanvasError as exc:
            if exc.code == "canvas_not_found":
                return []
            raise
        if isinstance(data, dict):
            groups = data.get("quiz_groups") or []
            return groups if isinstance(groups, list) else []
        return data if isinstance(data, list) else []

    # -- blueprint ---------------------------------------------------------------------------

    async def blueprint_template(self, course_id: str) -> dict[str, Any] | None:
        try:
            return await self.client.get_json(f"/api/v1/courses/{course_id}/blueprint_templates/default")
        except CanvasError as exc:
            if exc.code in ("canvas_not_found", "canvas_forbidden"):
                return None
            raise

    async def blueprint_subscriptions(self, course_id: str) -> list[dict[str, Any]]:
        try:
            data = await self.client.get_json(f"/api/v1/courses/{course_id}/blueprint_subscriptions")
        except CanvasError as exc:
            if exc.code in ("canvas_not_found", "canvas_forbidden"):
                return []
            raise
        return data if isinstance(data, list) else []

    async def blueprint_unsynced_changes(self, course_id: str) -> list[dict[str, Any]]:
        return await self.client.get_paginated(
            f"/api/v1/courses/{course_id}/blueprint_templates/default/unsynced_changes")

    # -- writes (WritePermit required) ----------------------------------------------------------

    async def update_page(self, course_id: str, url_or_id: str, fields: dict[str, Any], *,
                          permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}/pages/{_page_ref(url_or_id)}",
                                            json={"wiki_page": fields}, permit=permit)

    async def create_page(self, course_id: str, fields: dict[str, Any], *, permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("POST", f"/api/v1/courses/{course_id}/pages",
                                            json={"wiki_page": fields}, permit=permit)

    async def delete_page(self, course_id: str, url_or_id: str, *, permit: WritePermit) -> Any:
        return await self.client.write_json("DELETE", f"/api/v1/courses/{course_id}/pages/{_page_ref(url_or_id)}",
                                            permit=permit)

    async def update_assignment(self, course_id: str, assignment_id: str, fields: dict[str, Any], *,
                                permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}/assignments/{assignment_id}",
                                            json={"assignment": fields}, permit=permit)

    async def update_discussion(self, course_id: str, topic_id: str, fields: dict[str, Any], *,
                                permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}/discussion_topics/{topic_id}",
                                            json=fields, permit=permit)

    async def update_course(self, course_id: str, fields: dict[str, Any], *, permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}", json={"course": fields},
                                            permit=permit)

    async def update_course_settings(self, course_id: str, fields: dict[str, Any], *,
                                     permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}/settings", json=fields,
                                            permit=permit)

    async def update_module(self, course_id: str, module_id: str, fields: dict[str, Any], *,
                            permit: WritePermit) -> dict[str, Any]:
        if "published" in fields:
            # Publishing a module publishes every item in it – EmneKlar never does that implicitly.
            raise CanvasError("unsupported", status=500, detail="Modulens publiseringsstatus endres ikke av EmneKlar")
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}/modules/{module_id}",
                                            json={"module": fields}, permit=permit)

    async def update_module_item(self, course_id: str, module_id: str, item_id: str, fields: dict[str, Any], *,
                                 permit: WritePermit) -> dict[str, Any]:
        if "published" in fields:
            raise CanvasError("unsupported", status=500, detail="Publiseringsstatus endres ikke via modulelementer")
        return await self.client.write_json(
            "PUT", f"/api/v1/courses/{course_id}/modules/{module_id}/items/{item_id}",
            json={"module_item": fields}, permit=permit)

    async def create_module_item(self, course_id: str, module_id: str, fields: dict[str, Any], *,
                                 permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("POST", f"/api/v1/courses/{course_id}/modules/{module_id}/items",
                                            json={"module_item": fields}, permit=permit)

    async def delete_module_item(self, course_id: str, module_id: str, item_id: str, *,
                                 permit: WritePermit) -> Any:
        return await self.client.write_json(
            "DELETE", f"/api/v1/courses/{course_id}/modules/{module_id}/items/{item_id}", permit=permit)

    async def create_quiz(self, course_id: str, fields: dict[str, Any], *, permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("POST", f"/api/v1/courses/{course_id}/quizzes", json={"quiz": fields},
                                            permit=permit)

    async def update_quiz(self, course_id: str, quiz_id: str, fields: dict[str, Any], *,
                          permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}/quizzes/{quiz_id}",
                                            json={"quiz": fields}, permit=permit)

    async def delete_quiz(self, course_id: str, quiz_id: str, *, permit: WritePermit) -> Any:
        return await self.client.write_json("DELETE", f"/api/v1/courses/{course_id}/quizzes/{quiz_id}", permit=permit)

    async def create_quiz_group(self, course_id: str, quiz_id: str, group: dict[str, Any], *,
                                permit: WritePermit) -> dict[str, Any]:
        data = await self.client.write_json("POST", f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/groups",
                                            json={"quiz_groups": [group]}, permit=permit)
        if isinstance(data, dict) and isinstance(data.get("quiz_groups"), list) and data["quiz_groups"]:
            return dict(data["quiz_groups"][0])
        return data if isinstance(data, dict) else {}

    async def create_quiz_question(self, course_id: str, quiz_id: str, question: dict[str, Any], *,
                                   permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json("POST", f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/questions",
                                            json={"question": question}, permit=permit)

    async def update_quiz_question(self, course_id: str, quiz_id: str, question_id: str, question: dict[str, Any],
                                   *, permit: WritePermit) -> dict[str, Any]:
        return await self.client.write_json(
            "PUT", f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/questions/{question_id}",
            json={"question": question}, permit=permit)

    async def upload_course_file(self, course_id: str, *, name: str, data: bytes, content_type: str,
                                folder_path: str, permit: WritePermit) -> dict[str, Any]:
        """Upload a file to the course's files in three steps (Canvas «File Uploads», docs/CANVAS_API.md):

        1. ``POST /courses/:id/files`` with name, size, content type, folder path → ``upload_url`` + ``upload_params``;
        2. multipart POST of the bytes to ``upload_url`` without the token (:meth:`CanvasClient.upload_to`);
        3. confirm: a 3xx ``Location`` is fetched with the token (GET), and 201 ``Location`` returns the File JSON.

        ``on_duplicate=rename`` – EmneKlar never overwrites a file in the course.
        """
        preflight = await self.client.write_json(
            "POST", f"/api/v1/courses/{course_id}/files", permit=permit,
            json={"name": name, "size": len(data), "content_type": content_type, "parent_folder_path": folder_path,
                  "on_duplicate": "rename"})
        if not isinstance(preflight, dict) or not preflight.get("upload_url"):
            raise CanvasError("canvas_error", detail="Canvas ga ingen opplastingsadresse")
        status, location, body = await self.client.upload_to(
            str(preflight["upload_url"]), dict(preflight.get("upload_params") or {}),
            file_field=str(preflight.get("file_param") or "file"), filename=name, data=data,
            content_type=content_type, permit=permit)
        if isinstance(body, dict) and body.get("id") and not location:
            return body
        if not location:
            raise CanvasError("canvas_error", detail=f"Opplastingen ble ikke bekreftet (HTTP {status})")
        if not self.client.is_canvas_origin(location):
            raise CanvasError("canvas_error", detail="Bekreftelsesadressen pekte til en annen vert enn Canvas")
        confirmed = await self.client.get_json(location)
        if not isinstance(confirmed, dict) or not confirmed.get("id"):
            raise CanvasError("canvas_error", detail="Canvas bekreftet ikke filen")
        return confirmed

    async def find_course_file(self, course_id: str, name: str) -> list[dict[str, Any]]:
        """Files in the course whose name matches exactly (``search_term`` needs at least 2 characters)."""
        rows = await self.client.get_paginated(f"/api/v1/courses/{course_id}/files", [("search_term", name)],
                                               max_items=200)
        return [r for r in rows if isinstance(r, dict) and name in (r.get("display_name"), r.get("filename"))]

    async def set_usage_rights(self, course_id: str, file_ids: list[str], *, use_justification: str,
                               legal_copyright: str | None, publish: bool, permit: WritePermit) -> dict[str, Any]:
        """``PUT /courses/:id/usage_rights`` – needed when the course requires copyright information: new files are
        locked (invisible to students) until it is set."""
        if use_justification not in USE_JUSTIFICATIONS:
            raise CanvasError("validation_error", status=400, detail="Ugyldig opphavsrettsgrunnlag")
        body: dict[str, Any] = {"file_ids": file_ids, "publish": publish,
                                "usage_rights": {"use_justification": use_justification}}
        if legal_copyright:
            body["usage_rights"]["legal_copyright"] = legal_copyright
        return await self.client.write_json("PUT", f"/api/v1/courses/{course_id}/usage_rights", json=body,
                                            permit=permit)

    async def restrict_blueprint_item(self, course_id: str, content_type: str, content_id: str, restricted: bool,
                                      restrictions: dict[str, bool] | None, *, permit: WritePermit) -> Any:
        body: dict[str, Any] = {"content_type": content_type, "content_id": content_id, "restricted": restricted}
        if restrictions is not None:
            body["restrictions"] = restrictions
        return await self.client.write_json(
            "PUT", f"/api/v1/courses/{course_id}/blueprint_templates/default/restrict_item", json=body, permit=permit)


# -- helpers shared by features ------------------------------------------------------------------


def answer_is_correct(answer: dict[str, Any]) -> bool:
    """Classic Quiz answer key: weight 100 = correct (read shape uses `weight`, write shape `answer_weight`)."""
    weight = answer.get("weight", answer.get("answer_weight"))
    try:
        return float(weight or 0) >= 100
    except (TypeError, ValueError):
        return False


def answer_text(answer: dict[str, Any]) -> str:
    from emneklar.core.canvas.html import norm_text, parse_html

    html = answer.get("html") or answer.get("answer_html")
    if html:
        return norm_text(parse_html(str(html)).get_text(" "))
    return norm_text(str(answer.get("text") or answer.get("answer_text") or ""))


def is_block_editor_page(page: dict[str, Any]) -> bool:
    return str(page.get("editor") or "").lower() == "block_editor" or (
        page.get("body") is None and page.get("block_editor_attributes") is not None
    )
