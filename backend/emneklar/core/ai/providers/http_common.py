"""Shared HTTP handling for AI providers (timeouts, retries, error mapping, JSON parsing)."""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import httpx

from emneklar import __version__
from emneklar.core.ai.base import AIError, status_to_error

USER_AGENT = f"EmneKlar/{__version__}"
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}


def make_client(timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    # No redirects: API endpoints must answer directly. Only the provider's own key is ever attached.
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False, trust_env=False,
                             headers={"User-Agent": USER_AGENT}, transport=transport)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    ms = response.headers.get("retry-after-ms", "")
    if ms.replace(".", "", 1).isdigit():
        return float(ms) / 1000
    seconds = response.headers.get("retry-after", "")
    if seconds.replace(".", "", 1).isdigit():
        return float(seconds)
    return 2.0 * attempt


async def post_json(client: httpx.AsyncClient, url: str, payload: dict[str, Any], headers: dict[str, str], *,
                    retries: int = 1) -> dict[str, Any]:
    return await _post(client, url, headers, retries=retries, json=payload)


async def post_multipart(client: httpx.AsyncClient, url: str, data: dict[str, Any], files: dict[str, Any],
                         headers: dict[str, str], *, retries: int = 1) -> dict[str, Any]:
    """multipart/form-data (file uploads such as audio for transcription)."""
    return await _post(client, url, headers, retries=retries, data=data, files=files)


async def _post(client: httpx.AsyncClient, url: str, headers: dict[str, str], *, retries: int,
                **body: Any) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            response = await client.post(url, headers=headers, **body)
        except httpx.TimeoutException as exc:
            if attempt < retries:
                attempt += 1
                await asyncio.sleep(1.5 * attempt)
                continue
            raise AIError("ai_timeout", status=504) from exc
        except httpx.TransportError as exc:
            if attempt < retries:
                attempt += 1
                await asyncio.sleep(1.5 * attempt)
                continue
            raise AIError("ai_unavailable", status=503, detail=type(exc).__name__) from exc
        quota = response.status_code == 429 and any(
            code in response.text[:400].lower() for code in ("insufficient_quota", "credit_balance", "spend_limit"))
        if response.status_code in RETRY_STATUSES and attempt < retries and not quota:
            attempt += 1
            await asyncio.sleep(min(30.0, _retry_delay(response, attempt)) + random.uniform(0, 0.5))  # noqa: S311
            continue
        if response.status_code >= 400:
            raise status_to_error(response.status_code, response.text)
        try:
            data = response.json()
        except ValueError as exc:
            raise AIError("ai_bad_response", status=502, detail="Svaret var ikke JSON") from exc
        if not isinstance(data, dict):
            raise AIError("ai_bad_response", status=502, detail="Uventet svarformat")
        return data


async def get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> Any:
    try:
        response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise AIError("ai_timeout", status=504) from exc
    except httpx.TransportError as exc:
        raise AIError("ai_unavailable", status=503, detail=type(exc).__name__) from exc
    if response.status_code >= 400:
        raise status_to_error(response.status_code, response.text)
    try:
        return response.json()
    except ValueError as exc:
        raise AIError("ai_bad_response", status=502, detail="Svaret var ikke JSON") from exc


def parse_json_text(text: str) -> dict[str, Any]:
    """Parse a JSON object returned as text (tolerates code fences)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise AIError("ai_bad_response", status=502, detail="Modellen returnerte ikke JSON") from None
        try:
            data = json.loads(text[start: end + 1])
        except json.JSONDecodeError as exc:
            raise AIError("ai_bad_response", status=502, detail="Ugyldig JSON fra modellen") from exc
    if not isinstance(data, dict):
        raise AIError("ai_bad_response", status=502, detail="JSON var ikke et objekt")
    return data


def rejects(error: AIError, *needles: str) -> bool:
    detail = (error.detail or "").lower()
    return error.code == "ai_bad_response" and detail.startswith("http 400") and any(n in detail for n in needles)
