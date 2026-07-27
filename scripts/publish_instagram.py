#!/usr/bin/env python3
"""Публикация клипа в Instagram Reels через bundled Playwright instagram_client.

Зеркало publish_tiktok / publish_vk:
  scripts/instagram_client.py
  scripts/instagram_login_save.py
  videoshorts-memory/secrets/instagram_storage_state.json  (gitignored)
"""
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
DEFAULT_CLIENT = PLUGIN_ROOT / "scripts" / "instagram_client.py"
DEFAULT_LOGIN = PLUGIN_ROOT / "scripts" / "instagram_login_save.py"
DEFAULT_STORAGE = (
    PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "instagram_storage_state.json"
)


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
        local.get("VIDEOSHORTS_INSTAGRAM_CLIENT")
        or os.environ.get("VIDEOSHORTS_INSTAGRAM_CLIENT")
        or DEFAULT_CLIENT
    )
    if not client.is_absolute():
        client = (plugin_root / client).resolve()
    storage = Path(
        local.get("VIDEOSHORTS_INSTAGRAM_STORAGE")
        or os.environ.get("VIDEOSHORTS_INSTAGRAM_STORAGE")
        or local.get("INSTAGRAM_STORAGE_STATE")
        or os.environ.get("INSTAGRAM_STORAGE_STATE")
        or DEFAULT_STORAGE
    )
    if not storage.is_absolute():
        storage = (plugin_root / storage).resolve()
    storage.parent.mkdir(parents=True, exist_ok=True)
    return {
        "client": client,
        "login_script": DEFAULT_LOGIN,
        "cwd": plugin_root,
        "storage": storage,
        "has_cookies": storage.is_file() and storage.stat().st_size > 100,
        "client_ok": client.is_file(),
        "timezone": local.get("INSTAGRAM_TZ")
        or os.environ.get("INSTAGRAM_TZ")
        or "Europe/Moscow",
    }


def status_payload(clips_dir: Path | None = None) -> dict:
    cfg = resolve_config()
    out = {
        "ok": True,
        "has_cookies": cfg["has_cookies"],
        "client_ok": cfg["client_ok"],
        "storage": str(cfg["storage"]),
        "bundled": True,
        "timezone": cfg["timezone"],
    }
    if clips_dir and Path(clips_dir).is_dir():
        log = Path(clips_dir) / "instagram-publish-log.json"
        if log.is_file():
            out["last_log"] = _read_json(log)
    return out


def build_env(cfg: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["HEADLESS"] = "false"
    env["KEEP_BROWSER_OPEN"] = "false"
    env["VIDEOSHORTS_FORCE_CLOSE_BROWSER"] = "1"
    env["VIDEOSHORTS_INSTAGRAM_STORAGE"] = str(Path(cfg["storage"]).resolve())
    env["INSTAGRAM_STORAGE_STATE"] = str(Path(cfg["storage"]).resolve())
    env["INSTAGRAM_TZ"] = str(cfg["timezone"])
    local = _load_local_env(PLUGIN_ROOT)
    for key in ("KIE_API_KEY", "INSTAGRAM_TZ", "INSTAGRAM_LOCALE", "INSTAGRAM_ASPECT"):
        if local.get(key):
            env[key] = local[key]
    return env


def _normalize_tags(raw, *, limit: int = 12) -> list[str]:
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
    caption = ""
    hashtags: list = []

    platforms = meta.get("platforms") if isinstance(meta.get("platforms"), dict) else {}
    ig = platforms.get("instagram") if isinstance(platforms.get("instagram"), dict) else {}
    if ig.get("caption"):
        caption = str(ig.get("caption"))
    elif ig.get("description"):
        caption = str(ig.get("description"))
    elif ig.get("copy_block"):
        caption = str(ig.get("copy_block"))
    if ig.get("title"):
        title = str(ig.get("title"))
    if ig.get("hashtags"):
        hashtags = ig.get("hashtags") or []

    if not caption and isinstance(meta, dict):
        caption = str(meta.get("description") or meta.get("copy_block") or "")
    if not hashtags and isinstance(meta, dict):
        hashtags = meta.get("hashtags") or []
    if isinstance(meta, dict) and meta.get("title"):
        title = str(meta.get("title"))

    # queue platforms.instagram.payload fallback
    q_platforms = base.get("platforms") if isinstance(base.get("platforms"), dict) else {}
    q_ig = q_platforms.get("instagram") if isinstance(q_platforms.get("instagram"), dict) else {}
    q_payload = q_ig.get("payload") if isinstance(q_ig.get("payload"), dict) else {}
    if not caption:
        caption = str(q_payload.get("caption") or q_payload.get("description") or "")

    tags = _normalize_tags(hashtags)
    if tags and "#" not in caption:
        caption = (caption.rstrip() + "\n\n" + " ".join(f"#{t}" for t in tags)).strip()

    base["title"] = title
    base["_caption"] = caption[:2200]
    base["_hashtags"] = tags
    return base


def run_client(cfg: dict, args: list[str]) -> dict:
    client = Path(cfg["client"])
    if not client.is_file():
        return {"ok": False, "error": f"instagram_client not found: {client}"}
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
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts → Instagram Reels")
    parser.add_argument("clips_dir", type=Path, nargs="?", default=None)
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--location", default="", help="Optional location text")
    args = parser.parse_args()

    cfg = resolve_config()
    if args.status:
        print(json.dumps(status_payload(args.clips_dir), ensure_ascii=False, indent=2))
        return

    if args.login_only:
        login = Path(cfg["login_script"])
        if not login.is_file():
            # fallback: client --login-only (session check only)
            print("Instagram: check session…")
            result = run_client(cfg, ["--login-only"])
            print("[OK]" if result["ok"] else (result.get("stderr") or "fail"))
            sys.exit(0 if result["ok"] else 1)
        print("Instagram: открываю браузер для входа…")
        proc = subprocess.run(
            [sys.executable, str(login)],
            cwd=str(cfg["cwd"]),
            env=build_env(cfg),
        )
        sys.exit(proc.returncode)

    if args.clips_dir is None or args.index is None:
        print("[ERROR] Need clips_dir and --index", file=sys.stderr)
        sys.exit(2)

    clips_dir = args.clips_dir
    item = _clip_payload(clips_dir, args.index)
    video, cover = item.get("video"), item.get("cover")
    title = str(item.get("title") or f"clip_{args.index:02d}")
    caption = str(item.get("_caption") or "")

    if not video or not Path(str(video)).is_file():
        print(f"[ERROR] video missing clip_{args.index:02d}", file=sys.stderr)
        sys.exit(3)
    if not cover or not Path(str(cover)).is_file():
        print(f"[WARN] cover missing clip_{args.index:02d} — publishing without cover")

    # Avoid Windows argv mojibake for emoji captions
    caption_file = clips_dir / f"_ig_caption_{args.index:02d}.txt"
    caption_file.write_text(caption, encoding="utf-8")

    print(f"Instagram: clip_{args.index:02d}")
    print(f"  title: {title}")
    print(f"  caption ({len(caption)} chars): {caption[:160].replace(chr(10), ' ')}…")
    print(f"  cover: {cover or '(none)'}")
    print(f"  dry_run: {args.dry_run}")

    cli = [
        "--video",
        str(video),
        "--caption-file",
        str(caption_file.resolve()),
    ]
    if cover and Path(str(cover)).is_file():
        cli.extend(["--cover", str(cover)])
    if args.location:
        cli.extend(["--location", args.location])
    if args.dry_run:
        cli.append("--dry-run")

    result = run_client(cfg, cli)
    result["mode"] = "dry_run" if args.dry_run else "publish"
    result["index"] = args.index
    result["title"] = title
    result["caption"] = caption
    result["cover"] = str(cover) if cover else None
    _write_json(clips_dir / "instagram-publish-log.json", result)

    try:
        caption_file.unlink(missing_ok=True)
    except Exception:
        pass

    if result["ok"]:
        print("[OK] Instagram: posted" if not args.dry_run else "[OK] Instagram: dry-run")
        sys.exit(0)
    print(result.get("stderr") or result.get("stdout") or "fail", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
