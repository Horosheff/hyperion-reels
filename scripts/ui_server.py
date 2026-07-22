#!/usr/bin/env python3
"""Local VideoShorts UI bridge.

Serves the HTML UI on localhost and accepts the selected video + settings.
By default it prepares a READY_FOR_AGENT request for Cursor Director; the
direct Python pipeline is kept as an explicit local diagnostic fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from profile_system import PROFILE_PATH, build_profile

try:
    from ensure_dependencies import ensure_dependencies
except ImportError:
    ensure_dependencies = None  # type: ignore[assignment]


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
UI_DIR = PLUGIN_ROOT / "ui"
MEMORY_ROOT = PLUGIN_ROOT / "videoshorts-memory"
INPUT_DIR = MEMORY_ROOT / "input"
OUTPUT_DIR = MEMORY_ROOT / "output"
LOG_DIR = OUTPUT_DIR / "logs"
BRIEF_PATH = MEMORY_ROOT / "00-brief.md"
HANDOFF_PATH = PLUGIN_ROOT / ".cursor" / "videoshorts-handoff.md"
RUN_REQUEST_PATH = MEMORY_ROOT / "run-request.json"
RUN_STATUS_PATH = OUTPUT_DIR / "run-status.json"
LATEST_RESULTS_PATH = OUTPUT_DIR / "latest-results.json"
DEFAULT_RUN_MODE = "agent"
AGENT_CHAIN = [
    "videoshorts-system-profiler",
    "videoshorts-intake",
    "videoshorts-transcriber",
    "videoshorts-cleanup-planner",
    "videoshorts-moment-finder",
    "videoshorts-scorekeeper",
    "videoshorts-boundary-refiner",
    "videoshorts-cutter",
    "videoshorts-audio-polisher",
    "videoshorts-subtitle-writer",
    "videoshorts-subtitle-burner",
    "videoshorts-guardian",
    "videoshorts-metadata-writer",
    "videoshorts-packager",
]


class MultipartStream:
    def __init__(self, handler: BaseHTTPRequestHandler, boundary: bytes) -> None:
        self.rfile = handler.rfile
        self.boundary = b"--" + boundary
        self.remaining = int(handler.headers.get("Content-Length", "0") or "0")
        self.pending = b""

    def _read_raw(self, size: int = 1024 * 1024) -> bytes:
        if self.remaining <= 0:
            return b""
        chunk = self.rfile.read(min(size, self.remaining))
        self.remaining -= len(chunk)
        return chunk

    def readline(self) -> bytes:
        while b"\n" not in self.pending and self.remaining > 0:
            self.pending += self._read_raw(64 * 1024)
        if b"\n" in self.pending:
            idx = self.pending.index(b"\n") + 1
            line = self.pending[:idx]
            self.pending = self.pending[idx:]
            return line
        line = self.pending
        self.pending = b""
        return line

    def read_until_boundary(self, writer) -> bool:
        delimiter = b"\r\n" + self.boundary
        keep = len(delimiter) + 8
        buffer = self.pending
        self.pending = b""
        while True:
            idx = buffer.find(delimiter)
            if idx != -1:
                if idx:
                    writer(buffer[:idx])
                self.pending = buffer[idx + 2 :]
                line = self.readline()
                return line.startswith(self.boundary + b"--")
            if self.remaining <= 0:
                if buffer:
                    writer(buffer)
                return True
            if len(buffer) > keep:
                writer(buffer[:-keep])
                buffer = buffer[-keep:]
            buffer += self._read_raw()


def parse_content_disposition(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        result[key.strip().lower()] = raw.strip().strip('"')
    return result


def read_multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], Path | None]:
    content_type = handler.headers.get("Content-Type", "")
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("multipart boundary not found")
    boundary = match.group("boundary").strip().strip('"').encode("utf-8")
    stream = MultipartStream(handler, boundary)

    first = stream.readline().strip()
    if first != b"--" + boundary:
        raise ValueError("invalid multipart payload")

    fields: dict[str, str] = {}
    saved_video: Path | None = None
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    final = False
    while not final:
        headers: dict[str, str] = {}
        while True:
            line = stream.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
            decoded = line.decode("utf-8", errors="replace")
            if ":" in decoded:
                key, value = decoded.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        disposition = parse_content_disposition(headers.get("content-disposition", ""))
        name = disposition.get("name", "")
        filename = disposition.get("filename", "")

        if filename:
            target = INPUT_DIR / safe_filename(filename)
            with target.open("wb") as out:
                final = stream.read_until_boundary(out.write)
            saved_video = target.resolve()
        else:
            chunks: list[bytes] = []
            final = stream.read_until_boundary(chunks.append)
            fields[name] = b"".join(chunks).decode("utf-8", errors="replace")

    return fields, saved_video


def safe_filename(name: str) -> str:
    cleaned = Path(name or "source.mp4").name
    cleaned = re.sub(r"[^\w.\-() А-Яа-яЁё]+", "_", cleaned, flags=re.UNICODE)
    return cleaned or "source.mp4"


def parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on", "да"}


def read_latest_results() -> dict | None:
    if not LATEST_RESULTS_PATH.is_file():
        return None
    try:
        return json.loads(LATEST_RESULTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def merge_status_with_results(status: dict) -> dict:
    merged = dict(status)
    latest = read_latest_results()
    if latest:
        merged["latest_results_path"] = str(LATEST_RESULTS_PATH)
        merged["latest_results_status"] = latest.get("status")
        merged["latest_results_updated_at"] = latest.get("updated_at")
        totals = latest.get("totals") or {}
        merged["latest_results_totals"] = totals
    return merged


def reset_to_waiting_for_upload(reason: str = "new_ui_session") -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    if RUN_REQUEST_PATH.exists():
        RUN_REQUEST_PATH.unlink()
    status = {
        "status": "WAITING_FOR_UPLOAD",
        "run_mode": DEFAULT_RUN_MODE,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
        "message": "Откройте UI, выберите новый файл и нажмите OK — передать Cursor Director.",
    }
    RUN_STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    BRIEF_PATH.write_text(
        "# VideoShorts brief\n\n"
        f"created_at: {status['created_at']}\n"
        "status: WAITING_FOR_UPLOAD\n"
        "video_path: (not selected)\n",
        encoding="utf-8",
    )
    HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    HANDOFF_PATH.write_text(
        "# VideoShorts — новая сессия\n\n"
        "status: WAITING_FOR_UPLOAD\n"
        "director_action: ждать новый READY_FOR_AGENT из UI, не использовать старые run-request/latest-results\n",
        encoding="utf-8",
    )
    return status


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def build_command(video_path: Path, settings: dict) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_pipeline.py"),
        str(video_path),
        "-c",
        str(settings.get("clips") or 10),
        "--min",
        str(settings.get("minSec") or 30),
        "--max",
        str(settings.get("maxSec") or 60),
        "-m",
        str(settings.get("model") or "base"),
        "--template",
        str(settings.get("template") or "mrbeast"),
        "--profile",
        str(settings.get("profile") or "webinar"),
        "--subtitle-format",
        str(settings.get("subtitleFormat") or "both"),
        "--memory-root",
        str(MEMORY_ROOT),
        "--quality-preset",
        str(settings.get("qualityPreset") or "release"),
    ]

    language = str(settings.get("language") or "").strip()
    if language:
        cmd += ["--language", language]
    if str(settings.get("device") or "gpu") == "cpu":
        cmd.append("--force-cpu")
    cmd.append("--word-timestamps" if parse_bool(settings.get("wordTimestamps"), True) else "--no-word-timestamps")
    if not parse_bool(settings.get("subtitles"), True):
        cmd.append("--skip-subtitles")
    if not parse_bool(settings.get("burn"), True):
        cmd.append("--no-burn")
    if not parse_bool(settings.get("qa"), True):
        cmd.append("--no-qa")
    if not parse_bool(settings.get("publishBundle"), True):
        cmd.append("--no-publish-bundle")
    if parse_bool(settings.get("progressBar")):
        cmd.append("--progress-bar")
    if parse_bool(settings.get("zoomPunch")):
        cmd.append("--zoom-punch")
    if parse_bool(settings.get("bRoll")):
        cmd.append("--b-roll")
        cmd += ["--b-roll-max", str(broll_max(settings.get("bRollMax")))]
    if parse_bool(settings.get("hookStyle")):
        cmd.append("--subtitles-hook-style")
    if parse_bool(settings.get("emojiSubtitles")):
        cmd.append("--emoji-subtitles")
    return cmd


def normalize_run_mode(value: object) -> str:
    mode = str(value or DEFAULT_RUN_MODE).strip().lower()
    return mode if mode in {"agent", "local"} else DEFAULT_RUN_MODE


def broll_max(value: object) -> int:
    try:
        return max(1, min(3, int(value or 3)))
    except (TypeError, ValueError):
        return 3


def write_brief(video_path: Path, settings: dict, command: list[str], log_path: Path, run_mode: str, status: str) -> None:
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    lines = [
        "# VideoShorts brief",
        "",
        f"created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"status: {status}",
        f"run_mode: {run_mode}",
        f"video_path: {video_path}",
        f"clip_count: {settings.get('clips', 10)}",
        f"min_sec: {settings.get('minSec', 30)}",
        f"max_sec: {settings.get('maxSec', 60)}",
        f"whisper_model: {settings.get('model', 'base')}",
        f"language: {settings.get('language') or 'auto'}",
        f"subtitle_template: {settings.get('template', 'mrbeast')}",
        f"metadata_profile: {settings.get('profile', 'webinar')}",
        f"subtitle_format: {settings.get('subtitleFormat', 'both')}",
        f"quality_preset: {settings.get('qualityPreset', 'release')}",
        f"word_timestamps: {parse_bool(settings.get('wordTimestamps'), True)}",
        f"subtitles_enable: {parse_bool(settings.get('subtitles'), True)}",
        f"burn: {parse_bool(settings.get('burn'), True)}",
        f"qa: {parse_bool(settings.get('qa'), True)}",
        f"publish_bundle: {parse_bool(settings.get('publishBundle'), True)}",
        f"progressBar: {parse_bool(settings.get('progressBar'), False)}",
        f"zoomPunch: {parse_bool(settings.get('zoomPunch'), False)}",
        f"bRoll: {parse_bool(settings.get('bRoll'), False)}",
        f"bRollMax: {broll_max(settings.get('bRollMax'))}",
        f"log_path: {log_path}",
        "agent_chain: " + " -> ".join(AGENT_CHAIN),
        "",
        "diagnostic_local_command:",
        subprocess.list2cmdline(command),
        "",
    ]
    BRIEF_PATH.write_text("\n".join(lines), encoding="utf-8")
    HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    if run_mode == "agent":
        handoff_status = "READY_FOR_AGENT"
        director_action = "запускать Task-цепочку, не scripts/run_pipeline.py"
    else:
        handoff_status = status
        director_action = "локальная диагностика без Cursor subagents"
    HANDOFF_PATH.write_text(
        "# VideoShorts — новая сессия\n\n"
        f"status: {handoff_status}\n"
        "brief: videoshorts-memory/00-brief.md\n"
        "run_request: videoshorts-memory/run-request.json\n"
        f"director_action: {director_action}\n",
        encoding="utf-8",
    )


def prepare_agent_request(video_path: Path, settings: dict) -> dict:
    profile = build_profile()
    deps = profile.get("dependencies") or {}
    if not deps.get("ready") and ensure_dependencies is not None:
        dep_report = ensure_dependencies(install=True)
        profile = build_profile()
        deps = profile.get("dependencies") or dep_report
    if not deps.get("ready"):
        missing = ", ".join(deps.get("missing_required") or []) or "неизвестные зависимости"
        raise RuntimeError(
            f"Зависимости VideoShorts не готовы: {missing}. "
            "Запустите python scripts/ensure_dependencies.py --install или bootstrap-videoshorts.ps1"
        )
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    settings = {**settings, "system_profile": profile}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"agent-{timestamp}-{video_path.stem}.log"
    command = build_command(video_path, settings)
    write_brief(video_path, settings, command, log_path, "agent", "READY_FOR_AGENT")

    request = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "READY_FOR_AGENT",
        "run_mode": "agent",
        "agent_mode_env": {"VIDEOSHORTS_AGENT_MODE": "1"},
        "video_path": str(video_path),
        "settings": settings,
        "agent_chain": AGENT_CHAIN,
        "diagnostic_local_command": command,
        "note": "HTML bridge не запускает scripts/run_pipeline.py в agent mode. Cursor Director должен запустить Task-цепочку с VIDEOSHORTS_AGENT_MODE=1. Cutter/QA/Packager блокируют local_heuristic_draft.",
        "status_path": str(RUN_STATUS_PATH),
        "brief_path": str(BRIEF_PATH),
        "handoff_path": str(HANDOFF_PATH),
    }
    RUN_REQUEST_PATH.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

    status = {
        "status": "READY_FOR_AGENT",
        "run_mode": "agent",
        "created_at": request["created_at"],
        "video_path": str(video_path),
        "settings": settings,
        "agent_chain": AGENT_CHAIN,
        "brief_path": str(BRIEF_PATH),
        "run_request_path": str(RUN_REQUEST_PATH),
        "handoff_path": str(HANDOFF_PATH),
        "latest_results_path": str(OUTPUT_DIR / "latest-results.json"),
        "message": "Передано в Cursor Director. Ожидается запуск Task-цепочки VideoShorts.",
    }
    RUN_STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def start_local_pipeline(video_path: Path, settings: dict) -> dict:
    profile = build_profile()
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    settings = {**settings, "system_profile": profile}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"local-{timestamp}-{video_path.stem}.log"
    command = build_command(video_path, settings)
    write_brief(video_path, settings, command, log_path, "local", "LOCAL_RUNNING")

    request = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "LOCAL_RUNNING",
        "run_mode": "local",
        "video_path": str(video_path),
        "settings": settings,
        "command": command,
        "log_path": str(log_path),
        "status_path": str(RUN_STATUS_PATH),
        "note": "Диагностический backend-режим без Cursor subagents.",
    }
    RUN_REQUEST_PATH.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

    runner_command = [
        sys.executable,
        str(SCRIPTS_DIR / "run_with_status.py"),
        "--status",
        str(RUN_STATUS_PATH),
        "--log",
        str(log_path),
        "--cwd",
        str(PLUGIN_ROOT),
        "--",
        *command,
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        runner_command,
        cwd=str(PLUGIN_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    status = {
        "status": "LOCAL_RUNNING",
        "run_mode": "local",
        "pid": process.pid,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "video_path": str(video_path),
        "settings": settings,
        "command": command,
        "runner_command": runner_command,
        "log_path": str(log_path),
        "brief_path": str(BRIEF_PATH),
        "latest_results_path": str(OUTPUT_DIR / "latest-results.json"),
    }
    RUN_STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def start_request(video_path: Path, settings: dict) -> dict:
    run_mode = normalize_run_mode(settings.get("runMode"))
    settings = {**settings, "runMode": run_mode}
    if run_mode == "local":
        return start_local_pipeline(video_path, settings)
    return prepare_agent_request(video_path, settings)


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoShortsUI/0.1"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[ui] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/", "/upload", "/upload.html", "/videoshorts-upload.html"}:
            self.serve_file(UI_DIR / "videoshorts-upload.html", "text/html; charset=utf-8")
            return
        if path in {"/results", "/results.html", "/videoshorts-results.html"}:
            self.serve_file(UI_DIR / "videoshorts-results.html", "text/html; charset=utf-8")
            return
        if path == "/api/status":
            data = json.loads(RUN_STATUS_PATH.read_text(encoding="utf-8")) if RUN_STATUS_PATH.is_file() else {"status": "IDLE"}
            json_response(self, merge_status_with_results(data))
            return
        if path == "/api/config":
            from quality_presets import PRESETS, DEFAULT_PRESET

            json_response(self, {
                "ok": True,
                "project_root": str(PLUGIN_ROOT.resolve()),
                "input_dir": str(INPUT_DIR.resolve()),
                "input_dir_rel": "videoshorts-memory/input",
                "memory_root": str(MEMORY_ROOT.resolve()),
                "quality_presets": PRESETS,
                "default_quality_preset": DEFAULT_PRESET,
                "agent_mode_env": "VIDEOSHORTS_AGENT_MODE=1",
            })
            return
        if path == "/api/new-session":
            json_response(self, reset_to_waiting_for_upload("new_ui_session"))
            return
        if path == "/api/latest-results":
            latest = read_latest_results()
            if latest is None:
                json_response(self, {"ok": False, "error": "latest-results.json не найден.", "path": str(LATEST_RESULTS_PATH)}, status=404)
                return
            json_response(self, {"ok": True, "path": str(LATEST_RESULTS_PATH), "data": latest})
            return
        if path == "/api/media":
            query = parse_qs(parsed.query)
            raw_path = query.get("path", [""])[0]
            self.serve_media(Path(raw_path))
            return
        if path == "/api/profile":
            try:
                profile = build_profile()
                PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
                PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
                json_response(self, {"ok": True, "profile_path": str(PROFILE_PATH), **profile})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/dependencies":
            if ensure_dependencies is None:
                json_response(self, {"ok": False, "error": "ensure_dependencies.py недоступен"}, status=500)
                return
            try:
                report = ensure_dependencies(install=False)
                json_response(self, {"ok": True, **report})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return
        if path.startswith("/ui/"):
            self.serve_file(UI_DIR / path.removeprefix("/ui/"), self.guess_content_type(path))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/dependencies":
            if ensure_dependencies is None:
                json_response(self, {"ok": False, "error": "ensure_dependencies.py недоступен"}, status=500)
                return
            try:
                report = ensure_dependencies(install=True)
                json_response(self, {"ok": True, **report})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return
        if path != "/api/start":
            self.send_error(404)
            return
        try:
            fields, saved_video = read_multipart(self)
            settings_raw = fields.get("settings") or "{}"
            settings = json.loads(settings_raw)

            video_path: Path | None = saved_video
            if video_path is None:
                candidate = Path(str(settings.get("videoPath") or "")).expanduser()
                if candidate.is_file():
                    video_path = candidate.resolve()

            if not video_path or not video_path.is_file():
                json_response(self, {"ok": False, "error": "Видео не получено и путь к файлу не найден."}, status=400)
                return

            status = start_request(video_path, settings)
            json_response(self, {"ok": True, **status})
        except Exception as exc:
            json_response(self, {"ok": False, "error": str(exc)}, status=500)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def serve_file(self, path: Path, content_type: str) -> None:
        try:
            resolved = path.resolve()
            if not str(resolved).startswith(str(PLUGIN_ROOT.resolve())) or not resolved.is_file():
                self.send_error(404)
                return
            body = resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            self.send_error(404)

    def serve_media(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            memory_root = MEMORY_ROOT.resolve()
            if not str(resolved).startswith(str(memory_root)) or not resolved.is_file():
                self.send_error(404)
                return

            file_size = resolved.stat().st_size
            range_header = self.headers.get("Range")
            start = 0
            end = file_size - 1
            status = 200
            if range_header:
                match = re.match(r"bytes=(\d*)-(\d*)", range_header)
                if match:
                    if match.group(1):
                        start = int(match.group(1))
                    if match.group(2):
                        end = min(int(match.group(2)), file_size - 1)
                    status = 206
            if start > end or start >= file_size:
                self.send_error(416)
                return

            chunk_size = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(chunk_size))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.end_headers()
            with resolved.open("rb") as fh:
                fh.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    chunk = fh.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    self.wfile.write(chunk)
        except OSError:
            self.send_error(404)

    @staticmethod
    def guess_content_type(path: str) -> str:
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        if path.endswith(".js"):
            return "text/javascript; charset=utf-8"
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        return "application/octet-stream"


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts local HTML bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"VideoShorts UI: {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        time.sleep(0.2)
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
