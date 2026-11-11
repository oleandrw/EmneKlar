"""Deterministic checks of course, page, assignment and quiz settings.

The checks are about whether students can do and hand in the work (submission types, dates, publishing, who the
work is assigned to) and about real security risks (public course, pages anyone can edit). Quiz design choices
(time limits, locked question order) are the teacher's and are not reported.

Every item is categorised as recommendation, technical problem, security concern or preference. Preferences are
never changed automatically – only when the user explicitly picks a new value. Field values follow the Canvas API
documentation (Assignments: ``submission_types``, ``published``, ``unlock_at``/``lock_at``/``due_at``,
``only_visible_to_overrides``, ``has_overrides``; Courses: ``workflow_state``, ``blueprint``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

#: «security_accessibility» is kept as the key (stored and used by the UI); it now holds security risks only.
CATEGORY_LABELS = {"technical": "Teknisk problem", "security_accessibility": "Sikkerhet",
                   "recommendation": "Anbefaling", "preference": "Preferanse"}
DEFAULT_VIEW_LABELS = {"feed": "Siste aktivitet", "wiki": "Forside", "modules": "Moduler",
                       "assignments": "Oppgaveliste", "syllabus": "Emneplan"}
#: Boolean course settings offered as preferences (only shown when Canvas returns the key).
PREFERENCES: dict[str, tuple[str, str]] = {
    "allow_student_discussion_topics": ("Studenter kan opprette diskusjoner",
                                        "Gir studentene mulighet til å starte egne diskusjonstråder."),
    "allow_student_forum_attachments": ("Studenter kan legge ved filer i diskusjoner", ""),
    "allow_student_discussion_editing": ("Studenter kan redigere og slette egne innlegg", ""),
    "allow_student_organized_groups": ("Studenter kan opprette egne grupper", ""),
    "lock_all_announcements": ("Kommentarer på kunngjøringer er slått av", ""),
    "show_announcements_on_home_page": ("Vis siste kunngjøringer på startsiden", ""),
    "hide_final_grades": ("Skjul totalkarakteren for studentene", ""),
    "hide_distribution_graphs": ("Skjul karakterfordelingen for studentene", ""),
    "restrict_student_future_view": ("Studenter ser ikke emnet før startdato", ""),
    "restrict_student_past_view": ("Studenter ser ikke emnet etter sluttdato", ""),
    "syllabus_course_summary": ("Vis aktivitetsoversikt i emneplanen", ""),
    "usage_rights_required": ("Krev opphavsrettsinformasjon før filer publiseres", ""),
}
OFFLINE = {"none", "on_paper", "not_graded"}
#: Submission types where students do not hand in anything in Canvas (Canvas API: Assignments).
NO_SUBMISSION = {"none": "Ingen innlevering", "on_paper": "På papir"}
#: Unpublished work whose due date is this close is reported – students cannot see it or hand it in.
SOON = timedelta(days=14)


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _when(value: datetime) -> str:
    """«15.09.2026 kl. 23:59» in this machine's time zone (Canvas returns UTC)."""
    return value.astimezone().strftime("%d.%m.%Y kl. %H:%M")


def _item(rule_id: str, category: str, title: str, explanation: str, obj: dict[str, Any], *, current: str = "",
          recommendation: str = "", fix: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": f"{rule_id}:{obj.get('type')}:{obj.get('id')}", "rule_id": rule_id, "category": category,
            "category_label": CATEGORY_LABELS[category], "title": title, "explanation": explanation, "object": obj,
            "current": current, "recommendation": recommendation, "fix": fix}


def _dates(kind: str, raw: dict[str, Any], obj: dict[str, Any], items: list[dict[str, Any]], *,
           now: datetime, students_enrolled: bool) -> None:
    due, lock, unlock = _dt(raw.get("due_at")), _dt(raw.get("lock_at")), _dt(raw.get("unlock_at"))
    if unlock and lock and lock <= unlock:
        items.append(_item(f"CS-{kind}-LOCK-BEFORE-UNLOCK", "technical", "Stenges før den åpner",
                           "Elementet stenges før det åpner, så studentene får aldri tilgang til det.", obj,
                           current=f"Åpner {_when(unlock)}, stenges {_when(lock)}",
                           recommendation="Rett «Tilgjengelig fra» og «Tilgjengelig til» i Canvas."))
    elif due and lock and lock < due:
        items.append(_item(f"CS-{kind}-LOCK-BEFORE-DUE", "technical", "Stenges før fristen",
                           "Elementet stenges for studentene før fristen. Studentene kan ikke levere helt fram til "
                           "fristen.", obj, current=f"Frist {_when(due)}, stenges {_when(lock)}",
                           recommendation="Sett «Tilgjengelig til» lik eller etter fristen i Canvas."))
    if due and unlock and unlock > due:
        items.append(_item(f"CS-{kind}-UNLOCK-AFTER-DUE", "technical", "Åpner etter fristen",
                           "Elementet blir tilgjengelig først etter at fristen har gått ut.", obj,
                           current=f"Åpner {_when(unlock)}, frist {_when(due)}",
                           recommendation="Kontroller datoene i Canvas."))
    if students_enrolled and not raw.get("published") and due and now <= due <= now + SOON:
        items.append(_item(f"CS-{kind}-UNPUBLISHED-DUE-SOON", "technical", "Ikke publisert, men fristen er snart",
                           "Studentene ser ikke elementet og kan ikke levere før det er publisert.", obj,
                           current=f"Ikke publisert, frist {_when(due)}",
                           recommendation="Publiser i Canvas når studentene skal kunne levere."))


def analyze(*, course: dict[str, Any], settings: dict[str, Any], tabs: list[dict[str, Any]],
            front_page: dict[str, Any] | None, pages: list[dict[str, Any]], assignments: list[dict[str, Any]],
            quizzes: list[dict[str, Any]], modules: list[dict[str, Any]], now: datetime | None = None,
            ) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    now = now or datetime.now(UTC)
    # Unpublished work only matters where students take the course: not in a Blueprint (template) course and not in
    # a course that is itself unpublished or concluded.
    students_enrolled = course.get("workflow_state") == "available" and not course.get("blueprint")
    course_obj = {"type": "course", "id": str(course.get("id")), "title": course.get("name"), "url": None}
    view = course.get("default_view")
    view_label = DEFAULT_VIEW_LABELS.get(str(view), str(view))
    options = [{"value": "modules", "label": DEFAULT_VIEW_LABELS["modules"]}]
    if front_page:
        options.append({"value": "wiki", "label": DEFAULT_VIEW_LABELS["wiki"]})

    # -- course ----------------------------------------------------------------------------------
    if view == "wiki" and not front_page:
        items.append(_item("CS-HOME-NO-FRONT", "technical", "Startsiden peker på en forside som ikke finnes",
                           "Startsiden er satt til «Forside», men emnet har ingen forside.", course_obj,
                           current=view_label, recommendation="Bruk «Moduler» som startside, eller lag en forside.",
                           fix={"kind": "default_view", "options": options[:1]}))
    elif view == "feed":
        items.append(_item("CS-HOME-FEED", "recommendation", "Startsiden viser «Siste aktivitet»",
                           "Studentene finner som regel lettere fram når startsiden er en forside eller modulene.",
                           course_obj, current=view_label, recommendation="Velg «Moduler» eller «Forside».",
                           fix={"kind": "default_view", "options": options}))
    if not front_page and view != "wiki":
        items.append(_item("CS-NO-FRONT-PAGE", "recommendation", "Emnet har ingen forside",
                           "En forside med velkomst og hurtiglenker gir studentene en tydelig inngang til emnet.",
                           course_obj, recommendation=(
                               "Lag en side under Sider i Canvas, og gjør den til emnets forside. Gi den deretter "
                               "emnets design under Emnedesign."),
                           fix={"kind": "link", "path": "/emnedesign", "label": "Gå til Emnedesign"}))
    if course.get("is_public"):
        items.append(_item("CS-COURSE-PUBLIC", "security_accessibility", "Emnet er offentlig",
                           "Alle på internett kan se emnet uten å logge inn. Kontroller at innholdet kan deles "
                           "offentlig (opphavsrett og personopplysninger).", course_obj, current="Offentlig",
                           recommendation="Endre synligheten under Innstillinger i Canvas om dette ikke er tilsiktet."))
    hidden = {str(t.get("id")) for t in tabs if t.get("hidden")}
    if "modules" in hidden and modules:
        items.append(_item("CS-TAB-MODULES-HIDDEN", "recommendation", "«Moduler» er skjult i emnemenyen",
                           "Emnet har moduler, men lenken til dem er skjult for studentene i emnemenyen.", course_obj,
                           current="Skjult", recommendation="Vis «Moduler» under Innstillinger → Navigasjon i Canvas."))

    # -- pages -----------------------------------------------------------------------------------
    for page in pages:
        roles = {r.strip() for r in str(page.get("editing_roles") or "").split(",") if r.strip()}
        obj = {"type": "page", "id": str(page.get("url")), "title": page.get("title"), "url": page.get("html_url")}
        if "public" in roles:
            items.append(_item("CS-PAGE-EDIT-PUBLIC", "security_accessibility", "Alle kan redigere siden",
                               "Siden kan redigeres av alle, også uten innlogging.", obj, current="Alle",
                               recommendation="Begrens redigering til lærere under sidens innstillinger i Canvas."))
        elif roles & {"students", "members"}:
            items.append(_item("CS-PAGE-EDIT-STUDENTS", "security_accessibility", "Studenter kan redigere siden",
                               "Studentene kan endre innholdet på siden. Kontroller at dette er tilsiktet.", obj,
                               current="Lærere og studenter",
                               recommendation="Begrens redigering til lærere om siden ikke er ment for samarbeid."))

    # -- assignments -----------------------------------------------------------------------------
    for a in assignments:
        types = set(a.get("submission_types") or [])
        obj = {"type": "assignment", "id": str(a.get("id")), "title": a.get("name"), "url": a.get("html_url")}
        if a.get("published") and a.get("only_visible_to_overrides") and not a.get("has_overrides"):
            items.append(_item("CS-ASSIGN-NO-ASSIGNEES", "technical", "Ingen er tildelt oppgaven",
                               "Oppgaven vises bare for dem den er tildelt, men den er ikke tildelt noen. Ingen "
                               "studenter ser den eller kan levere.", obj, current="Tildelt: ingen",
                               recommendation="Tildel oppgaven til alle eller til seksjoner under «Tildel til» i "
                                              "Canvas."))
        if "online_quiz" in types:
            continue  # the rest is checked as a quiz
        _dates("ASSIGN", a, obj, items, now=now, students_enrolled=students_enrolled)
        graded = float(a.get("points_possible") or 0) > 0
        online = bool(types - OFFLINE)
        if a.get("published") and graded and types and types <= set(NO_SUBMISSION):
            items.append(_item("CS-ASSIGN-NO-SUBMISSION", "recommendation", "Studentene kan ikke levere i Canvas",
                               "Oppgaven gir poeng, men har ingen innleveringsmåte i Canvas. Det passer for "
                               "muntlige, praktiske eller papirbaserte oppgaver; skal studentene levere i Canvas, "
                               "trenger oppgaven en innleveringstype.", obj,
                               current=", ".join(NO_SUBMISSION[t] for t in sorted(types)),
                               recommendation="Velg innleveringstype i oppgavens innstillinger i Canvas, om "
                                              "studentene skal levere der."))
        if a.get("published") and graded and online and not a.get("due_at") and not a.get("has_overrides"):
            items.append(_item("CS-ASSIGN-NO-DUE", "recommendation", "Oppgaven har ingen frist",
                               "Uten frist vises ikke oppgaven i kalenderen og i studentenes oversikt over kommende "
                               "arbeid.", obj, current="Ingen frist",
                               recommendation="Legg inn en frist i Canvas om oppgaven har en."))

    # -- quizzes ---------------------------------------------------------------------------------
    for q in quizzes:
        obj = {"type": "quiz", "id": str(q.get("id")), "title": q.get("title"), "url": q.get("html_url")}
        _dates("QUIZ", q, obj, items, now=now, students_enrolled=students_enrolled)
        if q.get("published") and not q.get("question_count"):
            items.append(_item("CS-QUIZ-EMPTY", "technical", "Publisert quiz uten spørsmål",
                               "Quizen er publisert, men har ingen spørsmål.", obj, current="0 spørsmål",
                               recommendation="Legg til spørsmål eller avpubliser quizen."))
        reveals = q.get("show_correct_answers") and not q.get("show_correct_answers_last_attempt") \
            and not q.get("show_correct_answers_at")
        if q.get("quiz_type") == "assignment" and q.get("allowed_attempts") == -1 and reveals:
            items.append(_item("CS-QUIZ-ANSWERS-UNLIMITED", "security_accessibility",
                               "Riktige svar vises, og forsøkene er ubegrensede",
                               "Studentene kan se fasiten etter et forsøk og deretter ta quizen på nytt. Det svekker "
                               "quizen som vurdering.", obj, current="Ubegrensede forsøk, fasit vises",
                               recommendation="Vis riktige svar først etter siste forsøk, eller begrens antall forsøk."))

    preferences = [{"key": key, "label": label, "description": description, "value": bool(settings[key])}
                   for key, (label, description) in PREFERENCES.items() if isinstance(settings.get(key), bool)]
    order = list(CATEGORY_LABELS)
    items.sort(key=lambda i: (order.index(i["category"]), i["title"]))
    return {"items": items, "counts": {k: sum(1 for i in items if i["category"] == k) for k in CATEGORY_LABELS},
            "category_labels": CATEGORY_LABELS, "preferences": preferences,
            "course": {"default_view": view, "default_view_label": view_label, "has_front_page": bool(front_page)},
            "checked": {"pages": len(pages), "assignments": len(assignments), "quizzes": len(quizzes)},
            "limitations": ["Datoer som er overstyrt for enkelte seksjoner eller studenter, kontrolleres ikke.",
                            "Upubliserte oppgaver og quizer med frist innen 14 dager meldes bare i emner som er "
                            "publisert og ikke er Blueprint-emner.",
                            "Navigasjon og synlighet for emnet endres i Canvas – EmneKlar viser bare det som bør "
                            "vurderes."]}
