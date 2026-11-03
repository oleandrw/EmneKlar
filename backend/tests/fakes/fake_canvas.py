"""A fake Canvas LMS for automated tests and end-to-end tests.

It implements the subset of the Canvas REST API that EmneKlar uses, with the
response shapes documented in docs/CANVAS_API.md (Link-header pagination,
`weight`-based quiz answer keys, `{"quiz_groups": […]}` envelopes, items only
inlined for modules with ≤ 100 items, block-editor pages without HTML body …).

Used in-process (httpx.ASGITransport) by pytest and served with uvicorn by the
Playwright tests. Never shipped to users.
"""

from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from tests.fakes.documents import minimal_docx, minimal_pdf, minimal_pptx

TOKEN = "7~fakeCanvasTokenForTests1234567890abcdefghij"
COURSE_ID = "101"
BLUEPRINT_COURSE_ID = "102"
_ids = itertools.count(5000)


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_id() -> str:
    return str(next(_ids))


@dataclass
class CourseData:
    course: dict[str, Any]
    settings: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, bool] = field(default_factory=dict)
    pages: dict[str, dict[str, Any]] = field(default_factory=dict)  # by url slug
    revisions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    modules: list[dict[str, Any]] = field(default_factory=list)
    assignments: dict[str, dict[str, Any]] = field(default_factory=dict)
    discussions: dict[str, dict[str, Any]] = field(default_factory=dict)
    quizzes: dict[str, dict[str, Any]] = field(default_factory=dict)
    questions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    groups: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    media_objects: list[dict[str, Any]] = field(default_factory=list)
    users: list[dict[str, Any]] = field(default_factory=list)  # {id, name, enrollment: teacher|ta|designer|student}
    tabs: list[dict[str, Any]] = field(default_factory=list)
    blueprint_template: dict[str, Any] | None = None
    subscriptions: list[dict[str, Any]] = field(default_factory=list)
    restrictions: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


@dataclass
class FakeCanvasState:
    token: str = TOKEN
    user: dict[str, Any] = field(default_factory=lambda: {
        "id": "42", "name": "Kari Lærer", "short_name": "Kari", "sortable_name": "Lærer, Kari", "locale": "nb"})
    courses: dict[str, CourseData] = field(default_factory=dict)
    file_bytes: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    attachment_tracks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    writes: list[tuple[str, str, Any]] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)
    rate_limit_failures: int = 0
    rate_limit_status: int = 429
    fail: dict[str, int] = field(default_factory=dict)  # path substring -> status
    ignored_fields: set[str] = field(default_factory=set)  # fields a PUT accepts without storing (tests)
    origin: str = "http://canvas.test"


# ---------------------------------------------------------------------------------------- seed


def _page(slug: str, title: str, body: str | None, *, published: bool = True, front: bool = False,
          editor: str = "rce") -> dict[str, Any]:
    return {"page_id": next_id(), "url": slug, "title": title, "body": body, "published": published,
            "front_page": front, "editing_roles": "teachers", "created_at": "2026-08-01T10:00:00Z",
            "updated_at": "2026-08-20T10:00:00Z", "editor": editor, "html_url": f"/courses/101/pages/{slug}"}


def seed_state(origin: str = "http://canvas.test") -> FakeCanvasState:
    state = FakeCanvasState(origin=origin)
    c = CourseData(course={
        "id": COURSE_ID, "name": "Digital kompetanse for lærere", "course_code": "LA101IKT14-1 26H",
        "workflow_state": "available", "default_view": "modules", "blueprint": False, "is_public": False,
        "term": {"id": "7", "name": "Høst 2026"},
        "enrollments": [{"type": "teacher", "role": "TeacherEnrollment", "enrollment_state": "active"}],
        "syllabus_body": "<p>Emneplanen ligger i <a href=\"/courses/101/files/9001\">Pensumliste.pdf</a>.</p>",
    })
    c.settings = {
        "allow_student_discussion_topics": True, "allow_student_forum_attachments": True,
        "allow_student_discussion_editing": True, "allow_student_organized_groups": True,
        "hide_final_grades": False, "hide_distribution_graphs": False, "lock_all_announcements": False,
        "usage_rights_required": False, "restrict_student_past_view": False, "restrict_student_future_view": False,
        "show_announcements_on_home_page": False, "home_page_announcement_limit": 3,
        "syllabus_course_summary": True, "default_due_time": "23:59:59", "conditional_release": False,
    }
    c.permissions = dict.fromkeys(("manage", "update", "read_as_admin", "manage_wiki_update", "manage_wiki_create", "manage_course_content_edit", "manage_course_content_add", "manage_assignments_edit", "manage_assignments_add", "manage_files_edit", "update_course_details"), True)
    pages = [
        _page("velkommen", "Velkommen til emnet",
              "<h1>Velkommen</h1><p>Her finner du alt om emnet. <a href=\"https://www.example.org/plan\">Klikk her</a>"
              "</p><p><strong>Praktisk informasjon</strong></p><p>Undervisningen er på tirsdager.</p>"
              "<p><img src=\"/courses/101/files/9003/preview\" alt=\"IMG_2034.JPG\"></p>"),
        _page("bildeformater", "Bildeformater",
              "<h2>Hva er et bildeformat?</h2><h4>Raster og vektor</h4>"
              "<p><img src=\"/courses/101/files/9004/preview\"></p>"
              "<p><img src=\"https://cdn.example.org/diagram-farger.png\" alt=\"bilde\"></p>"
              "<p>- JPEG for foto</p><p>- PNG for grafikk</p><p>- SVG for vektor</p>"
              "<p><a href=\"/courses/101/pages/fargelaere\">Fargelære</a> og "
              "<a href=\"/courses/101/pages/finnes-ikke\">gammel side</a></p>"
              "<p><a href=\"https://www.example.org/missing\"></a></p>"),
        _page("fargelaere", "Fargelære",
              "<h2>Farger</h2><p style=\"color:#aaaaaa;background-color:#ffffff\">Lys grå tekst på hvit bakgrunn.</p>"
              "<p>Klikk på den grønne knappen til høyre for å fortsette.</p>"
              "<table><tr><td>Farge</td><td>Kode</td></tr><tr><td>Rød</td><td>#ff0000</td></tr></table>"
              "<p>THIS TEXT IS WRITTEN IN UPPERCASE LETTERS AND SHOULD BE READ</p>"),
        _page("video-og-medier", "Video og medier",
              "<h2>Introduksjonsvideo</h2>"
              "<iframe src=\"https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1\" width=\"560\" height=\"315\"></iframe>"
              "<p><iframe title=\"Forelesning 1\" data-media-id=\"m-abc123\" data-media-type=\"video\" "
              "src=\"/media_attachments_iframe/9010?type=video&amp;embedded=true\"></iframe></p>"
              "<p>This paragraph is written entirely in English so that the language detection can find it and "
              "suggest a language attribute for screen readers.</p>"),
        _page("oppsummering", "Oppsummering", "<h2>Oppsummering</h2><p>Takk for nå.</p>"),
        _page("blokkside", "Ny blokkside", None, editor="block_editor"),
        _page("forside", "Forside", "<h2>Velkommen</h2><p>Dette er forsiden.</p>", front=True),
        _page("gammelt-utkast", "Gammelt utkast", "<p>Ikke publisert.</p>", published=False),
    ]
    for p in pages:
        c.pages[p["url"]] = p
        c.revisions[p["url"]] = [{"revision_id": 1, "updated_at": p["updated_at"], "latest": True,
                                  "title": p["title"], "body": p["body"]}]
    c.assignments = {
        "301": {"id": "301", "name": "Innlevering 1: Bildebehandling", "description":
                "<p>Lever oppgaven <a href=\"https://www.example.org/oppgave\">her</a>.</p>",
                "html_url": "/courses/101/assignments/301", "published": True, "points_possible": 10,
                "due_at": "2026-09-15T21:59:00Z", "submission_types": ["online_upload"], "updated_at": "2026-08-20T10:00:00Z"},
        "302": {"id": "302", "name": "Refleksjonsnotat", "description": "<p>Skriv et refleksjonsnotat.</p>",
                "html_url": "/courses/101/assignments/302", "published": True, "points_possible": 0,
                "due_at": "2026-09-01T21:59:00Z", "submission_types": ["online_text_entry"], "updated_at": "2026-08-20T10:00:00Z"},
        "303": {"id": "303", "name": "Øvingsquiz: Bildeformater", "description": "",
                "html_url": "/courses/101/assignments/303", "published": True, "points_possible": 3,
                "submission_types": ["online_quiz"], "quiz_id": "401", "updated_at": "2026-08-20T10:00:00Z"},
    }
    c.discussions = {
        "501": {"id": "501", "title": "Presentasjonsrunde", "message": "<p>Presenter deg selv.</p>",
                "html_url": "/courses/101/discussion_topics/501", "published": True, "assignment_id": None,
                "updated_at": "2026-08-20T10:00:00Z"},
    }
    c.quizzes = {
        "401": {"id": "401", "title": "Øvingsquiz: Bildeformater", "description": "<p>Test deg selv.</p>",
                "quiz_type": "practice_quiz", "time_limit": None, "shuffle_answers": True, "hide_results": None,
                "show_correct_answers": True, "allowed_attempts": -1, "scoring_policy": "keep_highest",
                "one_question_at_a_time": False, "cant_go_back": False, "published": True, "question_count": 4,
                "points_possible": 4, "html_url": "/courses/101/quizzes/401", "assignment_id": "303",
                "updated_at": "2026-08-20T10:00:00Z"},
    }
    c.questions = {"401": [
        {"id": "601", "quiz_id": "401", "position": 1, "question_name": "Spørsmål 1", "question_type": "multiple_choice_question",
         "question_text": "<p>Hvilket format egner seg best for fotografier?</p>", "points_possible": 1, "quiz_group_id": None,
         "answers": [{"id": "1", "text": "JPEG", "html": "", "weight": 100}, {"id": "2", "text": "SVG", "html": "", "weight": 0},
                     {"id": "3", "text": "TXT", "html": "", "weight": 0}]},
        {"id": "602", "quiz_id": "401", "position": 2, "question_name": "Spørsmål 2", "question_type": "multiple_choice_question",
         "question_text": "<p>Hvilket format er vektorbasert?</p>", "points_possible": 1, "quiz_group_id": None,
         "answers": [{"id": "4", "text": "PNG", "weight": 0}, {"id": "5", "text": "GIF", "weight": 0},
                     {"id": "6", "text": "BMP", "weight": 0}]},
        {"id": "603", "quiz_id": "401", "position": 3, "question_name": "Spørsmål 3", "question_type": "true_false_question",
         "question_text": "<p>PNG støtter gjennomsiktighet.</p>", "points_possible": 1, "quiz_group_id": None,
         "answers": [{"id": "7", "text": "Sant", "weight": 100}, {"id": "8", "text": "Usant", "weight": 0}]},
        {"id": "604", "quiz_id": "401", "position": 4, "question_name": "Spørsmål 4", "question_type": "multiple_choice_question",
         "question_text": "<p>Hvilket format egner seg best for fotografier?</p>", "points_possible": 1, "quiz_group_id": None,
         "answers": [{"id": "9", "text": "JPEG", "weight": 100}, {"id": "10", "text": "Alle de ovennevnte", "weight": 100}]},
    ]}
    c.groups = {"401": []}
    c.files = {
        "9001": {"id": "9001", "display_name": "Pensumliste.pdf", "filename": "Pensumliste.pdf",
                 "content-type": "application/pdf", "size": 0, "url": f"{origin}/files/9001/download?download_frd=1",
                 "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z", "folder_id": "1"},
        "9002": {"id": "9002", "display_name": "Forelesning1.docx", "filename": "Forelesning1.docx",
                 "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size": 0,
                 "url": f"{origin}/files/9002/download?download_frd=1", "created_at": "2026-08-01T10:00:00Z",
                 "updated_at": "2026-08-01T10:00:00Z", "folder_id": "1"},
        "9005": {"id": "9005", "display_name": "Lysbilder uke 1.pptx", "filename": "Lysbilder_uke_1.pptx",
                 "content-type": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "size": 0,
                 "url": f"{origin}/files/9005/download?download_frd=1", "created_at": "2021-08-01T10:00:00Z",
                 "updated_at": "2021-08-01T10:00:00Z", "folder_id": "1"},
        "9003": {"id": "9003", "display_name": "IMG_2034.JPG", "filename": "IMG_2034.JPG", "content-type": "image/jpeg",
                 "size": 1000, "url": f"{origin}/files/9003/download?download_frd=1", "created_at": "2026-08-01T10:00:00Z",
                 "updated_at": "2026-08-01T10:00:00Z", "folder_id": "1"},
        "9004": {"id": "9004", "display_name": "raster-vektor-skjermbilde.png", "filename": "raster-vektor-skjermbilde.png",
                 "content-type": "image/png", "size": 1000, "url": f"{origin}/files/9004/download?download_frd=1",
                 "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z", "folder_id": "1"},
    }
    state.file_bytes = {
        "9001": (minimal_pdf(text=None), "application/pdf"),
        "9002": (minimal_docx(image_alt=None, title=None), c.files["9002"]["content-type"]),
        "9005": (minimal_pptx(), c.files["9005"]["content-type"]),
    }
    # 1×1 transparent PNG for image previews and AI alt-text tests.
    state.file_bytes["9004"] = (bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"), "image/png")
    for fid, (data, _) in state.file_bytes.items():
        c.files[fid]["size"] = len(data)
    c.media_objects = [
        {"media_id": "m-abc123", "title": "Forelesning 1", "media_type": "video", "media_tracks": []},
        {"media_id": "m-def456", "title": "Forelesning 2", "media_type": "video",
         "media_tracks": [{"id": "1", "kind": "subtitles", "locale": "nb", "workflow_state": "ready", "asr": True}]},
    ]
    state.attachment_tracks = {"9010": []}

    def item(item_id: str, title: str, type_: str, *, content_id: str | None = None, page_url: str | None = None,
             external_url: str | None = None, requirement: dict | None = None, published: bool = True,
             position: int = 1, indent: int = 0) -> dict[str, Any]:
        data = {"id": item_id, "title": title, "type": type_, "position": position, "indent": indent,
                "published": published, "html_url": f"/courses/101/modules/items/{item_id}",
                "completion_requirement": requirement}
        if content_id:
            data["content_id"] = content_id
        if page_url:
            data["page_url"] = page_url
        if external_url:
            data["external_url"] = external_url
        return data

    c.modules = [
        {"id": "201", "name": "Modul 1 – Introduksjon", "position": 1, "require_sequential_progress": False,
         "requirement_type": "all", "prerequisite_module_ids": [], "published": True, "unlock_at": None,
         "items": [item("1001", "Velkommen til emnet", "Page", page_url="velkommen", position=1),
                   item("1002", "Presentasjonsrunde", "Discussion", content_id="501", position=2),
                   item("1003", "Refleksjonsnotat", "Assignment", content_id="302", position=3)]},
        {"id": "202", "name": "Modul 2 – Bildebehandling", "position": 2, "require_sequential_progress": False,
         "requirement_type": "all", "prerequisite_module_ids": [], "published": True, "unlock_at": None,
         "items": [item("1010", "Bildeformater", "Page", page_url="bildeformater", position=1,
                        requirement={"type": "must_view", "completed": False}),
                   item("1011", "Innlevering 1: Bildebehandling", "Assignment", content_id="301", position=2),
                   item("1012", "Øvingsquiz: Bildeformater", "Quiz", content_id="401", position=3),
                   item("1013", "Fargelære", "Page", page_url="fargelaere", position=4)]},
        {"id": "203", "name": "modul 3: video", "position": 3, "require_sequential_progress": False,
         "requirement_type": "all", "prerequisite_module_ids": [], "published": True, "unlock_at": None,
         "items": [item("1020", "Video og medier", "Page", page_url="video-og-medier", position=1),
                   item("1021", "Pensumliste", "File", content_id="9001", position=2),
                   item("1022", "Forelesningsnotater", "File", content_id="9002", position=3),
                   item("1023", "Ekstern ressurs", "ExternalUrl", external_url="https://www.example.org/ressurs", position=4),
                   item("1024", "Lysbilder fra 2021", "File", content_id="9005", position=5)]},
    ]
    c.tabs = [{"id": "home", "label": "Startside", "hidden": False, "position": 1, "visibility": "public", "type": "internal"},
              {"id": "announcements", "label": "Kunngjøringer", "hidden": False, "position": 2, "visibility": "public", "type": "internal"},
              {"id": "outcomes", "label": "Læringsutbytter", "hidden": False, "position": 3, "visibility": "admins", "type": "internal"}]
    state.courses[COURSE_ID] = c

    bp = CourseData(course={
        "id": BLUEPRINT_COURSE_ID, "name": "Mal for digitale emner", "course_code": "MAL-DIGITAL", "workflow_state": "unpublished",
        "default_view": "wiki", "blueprint": True, "term": {"id": "1", "name": "Standardsemester"},
        "enrollments": [{"type": "teacher", "role": "TeacherEnrollment", "enrollment_state": "active"}]})
    bp.permissions = dict(c.permissions)
    bp.pages = {"mal-forside": _page("mal-forside", "Malforside", "<h2>Mal</h2>", front=True),
                "mal-ressurser": _page("mal-ressurser", "Malressurser", "<h2>Ressurser</h2>")}
    bp.assignments = {"391": {"id": "391", "name": "Malinnlevering", "description": "", "published": False,
                              "html_url": "/courses/102/assignments/391", "points_possible": 5,
                              "submission_types": ["online_upload"]}}
    bp.discussions = {"591": {"id": "591", "title": "Maldiskusjon", "message": "<p>Diskuter.</p>",
                              "html_url": "/courses/102/discussion_topics/591", "published": True, "assignment_id": None}}
    bp.modules = [{"id": "291", "name": "Malmodul", "position": 1, "require_sequential_progress": False,
                   "requirement_type": "all", "prerequisite_module_ids": [], "published": True, "unlock_at": None,
                   "items": [{"id": "2901", "title": "Malforside", "type": "Page", "page_url": "mal-forside",
                              "position": 1, "indent": 0, "published": True, "completion_requirement": None,
                              "html_url": "/courses/102/modules/items/2901"},
                             {"id": "2902", "title": "Malinnlevering", "type": "Assignment", "content_id": "391",
                              "position": 2, "indent": 0, "published": False, "completion_requirement": None,
                              "html_url": "/courses/102/modules/items/2902"}]}]
    bp.restrictions = {("assignment", "391"): {"restricted": True, "restrictions": {"content": True, "points": True}}}
    bp.blueprint_template = {"id": "1", "course_id": BLUEPRINT_COURSE_ID, "associated_course_count": 3,
                             "last_export_completed_at": "2026-08-01T10:00:00Z", "latest_migration": None}
    state.courses[BLUEPRINT_COURSE_ID] = bp
    student_course = CourseData(course={
        "id": "103", "name": "Emne jeg tar som student", "course_code": "STUD-1", "workflow_state": "available",
        "enrollments": [{"type": "student", "role": "StudentEnrollment", "enrollment_state": "active"}]})
    state.courses["103"] = student_course
    return state


# ------------------------------------------------------------------------------------- the app


def create_fake_canvas(state: FakeCanvasState | None = None) -> Any:
    state = state or seed_state()

    def err(status: int, message: str) -> JSONResponse:
        return JSONResponse({"errors": [{"message": message}]}, status_code=status)

    def course(request: Request) -> CourseData:
        cid = request.path_params["cid"]
        if cid not in state.courses:
            raise _Http(404, "The specified resource does not exist.")
        return state.courses[cid]

    def paginate(request: Request, items: list[Any]) -> JSONResponse:
        per_page = max(1, min(100, int(request.query_params.get("per_page") or 10)))
        page = max(1, int(request.query_params.get("page") or 1))
        start = (page - 1) * per_page
        chunk = items[start:start + per_page]
        params = [(k, v) for k, v in request.query_params.multi_items() if k != "page"]
        base = f"{state.origin}{request.url.path}"
        last = max(1, (len(items) + per_page - 1) // per_page)

        def link(p: int, rel: str) -> str:
            return f'<{base}?{urlencode([*params, ("page", p)])}>; rel="{rel}"'

        links = [link(page, "current"), link(1, "first"), link(last, "last")]
        if page < last:
            links.append(link(page + 1, "next"))
        if page > 1:
            links.append(link(page - 1, "prev"))
        return JSONResponse(chunk, headers={"Link": ",".join(links), "X-Rate-Limit-Remaining": "700.0",
                                            "X-Request-Cost": "0.2"})

    async def body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if not raw:
            return {}
        data = json.loads(raw)
        state.writes.append((request.method, request.url.path, data))
        return data

    # -- identity / courses ------------------------------------------------------------------

    async def users_self(request: Request) -> Response:
        return JSONResponse(state.user)

    async def list_courses(request: Request) -> Response:
        states = request.query_params.getlist("state[]") or ["available", "unpublished"]
        items = [copy.deepcopy(c.course) for c in state.courses.values() if c.course["workflow_state"] in states]
        return paginate(request, items)

    async def get_course(request: Request) -> Response:
        return JSONResponse(course(request).course)

    async def put_course(request: Request) -> Response:
        c = course(request)
        data = (await body(request)).get("course", {})
        if data.get("default_view") == "wiki" and not any(p["front_page"] for p in c.pages.values()):
            return err(400, "A Front Page is required")
        c.course.update(data)
        return JSONResponse(c.course)

    async def settings(request: Request) -> Response:
        c = course(request)
        if request.method == "PUT":
            c.settings.update(await body(request))
        return JSONResponse(c.settings)

    async def permissions(request: Request) -> Response:
        c = course(request)
        keys = request.query_params.getlist("permissions[]")
        return JSONResponse({k: c.permissions.get(k, False) for k in keys})

    async def tabs(request: Request) -> Response:
        return paginate(request, course(request).tabs)

    # -- pages -----------------------------------------------------------------------------------

    def page_by_ref(c: CourseData, ref: str) -> dict[str, Any]:
        if ref.startswith("page_id:"):
            ref = ref.split(":", 1)[1]
            for p in c.pages.values():
                if p["page_id"] == ref:
                    return p
        if ref in c.pages:
            return c.pages[ref]
        for p in c.pages.values():
            if p["page_id"] == ref:
                return p
        raise _Http(404, "page not found")

    def with_locks(c: CourseData, content_type: str, items: list[dict[str, Any]], key: str = "id") -> list[dict[str, Any]]:
        """Blueprint courses report lock status on list calls (like Canvas)."""
        if c.blueprint_template is None:
            return items
        result = []
        for item in items:
            lock = c.restrictions.get((content_type, str(item.get(key))))
            result.append({**item, "is_master_course_master_content": True,
                           "restricted_by_master_course": bool(lock and lock["restricted"]),
                           "master_course_restrictions": lock["restrictions"] if lock and lock["restricted"] else None})
        return result

    def page_json(p: dict[str, Any], with_body: bool) -> dict[str, Any]:
        data = copy.deepcopy(p)
        if p.get("editor") == "block_editor":
            data["body"] = None
            data["block_editor_attributes"] = {"version": "1", "blocks": "{}"}
        elif not with_body:
            data.pop("body", None)
        return data

    async def pages(request: Request) -> Response:
        c = course(request)
        if request.method == "POST":
            data = (await body(request)).get("wiki_page", {})
            slug = data.get("title", "side").lower().replace(" ", "-")
            while slug in c.pages:
                slug += "-2"
            p = _page(slug, data.get("title", "Uten tittel"), data.get("body", ""),
                      published=bool(data.get("published", False)), front=bool(data.get("front_page", False)))
            p["updated_at"] = now()
            c.pages[slug] = p
            c.revisions[slug] = [{"revision_id": 1, "updated_at": p["updated_at"], "latest": True,
                                  "title": p["title"], "body": p["body"]}]
            if p["front_page"]:
                for other in c.pages.values():
                    if other is not p:
                        other["front_page"] = False
            return JSONResponse(page_json(p, True))
        include_body = "body" in request.query_params.getlist("include[]")
        items = [page_json(p, include_body) for p in sorted(c.pages.values(), key=lambda p: p["title"])]
        return paginate(request, with_locks(c, "wiki_page", items, key="page_id"))

    async def page(request: Request) -> Response:
        c = course(request)
        p = page_by_ref(c, request.path_params["ref"])
        if request.method == "PUT":
            data = (await body(request)).get("wiki_page", {})
            if data.get("front_page") is True and not data.get("published", p["published"]):
                return err(400, "The front page cannot be unpublished")
            for key in ("title", "body", "published", "editing_roles"):
                if key in data:
                    p[key] = data[key]
            if data.get("front_page") is True:
                for other in c.pages.values():
                    other["front_page"] = other is p
            elif data.get("front_page") is False:
                p["front_page"] = False
            p["updated_at"] = now()
            revs = c.revisions.setdefault(p["url"], [])
            for r in revs:
                r["latest"] = False
            revs.append({"revision_id": len(revs) + 1, "updated_at": p["updated_at"], "latest": True,
                         "title": p["title"], "body": p["body"]})
            return JSONResponse(page_json(p, True))
        if request.method == "DELETE":
            if p["front_page"]:
                return err(400, "The front page cannot be deleted")
            del c.pages[p["url"]]
            state.writes.append(("DELETE", request.url.path, None))
            return JSONResponse(page_json(p, True))
        return JSONResponse(page_json(p, True))

    async def revisions(request: Request) -> Response:
        c = course(request)
        p = page_by_ref(c, request.path_params["ref"])
        return paginate(request, [{k: v for k, v in r.items() if k not in ("body", "title")}
                                  for r in c.revisions.get(p["url"], [])])

    async def revert(request: Request) -> Response:
        c = course(request)
        p = page_by_ref(c, request.path_params["ref"])
        rev_id = int(request.path_params["rev"])
        state.writes.append(("POST", request.url.path, None))
        revs = c.revisions.get(p["url"], [])
        target = next((r for r in revs if r["revision_id"] == rev_id), None)
        if target is None:
            return err(404, "revision not found")
        p["body"], p["title"], p["updated_at"] = target["body"], target["title"], now()
        revs.append({"revision_id": len(revs) + 1, "updated_at": p["updated_at"], "latest": True,
                     "title": p["title"], "body": p["body"]})
        return JSONResponse(page_json(p, True))

    async def front_page(request: Request) -> Response:
        c = course(request)
        current = next((p for p in c.pages.values() if p["front_page"]), None)
        if request.method == "PUT":
            data = await body(request)
            if current is None:
                return err(400, "no front page")
            for key in ("title", "body", "published"):
                if key in data:
                    current[key] = data[key]
            current["updated_at"] = now()
        if current is None:
            return err(404, "No front page has been set")
        return JSONResponse(page_json(current, True))

    # -- modules -----------------------------------------------------------------------------------

    def module_json(m: dict[str, Any], include_items: bool) -> dict[str, Any]:
        data = {k: v for k, v in m.items() if k != "items"}
        data["items_count"] = len(m["items"])
        if include_items and len(m["items"]) <= 100:
            data["items"] = [dict(i, module_id=m["id"]) for i in m["items"]]
        return data

    def find_module(c: CourseData, mid: str) -> dict[str, Any]:
        for m in c.modules:
            if m["id"] == mid:
                return m
        raise _Http(404, "module not found")

    async def modules(request: Request) -> Response:
        c = course(request)
        include_items = "items" in request.query_params.getlist("include[]")
        return paginate(request, [module_json(m, include_items) for m in sorted(c.modules, key=lambda m: m["position"])])

    async def module(request: Request) -> Response:
        c = course(request)
        m = find_module(c, request.path_params["mid"])
        if request.method == "PUT":
            data = (await body(request)).get("module", {})
            # Like canvas-lms ContextModulesApiController#update: requirement_type is NOT applied.
            for key in ("name", "position", "require_sequential_progress", "unlock_at", "prerequisite_module_ids",
                        "publish_final_grade"):
                if key in data and key not in state.ignored_fields:
                    m[key] = data[key]
        return JSONResponse(module_json(m, True))

    async def module_items(request: Request) -> Response:
        c = course(request)
        m = find_module(c, request.path_params["mid"])
        if request.method == "POST":
            data = (await body(request)).get("module_item", {})
            new = {"id": next_id(), "title": data.get("title", ""), "type": data.get("type", "Page"),
                   "position": data.get("position", len(m["items"]) + 1), "indent": 0, "published": True,
                   "completion_requirement": data.get("completion_requirement") or None}
            for key in ("page_url", "content_id", "external_url"):
                if key in data:
                    new[key] = data[key]
            m["items"].append(new)
            return JSONResponse(dict(new, module_id=m["id"]))
        return paginate(request, [dict(i, module_id=m["id"]) for i in sorted(m["items"], key=lambda i: i["position"])])

    async def module_item(request: Request) -> Response:
        c = course(request)
        m = find_module(c, request.path_params["mid"])
        item = next((i for i in m["items"] if i["id"] == request.path_params["iid"]), None)
        if item is None:
            return err(404, "item not found")
        if request.method == "DELETE":
            m["items"].remove(item)
            state.writes.append(("DELETE", request.url.path, None))
            return JSONResponse(item)
        if request.method == "PUT":
            data = (await body(request)).get("module_item", {})
            if "completion_requirement" in data:
                req = data["completion_requirement"]
                if req is None:
                    pass  # Canvas ignores JSON null
                elif not req:
                    item["completion_requirement"] = None
                else:
                    valid = {"must_view", "must_submit", "must_contribute", "min_score", "must_mark_done"}
                    if req.get("type") not in valid:
                        return err(400, "Invalid completion requirement type")
                    item["completion_requirement"] = dict(req) | {"completed": False}
            for key in ("title", "indent", "position"):
                if key in data:
                    item[key] = data[key]
            if "module_id" in data and data["module_id"] != m["id"]:
                target = find_module(c, str(data["module_id"]))
                m["items"].remove(item)
                target["items"].append(item)
                if "position" not in data:
                    item["position"] = len(target["items"])
                m = target
        return JSONResponse(dict(item, module_id=m["id"]))

    # -- assignments / discussions / files ------------------------------------------------------

    async def assignments(request: Request) -> Response:
        c = course(request)
        return paginate(request, with_locks(c, "assignment", list(c.assignments.values())))

    async def assignment(request: Request) -> Response:
        c = course(request)
        a = c.assignments.get(request.path_params["aid"])
        if a is None:
            return err(404, "not found")
        if request.method == "PUT":
            a.update((await body(request)).get("assignment", {}))
            a["updated_at"] = now()
        return JSONResponse(a)

    async def discussions(request: Request) -> Response:
        c = course(request)
        return paginate(request, with_locks(c, "discussion_topic", list(c.discussions.values())))

    async def discussion(request: Request) -> Response:
        c = course(request)
        d = c.discussions.get(request.path_params["did"])
        if d is None:
            return err(404, "not found")
        if request.method == "PUT":
            d.update(await body(request))
            d["updated_at"] = now()
        return JSONResponse(d)

    async def files(request: Request) -> Response:
        return paginate(request, list(course(request).files.values()))

    async def file_info(request: Request) -> Response:
        fid = request.path_params["fid"]
        for c in state.courses.values():
            if fid in c.files:
                return JSONResponse(c.files[fid])
        return err(404, "not found")

    async def file_download(request: Request) -> Response:
        fid = request.path_params["fid"]
        if fid not in state.file_bytes:
            return err(404, "not found")
        data, ctype = state.file_bytes[fid]
        return Response(data, media_type=ctype)

    async def media_objects(request: Request) -> Response:
        return paginate(request, course(request).media_objects)

    async def course_users(request: Request) -> Response:
        c = course(request)
        wanted = set(request.query_params.getlist("enrollment_type[]"))
        users = [{"id": u["id"], "name": u.get("name", "")} for u in c.users
                 if not wanted or u.get("enrollment") in wanted]
        return paginate(request, users)

    async def media_track_content(request: Request) -> Response:
        """Non-API route that serves a track's WebVTT (the ``url`` in media_objects[].media_tracks)."""
        for c in state.courses.values():
            for media in c.media_objects:
                if media.get("media_id") == request.path_params["mid"]:
                    for track in media.get("media_tracks") or []:
                        if str(track.get("id")) == request.path_params["tid"]:
                            return Response(track.get("webvtt_content") or "WEBVTT\n", media_type="text/vtt")
        return err(404, "not found")

    async def attachment_tracks(request: Request) -> Response:
        return JSONResponse(state.attachment_tracks.get(request.path_params["aid"], []))

    # -- quizzes ---------------------------------------------------------------------------------

    def quiz_by_id(c: CourseData, qid: str) -> dict[str, Any]:
        if qid not in c.quizzes:
            raise _Http(404, "quiz not found")
        return c.quizzes[qid]

    async def quizzes(request: Request) -> Response:
        c = course(request)
        if request.method == "POST":
            data = (await body(request)).get("quiz", {})
            qid = next_id()
            quiz = {"id": qid, "title": data.get("title", "Quiz"), "description": data.get("description", ""),
                    "quiz_type": data.get("quiz_type", "assignment"), "published": bool(data.get("published", False)),
                    "question_count": 0, "points_possible": 0, "html_url": f"/courses/{c.course['id']}/quizzes/{qid}"}
            for key in ("time_limit", "shuffle_answers", "hide_results", "show_correct_answers", "allowed_attempts",
                        "scoring_policy", "one_question_at_a_time", "cant_go_back", "due_at", "lock_at", "unlock_at"):
                if key in data:
                    quiz[key] = data[key]
            if int(quiz.get("allowed_attempts") or 1) <= 1:
                quiz.pop("scoring_policy", None)  # silently dropped, like real Canvas
            c.quizzes[qid] = quiz
            c.questions[qid] = []
            c.groups[qid] = []
            return JSONResponse(quiz)
        return paginate(request, with_locks(c, "quiz", list(c.quizzes.values())))

    async def quiz(request: Request) -> Response:
        c = course(request)
        q = quiz_by_id(c, request.path_params["qid"])
        if request.method == "PUT":
            data = (await body(request)).get("quiz", {})
            q.update(data)
            qs = c.questions.get(q["id"], [])
            ungrouped = sum(float(x.get("points_possible") or 0) for x in qs if not x.get("quiz_group_id"))
            grouped = sum(float(g.get("pick_count") or 0) * float(g.get("question_points") or 0)
                          for g in c.groups.get(q["id"], []))
            q["points_possible"] = ungrouped + grouped
            q["question_count"] = len([x for x in qs if not x.get("quiz_group_id")]) + sum(
                int(g.get("pick_count") or 0) for g in c.groups.get(q["id"], []))
        elif request.method == "DELETE":
            state.writes.append(("DELETE", request.url.path, None))
            del c.quizzes[q["id"]]
        return JSONResponse(q)

    async def questions(request: Request) -> Response:
        c = course(request)
        q = quiz_by_id(c, request.path_params["qid"])
        if request.method == "POST":
            data = (await body(request)).get("question", {})
            answers = []
            for a in data.get("answers") or []:
                answers.append({"id": next_id(), "text": a.get("answer_text", ""), "html": a.get("answer_html", ""),
                                "weight": float(a.get("answer_weight", 0)), "comments": a.get("answer_comments", "")})
            if data.get("question_type") == "multiple_choice_question" and answers and not any(
                    a["weight"] >= 100 for a in answers):
                answers[0]["weight"] = 100.0  # Canvas quirk: first answer becomes correct
            new = {"id": next_id(), "quiz_id": q["id"], "position": data.get("position", len(c.questions[q["id"]]) + 1),
                   "question_name": data.get("question_name", ""), "question_type": data.get("question_type"),
                   "question_text": data.get("question_text", ""), "points_possible": data.get("points_possible", 1),
                   "quiz_group_id": data.get("quiz_group_id"), "answers": answers,
                   "neutral_comments": data.get("neutral_comments", "")}
            c.questions[q["id"]].append(new)
            return JSONResponse(new)
        return paginate(request, list(c.questions.get(q["id"], [])))

    async def question(request: Request) -> Response:
        c = course(request)
        q = quiz_by_id(c, request.path_params["qid"])
        found = next((x for x in c.questions.get(q["id"], []) if x["id"] == request.path_params["qq"]), None)
        if found is None:
            return err(404, "not found")
        if request.method == "PUT":
            data = (await body(request)).get("question", {})
            for key in ("question_name", "question_text", "points_possible", "question_type", "correct_comments",
                        "incorrect_comments", "neutral_comments"):
                if key in data:
                    found[key] = data[key]
            if "answers" in data:
                # Like Canvas: the answers are replaced wholesale by what is sent.
                found["answers"] = [{"id": a.get("id") or next_id(), "text": a.get("answer_text", ""),
                                     "html": a.get("answer_html", ""), "weight": float(a.get("answer_weight", 0)),
                                     "comments": a.get("answer_comments", "")}
                                    for a in data["answers"]]
        return JSONResponse(found)

    async def groups(request: Request) -> Response:
        c = course(request)
        q = quiz_by_id(c, request.path_params["qid"])
        if request.method == "POST":
            data = (await body(request)).get("quiz_groups", [{}])[0]
            group = {"id": next_id(), "quiz_id": q["id"], "name": data.get("name", "Gruppe"),
                     "pick_count": int(data.get("pick_count", 1)), "question_points": float(data.get("question_points", 1)),
                     "assessment_question_bank_id": data.get("assessment_question_bank_id")}
            c.groups[q["id"]].append(group)
            return JSONResponse({"quiz_groups": [group]}, status_code=201)
        return JSONResponse({"quiz_groups": c.groups.get(q["id"], [])})

    # -- blueprint ---------------------------------------------------------------------------------

    async def blueprint(request: Request) -> Response:
        c = course(request)
        if c.blueprint_template is None:
            return err(404, "The specified resource does not exist.")
        return JSONResponse(c.blueprint_template)

    async def restrict_item(request: Request) -> Response:
        c = course(request)
        if c.blueprint_template is None:
            return err(404, "The specified resource does not exist.")
        data = await body(request)
        valid = {"assignment", "attachment", "discussion_topic", "external_tool", "lti-quiz", "quiz", "wiki_page"}
        if data.get("content_type") not in valid:
            return err(400, "invalid content type")
        c.restrictions[(data["content_type"], str(data["content_id"]))] = {
            "restricted": bool(data.get("restricted")), "restrictions": data.get("restrictions") or {"content": True}}
        return JSONResponse({"success": True})

    async def unsynced(request: Request) -> Response:
        c = course(request)
        if c.blueprint_template is None:
            return err(404, "The specified resource does not exist.")
        return paginate(request, [])

    async def subscriptions(request: Request) -> Response:
        return JSONResponse(course(request).subscriptions)

    routes = [
        Route("/api/v1/users/self", users_self),
        Route("/api/v1/courses", list_courses),
        Route("/api/v1/courses/{cid}", get_course),
        Route("/api/v1/courses/{cid}", put_course, methods=["PUT"]),
        Route("/api/v1/courses/{cid}/settings", settings, methods=["GET", "PUT"]),
        Route("/api/v1/courses/{cid}/permissions", permissions),
        Route("/api/v1/courses/{cid}/tabs", tabs),
        Route("/api/v1/courses/{cid}/pages", pages, methods=["GET", "POST"]),
        Route("/api/v1/courses/{cid}/pages/{ref}/revisions", revisions),
        Route("/api/v1/courses/{cid}/pages/{ref}/revisions/{rev}", revert, methods=["POST"]),
        Route("/api/v1/courses/{cid}/pages/{ref}", page, methods=["GET", "PUT", "DELETE"]),
        Route("/api/v1/courses/{cid}/front_page", front_page, methods=["GET", "PUT"]),
        Route("/api/v1/courses/{cid}/modules", modules),
        Route("/api/v1/courses/{cid}/modules/{mid}", module, methods=["GET", "PUT"]),
        Route("/api/v1/courses/{cid}/modules/{mid}/items", module_items, methods=["GET", "POST"]),
        Route("/api/v1/courses/{cid}/modules/{mid}/items/{iid}", module_item, methods=["GET", "PUT", "DELETE"]),
        Route("/api/v1/courses/{cid}/assignments", assignments),
        Route("/api/v1/courses/{cid}/assignments/{aid}", assignment, methods=["GET", "PUT"]),
        Route("/api/v1/courses/{cid}/discussion_topics", discussions),
        Route("/api/v1/courses/{cid}/discussion_topics/{did}", discussion, methods=["GET", "PUT"]),
        Route("/api/v1/courses/{cid}/files", files),
        Route("/api/v1/files/{fid}", file_info),
        Route("/files/{fid}/download", file_download),
        Route("/api/v1/courses/{cid}/media_objects", media_objects),
        Route("/api/v1/media_attachments/{aid}/media_tracks", attachment_tracks),
        Route("/api/v1/courses/{cid}/users", course_users),
        Route("/media_objects/{mid}/media_tracks/{tid}", media_track_content),
        Route("/api/v1/courses/{cid}/quizzes", quizzes, methods=["GET", "POST"]),
        Route("/api/v1/courses/{cid}/quizzes/{qid}", quiz, methods=["GET", "PUT", "DELETE"]),
        Route("/api/v1/courses/{cid}/quizzes/{qid}/questions", questions, methods=["GET", "POST"]),
        Route("/api/v1/courses/{cid}/quizzes/{qid}/questions/{qq}", question, methods=["GET", "PUT"]),
        Route("/api/v1/courses/{cid}/quizzes/{qid}/groups", groups, methods=["GET", "POST"]),
        Route("/api/v1/courses/{cid}/blueprint_templates/default", blueprint),
        Route("/api/v1/courses/{cid}/blueprint_templates/default/restrict_item", restrict_item, methods=["PUT"]),
        Route("/api/v1/courses/{cid}/blueprint_templates/default/unsynced_changes", unsynced),
        Route("/api/v1/courses/{cid}/blueprint_subscriptions", subscriptions),
    ]
    async def http_error(_request: Request, exc: Exception) -> Response:
        assert isinstance(exc, _Http)
        return err(exc.status, exc.message)

    app = Starlette(routes=routes, exception_handlers={_Http: http_error})

    async def guarded(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        request = Request(scope)
        state.requests.append((request.method, request.url.path))
        response: Response | None = None
        if not request.headers.get("user-agent"):
            response = JSONResponse({"error": "Forbidden", "message": "not provided a valid user agent."},
                                    status_code=403)
        elif not request.url.path.startswith("/files/") and                 request.headers.get("authorization") != f"Bearer {state.token}":
            response = err(401, "Invalid access token.")
        elif state.rate_limit_failures > 0:
            state.rate_limit_failures -= 1
            status = state.rate_limit_status
            response = Response(f"{status} Forbidden (Rate Limit Exceeded)", status_code=status,
                                headers={"X-Rate-Limit-Remaining": "0.0"})
        else:
            for fragment, status in state.fail.items():
                if fragment in request.url.path:
                    response = err(status, "simulated failure")
                    break
        if response is not None:
            await response(scope, receive, send)
            return
        await app(scope, receive, send)

    guarded.state = state  # type: ignore[attr-defined]
    return guarded  # type: ignore[return-value]


class _Http(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
