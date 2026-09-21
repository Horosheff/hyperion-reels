"""Minimal TypeSafe System One HTTP client (Jev). Keys are never logged."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
SYSTEM_ONE_PATH = "/v1/systemone"


class TypeSafeApiError(RuntimeError):
    """User-safe TypeSafe error (no secrets in message)."""


def jev_scores_enabled(env: dict[str, str] | None = None) -> bool:
    """True when VIDEOSHORTS_JEV_SCORES is 1/true/yes/on."""
    source = env if env is not None else os.environ
    value = str(source.get("VIDEOSHORTS_JEV_SCORES", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def load_typesafe_api_key(plugin_root: Path | None = None) -> str | None:
    """Read TYPESAFE_API_KEY from env or non-committed videoshorts.local.env."""
    value = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if value:
        return value
    root = plugin_root or Path(__file__).resolve().parents[1]
    env_file = root / "videoshorts.local.env"
    if not env_file.is_file():
        return None
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        if key.strip() == "TYPESAFE_API_KEY":
            return raw_value.strip().strip("\"'")
    return None


class TypeSafeClient:
    """POST /v1/systemone with injectable opener for unit tests."""

    def __init__(
        self,
        api_key: str,
        *,
        opener: Callable[..., Any] = urlopen,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        if not api_key.strip():
            raise ValueError("TYPESAFE_API_KEY пуст")
        self._api_key = api_key.strip()
        self._opener = opener
        self._base_url = (base_url or os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._model = model or os.environ.get("TYPESAFE_DEFAULT_MODEL") or DEFAULT_MODEL
        self._timeout = timeout

    def system_one(self, state: Any, questions: dict[str, dict]) -> dict:
        body = {
            "state": state,
            "model": self._model,
            "questions": questions,
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self._base_url}{SYSTEM_ONE_PATH}",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise TypeSafeApiError("TypeSafe API: неверный или отсутствующий ключ") from exc
            if exc.code == 422:
                raise TypeSafeApiError("TypeSafe API: невалидный запрос (422)") from exc
            if exc.code in {429, 529}:
                raise TypeSafeApiError(f"TypeSafe API: лимит/перегрузка (HTTP {exc.code})") from exc
            raise TypeSafeApiError(f"TypeSafe API недоступен (HTTP {exc.code})") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TypeSafeApiError("Не удалось связаться с TypeSafe API") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TypeSafeApiError("TypeSafe API вернул некорректный JSON") from exc
        if not isinstance(data, dict):
            raise TypeSafeApiError("TypeSafe API вернул неожиданный ответ")
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise TypeSafeApiError("TypeSafe API: нет answers в ответе")
        return data
