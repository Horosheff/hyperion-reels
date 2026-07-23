#!/usr/bin/env python3
"""Публикация клипа в Яндекс Дзен через встроенный Playwright dzen_client.

Всё внутри плагина Гиперион:
  scripts/dzen_client.py
  videoshorts-memory/secrets/dzen_storage_state.json
  videoshorts.local.env (секреты, не в git)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videoshorts_core import configure_stdio

configure_stdio()

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DZEN_CLIENT = PLUGIN_ROOT / "scripts" / "dzen_client.py"
DEFAULT_DZEN_CWD = PLUGIN_ROOT
DEFAULT_STORAGE = PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "dzen_storage_state.json"


def _load_local_env(root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for path in (root / "videoshorts.local.env", root / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_config(plugin_root: Path = PLUGIN_ROOT) -> dict:
    local = _load_local_env(plugin_root)
    client = Path(
        local.get("VIDEOSHORTS_DZEN_CLIENT")
        or os.environ.get("VIDEOSHORTS_DZEN_CLIENT")
        or DEFAULT_DZEN_CLIENT
    )
    if not client.is_absolute():
        client = (plugin_root / client).resolve()
    cwd = Path(
        local.get("VIDEOSHORTS_DZEN_CWD")
        or os.environ.get("VIDEOSHORTS_DZEN_CWD")
        or DEFAULT_DZEN_CWD
    )
    if not cwd.is_absolute():
        cwd = (plugin_root / cwd).resolve()
    storage = Path(
        local.get("STORAGE_STATE")
        or os.environ.get("STORAGE_STATE")
        or local.get("VIDEOSHORTS_DZEN_STORAGE")
        or os.environ.get("VIDEOSHORTS_DZEN_STORAGE")
        or DEFAULT_STORAGE
    )
    if not storage.is_absolute():
        storage = (plugin_root / storage).resolve()
    storage.parent.mkdir(parents=True, exist_ok=True)
    return {
        "client": client,
        "cwd": cwd,
        "storage": storage,
        "has_cookies": storage.is_file() and storage.stat().st_size > 100,
        "client_ok": client.is_file(),
        "channel": local.get("DZEN_CHANNEL_NAME") or os.environ.get("DZEN_CHANNEL_NAME") or "",
        "channel_url": local.get("DZEN_CHANNEL_URL") or os.environ.get("DZEN_CHANNEL_URL") or "",
        "plugin_root": str(plugin_root.resolve()),
    }


def build_env(cfg: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["HEADLESS"] = "false"
    # Не оставлять Chromium открытым — иначе Results UI ждёт ответа вечно
    env["KEEP_BROWSER_OPEN"] = "false"
    env["VIDEOSHORTS_FORCE_CLOSE_BROWSER"] = "1"
    env["STORAGE_STATE"] = str(Path(cfg["storage"]).resolve())
    local = _load_local_env(PLUGIN_ROOT)
    for key in (
        "DZEN_LOGIN",
        "DZEN_PASSWORD",
        "DZEN_CHANNEL_NAME",
        "DZEN_CHANNEL_URL",
        "KIE_API_KEY",
    ):
        if local.get(key):
            env[key] = local[key]
    if cfg.get("channel"):
        env["DZEN_CHANNEL_NAME"] = str(cfg["channel"])
    if cfg.get("channel_url"):
        env["DZEN_CHANNEL_URL"] = str(cfg["channel_url"])
    return env


def _normalize_tags(raw: object, *, limit: int = 5) -> list[str]:
    """Список тегов без #, без дублей. Дзен: максимум 5 чипов."""
    items: list[Any] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw.strip():
        items = [p for p in raw.replace(";", ",").split(",") if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for t in items:
        s = str(t).strip().lstrip("#").strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _tags_from_meta(meta: dict) -> str:
    cleaned = _normalize_tags(meta.get("hashtags") or meta.get("tags") or meta.get("seo_keywords") or [])
    return ", ".join(cleaned)


def _collect_hashtags(*sources: object) -> list[str]:
    for src in sources:
        tags = _normalize_tags(src, limit=5)
        if tags:
            return tags
    return []


def _zen_payload_from_item(item: dict, clips_dir: Path, index: int) -> dict:
    platforms = item.get("platforms") if isinstance(item.get("platforms"), dict) else {}
    for key in ("zen", "youtube", "instagram", "tiktok", "telegram", "vk"):
        job = platforms.get(key)
        if not isinstance(job, dict):
            continue
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        if not payload:
            continue
        tags = _collect_hashtags(
            payload.get("hashtags"),
            payload.get("tags"),
            payload.get("seo_keywords"),
        )
        title = str(payload.get("title") or "").strip()
        description = str(
            payload.get("description") or payload.get("caption") or ""
        ).strip()
        if title or description or tags:
            return {
                "title": title or str(item.get("title") or f"clip_{index:02d}"),
                "description": description,
                "hashtags": tags or _collect_hashtags(item.get("seo_keywords")),
            }

    meta = _read_json(clips_dir / "metadata" / f"clip_{index:02d}.metadata.json")
    yt = (meta.get("platforms") or {}).get("youtube") if isinstance(meta.get("platforms"), dict) else {}
    if not isinstance(yt, dict):
        yt = {}
    tags = _collect_hashtags(
        meta.get("hashtags"),
        yt.get("hashtags"),
        meta.get("seo_keywords"),
        item.get("seo_keywords"),
    )
    return {
        "title": str(meta.get("title") or item.get("title") or f"clip_{index:02d}"),
        "description": str(meta.get("description") or yt.get("description") or ""),
        "hashtags": tags,
    }


def _clip_payload(clips_dir: Path, index: int) -> dict:
    queue = _read_json(clips_dir / "publish-queue.json")
    queue_item: dict | None = None
    for item in queue.get("items") or []:
        if isinstance(item, dict) and int(item.get("index", -1)) == index:
            queue_item = item
            break

    covers = _read_json(clips_dir / "covers-manifest.json")
    cover = next(
        (
            c
            for c in covers.get("covers") or []
            if isinstance(c, dict) and int(c.get("index", -1)) == index and c.get("ok")
        ),
        {},
    )
    video = clips_dir / f"clip_{index:02d}.mp4"
    base = dict(queue_item) if queue_item else {"index": index}
    if not base.get("video"):
        base["video"] = str(video.resolve()) if video.is_file() else None
    if not base.get("cover") and cover.get("cover_path"):
        base["cover"] = cover.get("cover_path")
    if not base.get("title") and cover.get("cover_text"):
        base["title"] = cover.get("cover_text")

    zen_payload = _zen_payload_from_item(base, clips_dir, index)
    platforms = base.get("platforms") if isinstance(base.get("platforms"), dict) else {}
    platforms = dict(platforms)
    zen_job = platforms.get("zen") if isinstance(platforms.get("zen"), dict) else {
        "status": "pending",
        "adapter": "playwright:dzen",
    }
    zen_job = dict(zen_job)
    prev_payload = zen_job.get("payload") if isinstance(zen_job.get("payload"), dict) else {}
    zen_job["payload"] = {
        **prev_payload,
        **zen_payload,
        "hashtags": zen_payload.get("hashtags")
        or _collect_hashtags(prev_payload.get("hashtags")),
    }
    platforms["zen"] = zen_job
    base["platforms"] = platforms
    if not base.get("title"):
        base["title"] = zen_payload.get("title")
    return base


def run_dzen_client(cfg: dict, args: list[str], *, log_path: Path | None = None) -> dict:
    client = Path(cfg["client"])
    if not client.is_file():
        return {
            "ok": False,
            "error": (
                f"dzen_client not found: {client}. "
                "Ожидается scripts/dzen_client.py внутри плагина Гиперион."
            ),
        }
    cmd = [sys.executable, str(client), *args]
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(
        cmd,
        cwd=str(cfg["cwd"]),
        env=build_env(cfg),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "cmd": cmd[1:],
        "stdout": (result.stdout or "")[-8000:],
        "stderr": (result.stderr or "")[-4000:],
        "storage": str(Path(cfg["storage"]).resolve()),
        "client": str(client.resolve()),
        "cwd": str(Path(cfg["cwd"]).resolve()),
        "has_cookies_after": Path(cfg["storage"]).is_file() and Path(cfg["storage"]).stat().st_size > 100,
    }
    if log_path is not None:
        _write_json(log_path, payload)
    return payload


def status_payload(clips_dir: Path | None = None) -> dict:
    cfg = resolve_config()
    last_log = {}
    if clips_dir and clips_dir.is_dir():
        last_log = _read_json(clips_dir / "dzen-publish-log.json")
    return {
        "ok": True,
        "client_ok": cfg["client_ok"],
        "client": str(cfg["client"]),
        "cwd": str(cfg["cwd"]),
        "storage": str(cfg["storage"]),
        "has_cookies": cfg["has_cookies"],
        "channel": cfg.get("channel") or None,
        "channel_url": cfg.get("channel_url") or None,
        "channel_configured": bool(cfg["channel"]),
        "bundled": Path(cfg["client"]).resolve() == DEFAULT_DZEN_CLIENT.resolve(),
        "last": {
            "ok": last_log.get("ok"),
            "finished_at": last_log.get("finished_at"),
            "index": last_log.get("index"),
            "mode": last_log.get("mode"),
            "error": last_log.get("error"),
        } if last_log else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts → Яндекс Дзен (bundled Playwright)")
    parser.add_argument("clips_dir", type=Path, nargs="?", default=None)
    parser.add_argument("--index", type=int, default=None, help="Индекс клипа для публикации")
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    cfg = resolve_config()
    if args.status:
        print(json.dumps(status_payload(args.clips_dir), ensure_ascii=False, indent=2))
        return

    if args.login_only:
        log_path = (
            (args.clips_dir / "dzen-publish-log.json")
            if args.clips_dir
            else PLUGIN_ROOT / "videoshorts-memory" / "output" / "dzen-login-log.json"
        )
        print("🔐 Дзен: открываю браузер для входа (Playwright headed)…")
        result = run_dzen_client(cfg, ["--login-only"], log_path=log_path)
        result["mode"] = "login_only"
        _write_json(log_path, result)
        if result["ok"]:
            print("✅ Cookies сохранены:", cfg["storage"])
            sys.exit(0)
        print(result.get("stderr") or result.get("stdout") or "login failed", file=sys.stderr)
        sys.exit(1)

    if args.clips_dir is None or args.index is None:
        print("[ERROR] Нужны clips_dir и --index (или --login-only / --status)", file=sys.stderr)
        sys.exit(2)

    clips_dir = args.clips_dir
    if not clips_dir.is_dir():
        print(f"[ERROR] clips_dir not found: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    item = _clip_payload(clips_dir, args.index)
    video = item.get("video")
    cover = item.get("cover")
    zen_job = (item.get("platforms") or {}).get("zen") or {}
    payload = zen_job.get("payload") or {}
    title = str(payload.get("title") or item.get("title") or f"clip_{args.index:02d}")
    description = str(payload.get("description") or payload.get("caption") or "")
    tag_list = _normalize_tags(payload.get("hashtags") or [], limit=5)
    tags = ", ".join(tag_list)

    if not video or not Path(video).is_file():
        print(f"[ERROR] video missing for clip_{args.index:02d}", file=sys.stderr)
        sys.exit(3)
    if not cover or not Path(str(cover)).is_file():
        print(f"[ERROR] cover missing for clip_{args.index:02d} — сначала «Подготовить обложки»", file=sys.stderr)
        sys.exit(4)

    cli = [
        "--no-auto",
        "--video", str(video),
        "--title", title,
        "--description", description,
        "--cover", str(cover),
    ]
    if tags:
        cli.extend(["--tags", tags])
    else:
        print("[WARN] Теги пустые — проверьте metadata.hashtags / platforms.*.hashtags", file=sys.stderr)
    if args.draft:
        cli.append("--draft")

    log_path = clips_dir / "dzen-publish-log.json"
    print(f"📤 Дзен: clip_{args.index:02d} → {Path(video).name}")
    print(f"🏷 Теги ({len(tag_list)}): {tags or '—'}")
    print(f"📦 client={cfg['client']}")
    result = run_dzen_client(cfg, cli, log_path=None)
    result["mode"] = "draft" if args.draft else "publish"
    result["index"] = args.index
    result["video"] = str(video)
    result["cover"] = str(cover)
    result["title"] = title
    result["tags_sent"] = tag_list
    _write_json(log_path, result)

    queue_path = clips_dir / "publish-queue.json"
    queue = _read_json(queue_path)
    for entry in queue.get("items") or []:
        if isinstance(entry, dict) and int(entry.get("index", -1)) == args.index:
            platforms = entry.setdefault("platforms", {})
            zen = platforms.setdefault("zen", {"adapter": "playwright:dzen", "payload": {}})
            zen["status"] = "published" if result["ok"] and not args.draft else ("draft" if result["ok"] else "failed")
            zen["updated_at"] = datetime.now(timezone.utc).isoformat()
            zen["log"] = str(log_path.resolve())
            break
    if queue:
        _write_json(queue_path, queue)

    if result["ok"]:
        print("✅ Дзен:", "черновик" if args.draft else "опубликовано")
        try:
            from videoshorts_core import write_latest_results
            write_latest_results(clips_dir, status="PASS")
        except Exception as exc:
            print(f"[WARN] latest-results: {exc}", file=sys.stderr)
        sys.exit(0)
    print(result.get("stderr") or result.get("stdout") or "publish failed", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
