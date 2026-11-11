"""User-facing errors.

Every error that can reach the GUI carries a stable ``code`` and a short,
understandable Norwegian message. Technical details are optional, always
redacted, and shown only behind «Vis detaljer». Stack traces never leave the
backend.
"""

from __future__ import annotations

from typing import Any

MESSAGES: dict[str, str] = {
    # Generic
    "internal_error": "Noe gikk galt i EmneKlar. Prøv igjen, eller se loggen for detaljer.",
    "validation_error": "Forespørselen inneholdt ugyldige verdier.",
    "not_found": "Fant ikke det du lette etter.",
    "method_not_allowed": "Denne handlingen støttes ikke på denne adressen.",
    "conflict": "Handlingen kan ikke utføres i nåværende tilstand.",
    "confirmation_required": "Handlingen må bekreftes før den kan utføres.",
    "feature_disabled": "Denne funksjonen er slått av under Innstillinger → Avanserte innstillinger.",
    "unsupported": "Dette støttes ikke.",
    # Local web security
    "session_required": "Økten er ikke gyldig. Start EmneKlar på nytt fra Start-menyen (eller med start.bat).",
    "csrf_failed": "Sikkerhetskontrollen for forespørselen feilet. Last siden på nytt.",
    "origin_rejected": "Forespørselen kom fra en ukjent nettside og ble avvist.",
    "host_rejected": "Forespørselen brukte en ukjent vertsadresse og ble avvist.",
    "control_rejected": "Kontrollforespørselen ble avvist.",
    # Setup / Canvas
    "setup_required": "EmneKlar er ikke satt opp ennå. Fullfør oppsettet først.",
    "canvas_not_configured": "Canvas er ikke koblet til ennå. Gå til Innstillinger → Canvas-tilkobling.",
    "canvas_url_invalid": "Canvas-adressen ser ikke gyldig ut. Bruk for eksempel https://hiof.instructure.com.",
    "canvas_token_missing": "Canvas API-token mangler. Legg det inn under Innstillinger → Canvas-tilkobling.",
    "canvas_token_invalid": "Canvas avviste tokenet. Det kan være utløpt, slettet eller skrevet inn feil.",
    "canvas_token_other_url": "Tokenet som er lagret, hører til en annen Canvas-adresse. Lim inn et tilgangstoken for "
                              "den nye adressen.",
    "canvas_identity_changed": "Tokenet hører nå til en annen Canvas-bruker enn den du bekreftet. Ingenting er lagret – "
                               "test tilkoblingen på nytt.",
    "canvas_forbidden": "Du mangler tilgang til dette i Canvas.",
    "canvas_not_found": "Canvas fant ikke ressursen. Den kan være slettet eller skjult.",
    "canvas_rate_limited": "Canvas ber EmneKlar vente litt (for mange forespørsler). Prøv igjen om et øyeblikk.",
    "canvas_unavailable": "Canvas svarte ikke. Kontroller nettverket og prøv igjen.",
    "canvas_error": "Canvas returnerte en feil.",
    "canvas_write_blocked": "Endringer i Canvas kan bare gjøres gjennom endringskøen.",
    "course_required": "Velg et emne først.",
    "course_not_found": "Fant ikke emnet. Du har kanskje ikke tilgang lenger.",
    "snapshot_missing": "Det finnes ingen analyse av emnet ennå. Kjør en analyse først.",
    # Jobs / analysis
    "job_not_found": "Fant ikke jobben.",
    "job_already_running": "Det kjører allerede en analyse av dette emnet.",
    "job_not_pausable": "Jobben kan ikke settes på pause nå.",
    "analysis_nothing_selected": "Velg minst ett analyseområde og et omfang med innhold.",
    # Changes
    "change_not_found": "Fant ikke endringen.",
    "change_not_editable": "Denne endringen kan ikke redigeres.",
    "change_conflict": "Innholdet er endret i Canvas etter at forslaget ble laget. Se over forslaget på nytt.",
    "change_state_invalid": "Endringen har en status som ikke tillater denne handlingen.",
    "update_source_confirmation_required": "Et annet oppdateringsrepository enn standardkilden må bekreftes.",
    "change_requires_confirmation": "Endringen har høy risiko og må bekreftes eksplisitt.",
    "publish_running": "En publisering til Canvas pågår allerede. Vent til den er ferdig.",
    "undo_not_possible": "Denne endringen kan ikke angres automatisk.",
    "undo_conflict": "Innholdet er endret etter at endringen ble gjort. Angring ville overskrevet nyere arbeid.",
    # Secrets
    "secret_store_unavailable": "Fant ingen sikker nøkkelring i operativsystemet. Hemmeligheter kan ikke lagres.",
    "secret_invalid": "Verdien kan ikke lagres som hemmelighet.",
    # AI
    "ai_not_configured": "Ingen KI-leverandør er satt opp. Gå til Innstillinger → KI-assistenter.",
    "ai_sharing_disabled": (
        "Sending av emneinnhold til ekstern KI er slått av. Slå det på under Innstillinger → Sikkerhet og personvern."
    ),
    "ai_consent_required": "Du må bekrefte hva som sendes til KI-leverandøren før forespørselen kan sendes.",
    "ai_no_model": "Ingen aktivert modell passer for denne oppgaven. Se Innstillinger → KI-assistenter.",
    "ai_key_missing": "API-nøkkel for KI-leverandøren mangler.",
    "ai_key_invalid": "KI-leverandøren avviste API-nøkkelen.",
    "ai_unavailable": "KI-leverandøren er midlertidig utilgjengelig.",
    "ai_rate_limited": "KI-leverandøren begrenser antall forespørsler. Prøv igjen senere.",
    "ai_bad_response": "KI-leverandøren returnerte et svar som ikke kunne brukes.",
    "ai_model_missing": "Modellen finnes ikke hos leverandøren.",
    "ai_timeout": "KI-leverandøren svarte ikke i tide.",
    "ai_refused": "KI-modellen avslo forespørselen.",
    "ai_all_failed": "Ingen av de aktuelle KI-modellene klarte oppgaven. Se detaljer.",
    # Files / URLs
    "file_too_large": "Filen er for stor til å analyseres.",
    "file_unsupported": "Dette filformatet støttes ikke.",
    "file_parse_failed": "Kunne ikke lese filen.",
    "url_blocked": "Adressen er blokkert av sikkerhetshensyn.",
    # Emne-RAG
    "rag_index_missing": ("Det finnes ingen kunnskapsbase for emnet ennå. Opprett den under Canvas-verktøy → Emnets "
                          "kunnskapsbase først."),
    "rag_index_busy": "Kunnskapsbasen for emnet bygges eller oppdateres akkurat nå. Vent til jobben er ferdig.",
    "rag_index_foreign": "Filen med kunnskapsbasen tilhører ikke EmneKlar og ble ikke åpnet.",
    "rag_index_outdated": "Kunnskapsbasen er laget av en eldre versjon av EmneKlar. Bygg den på nytt.",
    "rag_model_changed": (
        "Kunnskapsbasen er laget med en annen embedding-modell enn den som er valgt nå. Bygg den på nytt."
    ),
    "rag_nothing_selected": "Velg minst én kildetype, og minst én modul hvis du har valgt «Valgte moduler».",
    "rag_download_required": "Lokale modeller må lastes ned første gang. Bekreft nedlastingen før du starter.",
    "rag_local_models_missing": (
        "Lokale modeller følger ikke med EmneKlar. Velg en KI-leverandør for semantisk søk eller transkripsjon i "
        "innstillingene for kunnskapsbasen, eller bruk nøkkelordsøk og eksisterende teksting."
    ),
    "rag_query_empty": "Skriv et spørsmål.",
    # KI-bildeassistent
    "illustration_nothing_selected": "Velg hva som skal behandles: hele emnet, minst én modul eller én side.",
    "illustration_file_locked": (
        "Emnet krever opphavsrettsinformasjon for filer. Velg opphavsrettsgrunnlag før publisering, ellers blir "
        "bildet låst og usynlig for studentene."
    ),
    "illustration_page_changed": "Siden er endret i Canvas etter analysen. Velg plassering på nytt før publisering.",
    "illustration_cost_limit": "Kostnadsgrensen for jobben er nådd. Jobben er stoppet.",
    "illustration_busy": "KI-bildeassistenten arbeider allerede med dette emnet. Vent til jobben er ferdig.",
    "illustration_image_unavailable": "Ingen bildemodell er tilgjengelig. Se Innstillinger → KI-assistenter.",
    # Reports / updates
    "report_not_found": "Fant ikke rapporten.",
    "update_check_failed": "Kunne ikke sjekke etter oppdateringer.",
}


class AppError(Exception):
    """An error with a stable code, a user-facing message and an HTTP status."""

    def __init__(
        self,
        code: str,
        *,
        status: int = 400,
        message: str | None = None,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.message = message or MESSAGES.get(code) or MESSAGES["internal_error"]
        self.detail = detail
        self.extra = extra or {}
        super().__init__(f"{code}: {detail or self.message}")

    def to_payload(self) -> dict[str, Any]:
        from emneklar.core.security.redaction import redact  # local import avoids cycles

        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            payload["details"] = redact(self.detail)[:2000]
        if self.extra:
            payload["extra"] = self.extra
        return {"error": payload}


class NotFoundError(AppError):
    def __init__(self, code: str = "not_found", detail: str | None = None) -> None:
        super().__init__(code, status=404, detail=detail)


class ConflictError(AppError):
    def __init__(self, code: str = "conflict", detail: str | None = None, **extra: Any) -> None:
        super().__init__(code, status=409, detail=detail, extra=extra or None)
