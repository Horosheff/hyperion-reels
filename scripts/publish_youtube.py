#!/usr/bin/env python3
"""Публикация клипа в YouTube Shorts через bundled Playwright youtube_client."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from videoshorts_core import configure_stdio

configure_stdio()

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT = PLUGIN_ROOT / "scripts" / "youtube_client.py"
DEFAULT_LOGIN = PLUGIN_ROOT / "scripts" / "youtube_login_save.py"
DEFAULT_STORAGE = PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "youtube_storage_state.json"


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
        local.get("VIDEOSHORTS_YOUTUBE_CLIENT")
        or os.environ.get("VIDEOSHORTS_YOUTUBE_CLIENT")
        or DEFAULT_CLIENT
    )
    if not client.is_absolute():
        client = (plugin_root / client).resolve()
    storage = Path(
        local.get("VIDEOSHORTS_YOUTUBE_STORAGE")
        or os.environ.get("VIDEOSHORTS_YOUTUBE_STORAGE")
        or local.get("YOUTUBE_STORAGE_STATE")
        or os.environ.get("YOUTUBE_STORAGE_STATE")
        or DEFAULT_STORAGE
    )
    if not storage.is_absolute():
        storage = (plugin_root / storage).resolve()
    storage.parent.mkdir(parents=True, exist_ok=True)
    channel_id = (
        local.get("YOUTUBE_CHANNEL_ID")
        or os.environ.get("YOUTUBE_CHANNEL_ID")
        or "UCQ2_R6IaR6FvJpvqLaNqu6w"
    )
    return {
        "client": client,
        "login_script": DEFAULT_LOGIN,
        "cwd": plugin_root,
        "storage": storage,
        "has_cookies": storage.is_file() and storage.stat().st_size > 100,
        "client_ok": client.is_file(),
        "channel_id": channel_id,
        "channel_url": local.get("YOUTUBE_CHANNEL_URL")
        or os.environ.get("YOUTUBE_CHANNEL_URL")
        or f"https://studio.youtube.com/channel/{channel_id}",
        "category": local.get("YOUTUBE_CATEGORY")
        or os.environ.get("YOUTUBE_CATEGORY")
        or "Наука и техника",
        "playlist": local.get("YOUTUBE_PLAYLIST") or os.environ.get("YOUTUBE_PLAYLIST") or "",
    }


def build_env(cfg: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["HEADLESS"] = "false"
    env["KEEP_BROWSER_OPEN"] = "false"
    env["VIDEOSHORTS_FORCE_CLOSE_BROWSER"] = "1"
    env["VIDEOSHORTS_YOUTUBE_STORAGE"] = str(Path(cfg["storage"]).resolve())
    env["YOUTUBE_STORAGE_STATE"] = str(Path(cfg["storage"]).resolve())
    env["YOUTUBE_CHANNEL_ID"] = str(cfg["channel_id"])
    env["YOUTUBE_CHANNEL_URL"] = str(cfg["channel_url"])
    env["YOUTUBE_CATEGORY"] = str(cfg["category"])
    if cfg.get("playlist"):
        env["YOUTUBE_PLAYLIST"] = str(cfg["playlist"])
    for key in (
        "VIDEOSHORTS_PLATFORM",
        "VIDEOSHORTS_BROWSER_SLOT",
        "VIDEOSHORTS_WINDOW_SLOT",
        "PLAYWRIGHT_MONITOR",
        "PLAYWRIGHT_WINDOW_POSITION",
        "PLAYWRIGHT_WINDOW_SIZE",
        "YOUTUBE_PLAYLIST",
        "YOUTUBE_AI_USED",
        "YOUTUBE_TZ",
        "YOUTUBE_LOCALE",
    ):
        if key in os.environ and os.environ[key]:
            env[key] = os.environ[key]
    local = _load_local_env(PLUGIN_ROOT)
    for key in (
        "YOUTUBE_CHANNEL_ID",
        "YOUTUBE_CHANNEL_URL",
        "YOUTUBE_CATEGORY",
        "YOUTUBE_PLAYLIST",
        "YOUTUBE_AI_USED",
        "YOUTUBE_TZ",
        "YOUTUBE_LOCALE",
        "KIE_API_KEY",
    ):
        if local.get(key):
            env[key] = local[key]
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
    queue_item = next(
        (
            item
            for item in (queue.get("items") or [])
            if isinstance(item, dict) and int(item.get("index", -1)) == index
        ),
        None,
    )
    covers = _read_json(clips_dir / "covers-manifest.json")
    cover = next(
        (
            c
            for c in (covers.get("covers") or [])
            if isinstance(c, dict) and int(c.get("index", -1)) == index and c.get("ok")
        ),
        {},
    )
    meta_paths = [
        clips_dir / "metadata" / f"clip_{index:02d}.metadata.json",
        clips_dir / f"clip_{index:02d}.metadata.json",
    ]
    meta: dict = {}
    for mp in meta_paths:
        meta = _read_json(mp)
        if meta:
            break

    video = clips_dir / f"clip_{index:02d}.mp4"
    base = dict(queue_item) if queue_item else {"index": index}
    if not base.get("video"):
        base["video"] = str(video.resolve()) if video.is_file() else None
    cover_local = clips_dir / "covers" / f"clip_{index:02d}_cover.jpg"
    if not base.get("cover") and cover.get("cover_path"):
        base["cover"] = cover.get("cover_path")
    if not base.get("cover") and cover_local.is_file():
        base["cover"] = str(cover_local.resolve())

    title = base.get("title") or (meta.get("title") if meta else None) or f"clip_{index:02d}"
    description = ""
    hashtags: list = []

    platforms = meta.get("platforms") if isinstance(meta.get("platforms"), dict) else {}
    yt = platforms.get("youtube") if isinstance(platforms.get("youtube"), dict) else {}
    if yt.get("title"):
        title = str(yt.get("title"))
    if yt.get("description"):
        description = str(yt.get("description"))
    elif yt.get("caption"):
        description = str(yt.get("caption"))
    if yt.get("hashtags"):
        hashtags = yt.get("hashtags") or []

    if not description and isinstance(meta, dict):
        description = str(meta.get("description") or meta.get("copy_block") or "")
    if not hashtags and isinstance(meta, dict):
        hashtags = meta.get("hashtags") or []

    q_platforms = base.get("platforms") if isinstance(base.get("platforms"), dict) else {}
    q_yt = q_platforms.get("youtube") if isinstance(q_platforms.get("youtube"), dict) else {}
    q_payload = q_yt.get("payload") if isinstance(q_yt.get("payload"), dict) else {}
    if not description:
        description = str(q_payload.get("description") or q_payload.get("caption") or "")
    if q_payload.get("title"):
        title = str(q_payload.get("title"))

    base["title"] = title
    base["_description"] = description
    base["_hashtags"] = _normalize_tags(hashtags)
    return base


def run_client(cfg: dict, args: list[str]) -> dict:
    client = Path(cfg["client"])
    if not client.is_file():
        return {"ok": False, "error": f"youtube_client not found: {client}"}
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
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "cmd": cmd[1:],
        "stdout": (result.stdout or "")[-8000:],
        "stderr": (result.stderr or "")[-4000:],
        "storage": str(Path(cfg["storage"]).resolve()),
        "client": str(client.resolve()),
        "has_cookies_after": Path(cfg["storage"]).is_file()
        and Path(cfg["storage"]).stat().st_size > 100,
    }


def status_payload(clips_dir: Path | None = None) -> dict:
    cfg = resolve_config()
    last_log = {}
    if clips_dir and Path(clips_dir).is_dir():
        last_log = _read_json(Path(clips_dir) / "youtube-publish-log.json")
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
    parser = argparse.ArgumentParser(description="VideoShorts → YouTube Shorts")
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
        login = Path(cfg["login_script"])
        if login.is_file():
            print("YouTube: открываю браузер для входа…")
            proc = subprocess.run(
                [sys.executable, str(login)],
                cwd=str(cfg["cwd"]),
                env=build_env(cfg),
            )
            sys.exit(proc.returncode)
        print("YouTube: check session…")
        result = run_client(cfg, ["--login-only"])
        print("[OK]" if result["ok"] else (result.get("stderr") or "fail"))
        sys.exit(0 if result["ok"] else 1)

    if args.clips_dir is None or args.index is None:
        print("[ERROR] Нужны clips_dir и --index", file=sys.stderr)
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
        print(f"[WARN] cover missing clip_{args.index:02d} — publishing without cover")

    cli = [
        "--video",
        str(video),
        "--title",
        title,
        "--description",
        description,
    ]
    if cover and Path(str(cover)).is_file():
        cli.extend(["--cover", str(cover)])
    if tags:
        cli.extend(["--tags", tags])
    if args.draft:
        cli.append("--draft")

    # Хештеги в title (до 3) собирает youtube_client; дубли в description он снимает сам
    print(f"YouTube: clip_{args.index:02d} → {cfg['channel_id']} · {Path(str(video)).name}")
    print(f"  category={cfg['category']} · playlist={cfg['playlist'] or '(none)'}")
    print(f"  title={title[:80]}{'…' if len(title) > 80 else ''}")
    print(f"  hashtags({len(item.get('_hashtags') or [])})={tags[:120]}")
    result = run_client(cfg, cli)
    result["mode"] = "draft" if args.draft else "publish"
    result["index"] = args.index
    result["video"] = str(video)
    result["cover"] = str(cover) if cover else None
    result["title"] = title
    result["playlist"] = cfg["playlist"]
    _write_json(clips_dir / "youtube-publish-log.json", result)

    if result["ok"]:
        print("[OK] YouTube: опубликовано")
        sys.exit(0)
    print(result.get("stderr") or result.get("stdout") or "publish failed", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
