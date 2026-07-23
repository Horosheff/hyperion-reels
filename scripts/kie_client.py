"""Минимальный клиент Kie task API для B-roll и AI-обложек; ключи не логируются."""
from __future__ import annotations

import json
import mimetypes
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = "https://api.kie.ai/api/v1/jobs"
FILE_UPLOAD_ROOT = "https://kieai.redpandaai.co"


class KieApiError(RuntimeError):
    """Ошибка Kie, пригодная для пользовательского отчёта без раскрытия ключа."""


def load_api_key(plugin_root: Path | None = None) -> str | None:
    """Берёт ключ из окружения либо из некоммитимого videoshorts.local.env."""
    value = os.environ.get("KIE_API_KEY", "").strip()
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
        if key.strip() == "KIE_API_KEY":
            return raw_value.strip().strip("\"'")
    return None


class KieClient:
    def __init__(self, api_key: str, *, opener=urlopen, sleep=time.sleep, api_root: str = API_ROOT):
        if not api_key.strip():
            raise ValueError("KIE_API_KEY пуст")
        self._api_key = api_key.strip()
        self._opener = opener
        self._sleep = sleep
        self._api_root = api_root.rstrip("/")

    def _request_json(self, request: Request) -> dict:
        try:
            with self._opener(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 402, 422, 429}:
                raise KieApiError(f"Kie API HTTP {exc.code}") from exc
            raise KieApiError(f"Kie API недоступен (HTTP {exc.code})") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise KieApiError("Не удалось получить корректный ответ Kie API") from exc
        if not isinstance(payload, dict):
            raise KieApiError("Kie API вернул некорректный JSON")
        if payload.get("code") != 200:
            raise KieApiError(f"Kie API отклонил задачу: {payload.get('msg') or payload.get('code')}")
        return payload

    def create_task(self, model: str, input_data: dict) -> str:
        body = json.dumps({"model": model, "input": input_data}, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self._api_root}/createTask",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
        )
        payload = self._request_json(request)
        task_id = payload.get("data", {}).get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise KieApiError("Kie API не вернул taskId")
        return task_id

    def get_task(self, task_id: str) -> dict:
        request = Request(
            f"{self._api_root}/recordInfo?{urlencode({'taskId': task_id})}",
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        data = self._request_json(request).get("data")
        if not isinstance(data, dict):
            raise KieApiError("Kie API не вернул данные задачи")
        return data

    def wait_for_result(self, task_id: str, *, timeout_sec: int = 600, poll_sec: float = 4.0) -> list[str]:
        deadline = time.monotonic() + timeout_sec
        delay = max(1.0, poll_sec)
        while time.monotonic() < deadline:
            record = self.get_task(task_id)
            state = record.get("state")
            if state == "success":
                try:
                    result = json.loads(record.get("resultJson") or "{}")
                    urls = result.get("resultUrls", [])
                except json.JSONDecodeError as exc:
                    raise KieApiError("Kie API вернул повреждённый resultJson") from exc
                if isinstance(urls, list) and all(isinstance(url, str) and url for url in urls):
                    return urls
                raise KieApiError("Задача Kie завершилась без resultUrls")
            if state == "fail":
                raise KieApiError(f"Kie task failed: {record.get('failCode') or ''} {record.get('failMsg') or ''}".strip())
            self._sleep(delay)
            delay = min(15.0, delay * 1.5)
        raise KieApiError(f"Истёк таймаут ожидания Kie task {task_id}")

    def generate_image(self, prompt: str, *, aspect_ratio: str = "9:16", resolution: str = "1K") -> tuple[str, list[str]]:
        task_id = self.create_task(
            "gpt-image-2-text-to-image",
            {"prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": resolution},
        )
        return task_id, self.wait_for_result(task_id)

    def generate_image_i2i(
        self,
        prompt: str,
        input_urls: list[str],
        *,
        aspect_ratio: str = "9:16",
        resolution: str = "1K",
    ) -> tuple[str, list[str]]:
        urls = [u for u in input_urls if isinstance(u, str) and u.startswith("http")]
        if not urls:
            raise KieApiError("input_urls пуст — нужен HTTPS референс для image-to-image")
        task_id = self.create_task(
            "gpt-image-2-image-to-image",
            {
                "prompt": prompt,
                "input_urls": urls[:16],
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
            },
        )
        return task_id, self.wait_for_result(task_id)

    def upload_file(self, local_path: Path, *, upload_path: str = "videoshorts/covers") -> str:
        """Загрузка локального файла на Kie CDN (stream multipart) → HTTPS URL для input_urls."""
        path = Path(local_path)
        if not path.is_file():
            raise KieApiError(f"Файл для upload не найден: {path.name}")
        try:
            import requests
        except ImportError as exc:
            raise KieApiError("Для upload нужен пакет requests: pip install requests") from exc

        mime, _ = mimetypes.guess_type(path.name)
        mime = mime or "application/octet-stream"
        try:
            with path.open("rb") as fh:
                response = requests.post(
                    f"{FILE_UPLOAD_ROOT}/api/file-stream-upload",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": (path.name, fh, mime)},
                    data={"uploadPath": upload_path, "fileName": path.name},
                    timeout=300,
                )
        except requests.RequestException as exc:
            raise KieApiError("Не удалось загрузить файл на Kie CDN") from exc
        if response.status_code >= 400:
            raise KieApiError(f"Kie upload HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise KieApiError("Kie upload вернул некорректный JSON") from exc
        if not isinstance(payload, dict):
            raise KieApiError("Kie upload вернул некорректный JSON")
        if not payload.get("success") and payload.get("code") != 200:
            raise KieApiError(f"Kie upload отклонён: {payload.get('msg') or payload.get('code')}")
        data = payload.get("data") or {}
        url = data.get("fileUrl") or data.get("downloadUrl")
        if not isinstance(url, str) or not url.startswith("http"):
            raise KieApiError("Kie upload не вернул fileUrl")
        return url

    def generate_video(self, prompt: str, image_url: str) -> tuple[str, list[str]]:
        task_id = self.create_task(
            "grok-imagine-video-1-5-preview",
            {
                "prompt": prompt,
                "image_urls": [image_url],
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "duration": 3,
                "nsfw_checker": True,
            },
        )
        return task_id, self.wait_for_result(task_id)

    def download(self, url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": "VideoShorts B-roll"})
        try:
            with self._opener(request, timeout=90) as response:
                target.write_bytes(response.read())
        except (HTTPError, URLError, TimeoutError) as exc:
            raise KieApiError("Не удалось скачать B-roll из Kie") from exc
