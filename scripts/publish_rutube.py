#!/usr/bin/env python3
"""Публикация клипа в RuTube Shorts через bundled Playwright rutube_client."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from videoshorts_core import configure_stdio

configure_stdio()

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT = PLUGIN_ROOT / "scripts" / "rutube_client.py"
DEFAULT_STORAGE = PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "rutube_storage_state.json"


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
        local.get("VIDEOSHORTS_RUTUBE_CLIENT")
        or os.environ.get("VIDEOSHORTS_RUTUBE_CLIENT")
        or DEFAULT_CLIENT
    )
    if not client.is_absolute():
        client = (plugin_root / client).resolve()
    storage = Path(
        local.get("VIDEOSHORTS_RUTUBE_STORAGE")
        or os.environ.get("VIDEOSHORTS_RUTUBE_STORAGE")
        or local.get("RUTUBE_STORAGE_STATE")
        or os.environ.get("RUTUBE_STORAGE_STATE")
        or DEFAULT_STORAGE
    )
    if not storage.is_absolute():
        storage = (plugin_root / storage).resolve()
    storage.parent.mkdir(parents=True, exist_ok=True)
    return {
        "client": client,
        "cwd": plugin_root,
        "storage": storage,
        "has_cookies": storage.is_file() and storage.stat().st_size > 100,
        "client_ok": client.is_file(),
        "channel_id": local.get("RUTUBE_CHANNEL_ID") or os.environ.get("RUTUBE_CHANNEL_ID") or "33566314",
        "channel_url": local.get("RUTUBE_CHANNEL_URL")
        or os.environ.get("RUTUBE_CHANNEL_URL")
        or "https://rutube.ru/channel/33566314/",
        "category": local.get("RUTUBE_CATEGORY")
        or os.environ.get("RUTUBE_CATEGORY")
        or "Технологии и интернет",
        "playlist": local.get("RUTUBE_PLAYLIST")
        or os.environ.get("RUTUBE_PLAYLIST")
        or "Вайбкодинг для бизнеса",
        "plugin_root": str(plugin_root.resolve()),
    }


def build_env(cfg: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["HEADLESS"] = "false"
    env["KEEP_BROWSER_OPEN"] = "false"
    env["VIDEOSHORTS_FORCE_CLOSE_BROWSER"] = "1"
    env["VIDEOSHORTS_RUTUBE_STORAGE"] = str(Path(cfg["storage"]).resolve())
    local = _load_local_env(PLUGIN_ROOT)
    for key in (
        "RUTUBE_CHANNEL_ID",
        "RUTUBE_CHANNEL_URL",
        "RUTUBE_CATEGORY",
        "RUTUBE_PLAYLIST",
        "KIE_API_KEY",
    ):
        if local.get(key):
            env[key] = local[key]
    env["RUTUBE_CHANNEL_ID"] = str(cfg["channel_id"])
    env["RUTUBE_CHANNEL_URL"] = str(cfg["channel_url"])
    env["RUTUBE_CATEGORY"] = str(cfg["category"])
    env["RUTUBE_PLAYLIST"] = str(cfg["playlist"])
    return env


def _normalize_tags(raw, *, limit: int = 15) -> list[str]:
    if isinstance(raw, str):
        items = [t.strip() for t in raw.replace(";", ",").split(",")]
    elif isinstance(raw, list):
        items = [str(t).strip() for t in raw]
    else:
        items = []
    out: list[str] = []
    for t in items:
        t = t.lstrip("#").strip()
        if t and t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


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
    meta_path = clips_dir / "metadata" / f"clip_{index:02d}.metadata.json"
    meta = _read_json(meta_path)
    video = clips_dir / f"clip_{index:02d}.mp4"
    base = dict(queue_item) if queue_item else {"index": index}
    if not base.get("video"):
        base["video"] = str(video.resolve()) if video.is_file() else None
    if not base.get("cover") and cover.get("cover_path"):
        base["cover"] = cover.get("cover_path")
    cover_local = clips_dir / "covers" / f"clip_{index:02d}_cover.jpg"
    if not base.get("cover") and cover_local.is_file():
        base["cover"] = str(cover_local.resolve())

    platforms = base.get("platforms") if isinstance(base.get("platforms"), dict) else {}
    platforms = dict(platforms)
    # Prefer rutube / zen / vk / generic metadata
    title = (
        base.get("title")
        or (meta.get("title") if isinstance(meta, dict) else None)
        or cover.get("cover_text")
        or f"clip_{index:02d}"
    )
    description = ""
    hashtags: list = []
    for key in ("rutube", "zen", "vk", "youtube", "telegram"):
        block = platforms.get(key) if isinstance(platforms.get(key), dict) else {}
        payload = block.get("payload") if isinstance(block.get("payload"), dict) else {}
        if not description:
            description = str(payload.get("description") or payload.get("caption") or "")
        if not hashtags:
            hashtags = payload.get("hashtags") or []
        if not base.get("title") and payload.get("title"):
            title = str(payload.get("title"))
    if isinstance(meta, dict):
        if not description:
            description = str(meta.get("description") or "")
        if not hashtags:
            hashtags = meta.get("hashtags") or []
        if meta.get("title"):
            title = str(meta.get("title"))

    base["title"] = title
    base["_description"] = description
    base["_hashtags"] = _normalize_tags(hashtags)
    if not base.get("cover") and cover.get("cover_path"):
        base["cover"] = cover.get("cover_path")
    return base


def _client_timeout() -> int:
    try:
        return max(120, int(os.getenv("VIDEOSHORTS_PUBLISH_CLIENT_TIMEOUT", "900")))
    except ValueError:
        return 900


def run_client(cfg: dict, args: list[str], *, log_path: Path | None = None) -> dict:
    client = Path(cfg["client"])
    if not client.is_file():
        return {"ok": False, "error": f"rutube_client not found: {client}"}
    cmd = [sys.executable, str(client), *args]
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cfg["cwd"]),
            env=build_env(cfg),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_client_timeout(),
        )
    except subprocess.TimeoutExpired:
        payload = {
            "ok": False,
            "error": f"timeout {_client_timeout()}с (env VIDEOSHORTS_PUBLISH_CLIENT_TIMEOUT)",
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "cmd": cmd[1:],
        }
        if log_path is not None:
            _write_json(log_path, payload)
        return payload
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
        "has_cookies_after": Path(cfg["storage"]).is_file() and Path(cfg["storage"]).stat().st_size > 100,
    }
    if log_path is not None:
        _write_json(log_path, payload)
    return payload


def status_payload(clips_dir: Path | None = None) -> dict:
    cfg = resolve_config()
    last_log = {}
    if clips_dir and clips_dir.is_dir():
        last_log = _read_json(clips_dir / "rutube-publish-log.json")
    return {
        "ok": True,
        "client_ok": cfg["client_ok"],
        "client": str(cfg["client"]),
        "storage": str(cfg["storage"]),
        "has_cookies": cfg["has_cookies"],
        "channel_id": cfg.get("channel_id"),
        "channel_url": cfg.get("channel_url"),
        "category": cfg.get("category"),
        "playlist": cfg.get("playlist"),
        "last": {
            "ok": last_log.get("ok"),
            "finished_at": last_log.get("finished_at"),
            "index": last_log.get("index"),
            "mode": last_log.get("mode"),
            "error": last_log.get("error"),
        }
        if last_log
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts → RuTube Shorts")
    parser.add_argument("clips_dir", type=Path, nargs="?", default=None)
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    cfg = resolve_config()
    if args.status:
        print(json.dumps(status_payload(args.clips_dir), ensure_ascii=False, indent=2))
        return

    if args.login_only:
        print("RuTube: check session / open studio…")
        result = run_client(cfg, ["--login-only"])
        print("[OK] logged in" if result["ok"] else (result.get("stderr") or result.get("stdout") or "fail"))
        sys.exit(0 if result["ok"] else 1)

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
    title = str(item.get("title") or f"clip_{args.index:02d}")
    description = str(item.get("_description") or "")
    tags = ", ".join(item.get("_hashtags") or [])

    if not video or not Path(str(video)).is_file():
        print(f"[ERROR] video missing for clip_{args.index:02d}", file=sys.stderr)
        sys.exit(3)
    if not cover or not Path(str(cover)).is_file():
        print(f"[ERROR] cover missing for clip_{args.index:02d}", file=sys.stderr)
        sys.exit(4)

    cli = [
        "--video", str(video),
        "--title", title,
        "--description", description,
        "--cover", str(cover),
    ]
    if tags:
        cli.extend(["--tags", tags])
    if args.draft:
        cli.append("--draft")

    print(f"RuTube: clip_{args.index:02d} → #{cfg['channel_id']} · {Path(str(video)).name}")
    print(f"  category={cfg['category']} · playlist={cfg['playlist']}")
    result = run_client(cfg, cli)
    result["mode"] = "draft" if args.draft else "publish"
    result["index"] = args.index
    result["video"] = str(video)
    result["cover"] = str(cover)
    result["title"] = title
    result["playlist"] = cfg["playlist"]
    _write_json(clips_dir / "rutube-publish-log.json", result)

    if result["ok"]:
        print("[OK] RuTube: опубликовано")
        sys.exit(0)
    print(result.get("stderr") or result.get("stdout") or "publish failed", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
