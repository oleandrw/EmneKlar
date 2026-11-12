"""A fake AI provider (Anthropic Messages API shape) for local testing of KI-forslag til alt-tekst.

Used by the dev server with ``--demo``: nothing leaves the machine. It answers alt-text requests only, after a short
delay (so the queue's «genereres» state can be seen), with a clearly marked test suggestion built from the page title
in the prompt. Every other AI task is refused with an explanation. Never shipped to users.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx

DELAY_SECONDS = 1.2


def fake_ai_transport(delay: float = DELAY_SECONDS) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            # «Koble til» in Innstillinger → KI-assistenter: a key containing "ugyldig" is rejected, others accepted.
            await asyncio.sleep(delay / 2)
            key = request.headers.get("x-api-key") or request.headers.get("authorization") or ""
            if "ugyldig" in key:
                return httpx.Response(401, json={"type": "error", "error": {
                    "type": "authentication_error", "message": "invalid x-api-key"}})
            return httpx.Response(200, json={"data": [{"id": "testmodell-1", "display_name": "Testmodell 1"}]})
        data = json.loads(request.content or b"{}")
        system = json.dumps(data.get("system") or "", ensure_ascii=False)
        if "alt-tekst" not in system:
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "Den falske KI-leverandøren i testmodus støtter bare "
                                                           "alt-tekst."}})
        await asyncio.sleep(delay)
        text = json.dumps(data.get("messages") or [], ensure_ascii=False)
        page = re.search(r"«([^»]{1,80})»", text)
        heading = re.search(r"Nærmeste overskrift over bildet: «([^»]{1,80})»", text)
        subject = heading.group(1) if heading else (page.group(1) if page else "innholdet")
        answer = {"alt_text": f"Testforslag: eksempel som illustrerer «{subject}»", "decorative": False,
                  "image_kind": "informative", "confidence": "low",
                  "notes": "Laget av den falske KI-leverandøren i testmodus – ikke en ekte bildebeskrivelse."}
        return httpx.Response(200, json={"id": "msg_fake", "type": "message", "role": "assistant",
                                         "content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}],
                                         "stop_reason": "end_turn", "usage": {"input_tokens": 400, "output_tokens": 60}})

    return httpx.MockTransport(handler)
