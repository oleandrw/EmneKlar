"""Running document parsers in separate worker processes.

Document libraries have bugs; course files may be hostile or broken. Parsing therefore runs
in a small pool of *spawned* worker processes:

* each job has a timeout - a hung parser is killed and replaced;
* each worker has a memory cap (Windows Job Object / POSIX ``RLIMIT_AS``);
* a crashing worker cannot take down the web application;
* the protocol is JSON over a pipe in both directions - no pickle from the
  worker to the main process, so a compromised worker cannot inject objects;
* workers are recycled after a number of jobs.

Limitation (documented in THREAT_MODEL.md): workers run as the same OS user.
This contains crashes and resource exhaustion, but is not a full sandbox.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import multiprocessing
import os
import sys
import threading
from multiprocessing.connection import Connection
from typing import Any, Protocol

log = logging.getLogger(__name__)

MAX_RESULT_BYTES = 64 * 1024 * 1024

# Only these functions may run in a worker ("module:function"). Jobs are JSON: {"job": name, "args": {...}}.
ALLOWED_JOBS = {
    "inspect_document": "emneklar.features.accessibility.documents:inspect_document",
    "rag_convert": "emneklar.features.course_rag.convert.documents:convert_document",
    "rag_render_pdf": "emneklar.features.course_rag.convert.ocr:render_pdf_pages",
    "rag_image_prepare": "emneklar.features.course_rag.convert.imageprep:prepare_image",
    "rag_keyframes": "emneklar.features.course_rag.convert.imageprep:extract_keyframes",
}


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    target = ALLOWED_JOBS.get(str(job.get("job")))
    if target is None:
        return {"error": "unknown_job"}
    module_name, func_name = target.split(":")
    import importlib

    func = getattr(importlib.import_module(module_name), func_name)
    result = func(**dict(job.get("args") or {}))
    return result if isinstance(result, dict) else {"error": "bad_result"}


class ParserRunner(Protocol):
    async def run(self, job: dict[str, Any], timeout: float) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class InlineRunner:
    """Runs parsers in a thread of the main process (tests, or isolation disabled)."""

    async def run(self, job: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            async with asyncio.timeout(timeout):
                return await asyncio.to_thread(execute_job, job)
        except TimeoutError:
            return {"error": "timeout"}

    async def close(self) -> None:
        return None


# -- worker side ------------------------------------------------------------


def _apply_posix_limits(memory_mb: int) -> None:
    if sys.platform == "win32":
        return
    try:
        import resource

        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.nice(5)
    except Exception:  # noqa: BLE001, S110 - best effort
        pass


def quiet_worker_logging() -> None:
    """Keep document libraries' chatter out of the console window.

    A worker has no logging set up, so Python would print library warnings
    (e.g. pypdf's "fontTools is required to fully parse …" for every font) to
    the console the teacher started the program from. What matters for the
    teacher is returned as structured warnings in the parse result instead.
    """
    root = logging.getLogger()
    root.handlers = [logging.NullHandler()]
    root.setLevel(logging.ERROR)


def worker_main(conn: Connection, memory_mb: int) -> None:
    quiet_worker_logging()
    if sys.platform != "win32":
        _apply_posix_limits(memory_mb)
    while True:
        try:
            raw = conn.recv_bytes()
        except (EOFError, OSError):
            return
        try:
            job = json.loads(raw)
            result = execute_job(job)
        except MemoryError:
            result = {"error": "memory"}
        except Exception as exc:  # noqa: BLE001
            result = {"error": "exception", "detail": type(exc).__name__}
        try:
            conn.send_bytes(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        except (OSError, ValueError):
            return


# -- Windows memory limit via Job Object --------------------------------------


class _WindowsJob:
    """Assigns a process to a Job Object with a per-process memory limit.

    The job is created with KILL_ON_JOB_CLOSE, so workers die with the app.
    """

    _k32: Any
    _job: Any

    def __init__(self, memory_mb: int) -> None:
        if sys.platform != "win32":
            raise OSError("Job Objects finnes bare på Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError("CreateJobObject failed")
        info = EXTENDED()
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        )
        info.ProcessMemoryLimit = memory_mb * 1024 * 1024
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            raise OSError("SetInformationJobObject failed")
        self._job = job

    def assign(self, pid: int) -> None:
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        handle = self._k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not handle:
            raise OSError("OpenProcess failed")
        try:
            if not self._k32.AssignProcessToJobObject(self._job, handle):
                raise OSError("AssignProcessToJobObject failed")
        finally:
            self._k32.CloseHandle(handle)


# -- parent side ----------------------------------------------------------------


class _Worker:
    def __init__(self, memory_mb: int, job_object: _WindowsJob | None) -> None:
        ctx = multiprocessing.get_context("spawn")
        self.conn, child = ctx.Pipe(duplex=True)
        self.proc = ctx.Process(target=worker_main, args=(child, memory_mb), daemon=True, name="emneklar-parser")
        self.proc.start()
        child.close()
        self.jobs = 0
        if job_object is not None and self.proc.pid:
            try:
                job_object.assign(self.proc.pid)
            except OSError:
                log.warning("Kunne ikke sette minnegrense for parserprosess")

    def call(self, job: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.jobs += 1
        self.conn.send_bytes(json.dumps(job).encode("utf-8"))
        if not self.conn.poll(timeout):
            raise TimeoutError
        data = self.conn.recv_bytes(maxlength=MAX_RESULT_BYTES)
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("Unexpected worker response")
        return result

    @property
    def alive(self) -> bool:
        return self.proc.is_alive()

    def kill(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.close()
        with contextlib.suppress(Exception):
            self.proc.kill()
            self.proc.join(timeout=5)


class IsolatedWorkerPool:
    def __init__(self, size: int = 2, *, memory_mb: int = 1536, max_jobs_per_worker: int = 25) -> None:
        self.size = max(1, size)
        self.memory_mb = memory_mb
        self.max_jobs = max_jobs_per_worker
        self._idle: asyncio.Queue[_Worker] | None = None
        self._created = 0
        self._lock = threading.Lock()
        self._job_object: _WindowsJob | None = None
        if sys.platform == "win32":
            try:
                self._job_object = _WindowsJob(memory_mb)
            except OSError:
                log.warning("Job Object ikke tilgjengelig - parserprosesser kjører uten minnegrense")

    def _new_worker(self) -> _Worker:
        return _Worker(self.memory_mb, self._job_object)

    async def _acquire(self) -> _Worker:
        if self._idle is None:
            self._idle = asyncio.Queue()
        if not self._idle.empty():
            return self._idle.get_nowait()
        with self._lock:
            can_create = self._created < self.size
            if can_create:
                self._created += 1
        if can_create:
            try:
                return await asyncio.to_thread(self._new_worker)
            except Exception:
                with self._lock:
                    self._created -= 1
                raise
        return await self._idle.get()

    async def _release(self, worker: _Worker, healthy: bool) -> None:
        assert self._idle is not None
        if healthy and worker.alive and worker.jobs < self.max_jobs:
            self._idle.put_nowait(worker)
            return
        worker.kill()
        replacement = await asyncio.to_thread(self._new_worker)
        self._idle.put_nowait(replacement)

    async def run(self, job: dict[str, Any], timeout: float) -> dict[str, Any]:
        worker = await self._acquire()
        healthy = False
        try:
            result = await asyncio.to_thread(worker.call, job, timeout)
            healthy = True
            return result
        except TimeoutError:
            log.warning("Parserprosess brukte for lang tid og ble stoppet")
            return {"error": "timeout"}
        except (EOFError, OSError, BrokenPipeError):
            log.warning("Parserprosess krasjet")
            return {"error": "crashed"}
        except (ValueError, json.JSONDecodeError):
            return {"error": "bad_response"}
        finally:
            await self._release(worker, healthy)

    async def close(self) -> None:
        if self._idle is None:
            return
        while not self._idle.empty():
            self._idle.get_nowait().kill()
