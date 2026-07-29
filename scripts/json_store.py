#!/usr/bin/env python3
"""Atomic JSON storage with an optional cross-process advisory lock.

All shared state files (publish-queue.json, latest-results.json, run-status.json)
can be written concurrently by parallel publisher subprocesses and the UI server.
Plain ``Path.write_text`` is not atomic and leaves corrupted half-written files
when two writers collide. This module provides:

- ``read_json`` — tolerant read (utf-8 / utf-8-sig), never raises on bad JSON.
- ``write_json`` / ``write_text_atomic`` — write via sibling tmp + ``os.replace``.
- ``file_lock`` — cross-process advisory lock (msvcrt on Windows, fcntl elsewhere).
- ``update_json`` — locked read-modify-write for dict-shaped state files.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl  # type: ignore[import-not-found]

LOCK_TIMEOUT_SEC = float(os.getenv("VIDEOSHORTS_JSON_LOCK_TIMEOUT", "15"))

_MISSING = object()


def read_json(path: Path, default: Any = _MISSING) -> Any:
    path = Path(path)
    fallback = {} if default is _MISSING else default
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return fallback


def _tmp_path_for(path: Path) -> Path:
    return path.with_name(f"{path.name}.{os.getpid()}.tmp")


def write_json(path: Path, data: Any, *, indent: int = 2) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path_for(path)
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
    return path


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path_for(path)
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
    return path


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = LOCK_TIMEOUT_SEC) -> Iterator[Path]:
    """Advisory cross-process lock using a sibling ``<name>.lock`` file.

    The lock is released on context exit. Raises TimeoutError if the lock
    cannot be acquired within ``timeout`` seconds.
    """

    path = Path(path)
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        fh.seek(0)
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Не удалось получить lock: {lock_path}")
                time.sleep(0.05)
        yield lock_path
    finally:
        with contextlib.suppress(OSError):
            fh.seek(0)
            if os.name == "nt":
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def update_json(
    path: Path,
    mutator: Callable[[Any], Any],
    *,
    default: Any = None,
    lock: bool = True,
    timeout: float = LOCK_TIMEOUT_SEC,
) -> Any:
    """Read JSON, apply ``mutator`` and write back atomically.

    ``mutator`` receives the current value (or ``default``/``{}`` when missing)
    and returns the value to persist. Returning ``None`` keeps the mutated
    in-place object.
    """

    path = Path(path)

    def _apply() -> Any:
        data = read_json(path, default)
        result = mutator(data)
        value = data if result is None else result
        write_json(path, value)
        return value

    if lock:
        with file_lock(path, timeout=timeout):
            return _apply()
    return _apply()
