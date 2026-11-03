"""Secret storage in the operating system credential store.

Secrets (the Canvas API token and AI provider keys) are:

* stored only in the OS credential store (Windows Credential Manager via
  ``keyring``) – never in SQLite, settings files, the browser or logs;
* never returned by any API endpoint – the GUI only learns *whether* a secret
  is configured;
* registered with the redactor as soon as they are read, so they are masked
  if they ever end up in a log line or error message.
"""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod

from emneklar.core.errors import AppError
from emneklar.core.security.redaction import register_secret, unregister_secret

log = logging.getLogger(__name__)

# Not plain "EmneKlar": another implementation of the same specification stores its secrets under that name,
# and the Windows keyring backend re-saves an existing entry when a new one is added under the same service.
KEYRING_SERVICE = "EmneKlar-Claude"
CANVAS_TOKEN = "canvas_token"
MAX_SECRET_LENGTH = 2000  # Windows Credential Manager caps blobs at 2560 bytes
_NAME_RE = re.compile(r"^(canvas_token|ai_key:[a-z0-9_-]{1,40})$")


def ai_key_name(provider_id: str) -> str:
    return f"ai_key:{provider_id}"


class SecretStore(ABC):
    def __init__(self) -> None:
        self._cache: dict[str, str | None] = {}
        self._lock = threading.Lock()

    @abstractmethod
    def _get(self, name: str) -> str | None: ...

    @abstractmethod
    def _set(self, name: str, value: str) -> None: ...

    @abstractmethod
    def _delete(self, name: str) -> None: ...

    @staticmethod
    def _check_name(name: str) -> None:
        if not _NAME_RE.match(name):
            raise AppError("secret_invalid", detail="Ukjent navn på hemmelighet")

    def get(self, name: str) -> str | None:
        self._check_name(name)
        with self._lock:
            if name in self._cache:
                return self._cache[name]
        value = self._get(name)
        register_secret(value)
        with self._lock:
            self._cache[name] = value
        return value

    def has(self, name: str) -> bool:
        return bool(self.get(name))

    def set(self, name: str, value: str) -> None:
        self._check_name(name)
        value = (value or "").strip()
        if not value:
            raise AppError("secret_invalid", detail="Tom verdi")
        if len(value) > MAX_SECRET_LENGTH:
            raise AppError("secret_invalid", detail="Verdien er for lang")
        if any(c in value for c in "\r\n\x00"):
            raise AppError("secret_invalid", detail="Verdien inneholder ugyldige tegn")
        old = self.get(name)
        self._set(name, value)
        unregister_secret(old)
        register_secret(value)
        with self._lock:
            self._cache[name] = value
        log.info("Hemmelighet lagret: %s", name)

    def delete(self, name: str) -> None:
        self._check_name(name)
        old = self.get(name)
        self._delete(name)
        unregister_secret(old)
        with self._lock:
            self._cache[name] = None
        log.info("Hemmelighet slettet: %s", name)


class KeyringSecretStore(SecretStore):
    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        super().__init__()
        import keyring  # imported lazily so tests never touch the real keyring

        self._keyring = keyring
        self._service = service

    def _get(self, name: str) -> str | None:
        try:
            return self._keyring.get_password(self._service, name)
        except Exception as exc:
            raise AppError("secret_store_unavailable", status=500, detail=type(exc).__name__) from exc

    def _set(self, name: str, value: str) -> None:
        try:
            self._keyring.set_password(self._service, name, value)
        except Exception as exc:
            raise AppError("secret_store_unavailable", status=500, detail=type(exc).__name__) from exc

    def _delete(self, name: str) -> None:
        try:
            self._keyring.delete_password(self._service, name)
        except self._keyring.errors.PasswordDeleteError:
            return
        except Exception as exc:
            raise AppError("secret_store_unavailable", status=500, detail=type(exc).__name__) from exc

    def backend_name(self) -> str:
        try:
            return type(self._keyring.get_keyring()).__name__
        except Exception:  # noqa: BLE001
            return "ukjent"


class MemorySecretStore(SecretStore):
    """For tests and throw-away sessions. Secrets disappear when the process ends."""

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, str] = {}

    def _get(self, name: str) -> str | None:
        return self._data.get(name)

    def _set(self, name: str, value: str) -> None:
        self._data[name] = value

    def _delete(self, name: str) -> None:
        self._data.pop(name, None)

    def backend_name(self) -> str:
        return "minne (test)"


def create_secret_store(backend: str) -> SecretStore:
    return MemorySecretStore() if backend == "memory" else KeyringSecretStore()
