#!/usr/bin/env python3
"""Публикация клипа в TikTok Studio через bundled Playwright tiktok_client."""
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
DEFAULT_CLIENT = PLUGIN_ROOT / "scripts" / "tiktok_client.py"
DEFAULT_STORAGE = PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "tiktok_storage_state.json"


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
        local.get("VIDEOSHORTS_TIKTOK_CLIENT")
        or os.environ.get("VIDEOSHORTS_TIKTOK_CLIENT")
        or DEFAULT_CLIENT
    )
    if not client.is_absolute():
        client = (plugin_root / client).resolve()
    storage = Path(
        local.get("VIDEOSHORTS_TIKTOK_STORAGE")
        or os.environ.get("VIDEOSHORTS_TIKTOK_STORAGE")
        or local.get("TIKTOK_STORAGE_STATE")
        or os.environ.get("TIKTOK_STORAGE_STATE")
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
        "visibility": local.get("TIKTOK_VISIBILITY")
        or os.environ.get("TIKTOK_VISIBILITY")
        or "Everyone",
        "timezone": local.get("TIKTOK_TZ") or os.environ.get("TIKTOK_TZ") or "Europe/Vilnius",
    }


def build_env(cfg: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["HEADLESS"] = "false"
    env["KEEP_BROWSER_OPEN"] = "false"
    env["VIDEOSHORTS_FORCE_CLOSE_BROWSER"] = "1"
    env["VIDEOSHORTS_TIKTOK_STORAGE"] = str(Path(cfg["storage"]).resolve())
    env["TIKTOK_VISIBILITY"] = str(cfg["visibility"])
    env["TIKTOK_TZ"] = str(cfg["timezone"])
    local = _load_local_env(PLUGIN_ROOT)
    for key in ("KIE_API_KEY", "TIKTOK_VISIBILITY", "TIKTOK_TZ"):
        if local.get(key):
            env[key] = local[key]
    return env


def _normalize_tags(raw, *, limit: int = 8) -> list[str]:
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
    meta = _read_json(clips_dir / "metadata" / f"clip_{index:02d}.metadata.json")
    video = clips_dir / f"clip_{index:02d}.mp4"
    base = dict(queue_item) if queue_item else {"index": index}
    if not base.get("video"):
        base["video"] = str(video.resolve()) if video.is_file() else None
    cover_local = clips_dir / "covers" / f"clip_{index:02d}_cover.jpg"
    if not base.get("cover") and cover.get("cover_path"):
        base["cover"] = cover.get("cover_path")
    if not base.get("cover") and cover_local.is_file():
        base["cover"] = str(cover_local.resolve())

    platforms = base.get("platforms") if isinstance(base.get("platforms"), dict) else {}
    title = base.get("title") or (meta.get("title") if isinstance(meta, dict) else None) or f"clip_{index:02d}"
    description = ""
    hashtags: list = []
    for key in ("tiktok", "zen", "vk", "rutube", "youtube", "instagram"):
        block = platforms.get(key) if isinstance(platforms.get(key), dict) else {}
        payload = block.get("payload") if isinstance(block.get("payload"), dict) else {}
        if not description:
            description = str(payload.get("description") or payload.get("caption") or "")
        if not hashtags:
            hashtags = payload.get("hashtags") or []
        if payload.get("title"):
            title = str(payload.get("title"))
    if isinstance(meta, dict):
        if not description:
            description = str(meta.get("description") or "")
        if not hashtags:
            hashtags = meta.get("hashtags") or []
        if meta.get("title"):
            title = str(meta.get("title"))
        # TikTok-specific from metadata platforms
        tt = meta.get("platforms") if isinstance(meta.get("platforms"), dict) else {}
        tt_block = tt.get("tiktok") if isinstance(tt.get("tiktok"), dict) else {}
        # Полный текст берём из корня meta (tiktok.description часто обрезан: «payoff: а»)
        if isinstance(meta, dict) and meta.get("description"):
            description = str(meta.get("description"))
        if isinstance(meta, dict) and meta.get("title"):
            title = str(meta.get("title"))
        # caption/copy_block из tiktok — только если корень пуст и текст не выглядит обрезанным
        if not description:
            for key in ("caption", "copy_block", "description"):
                val = str(tt_block.get(key) or "").strip()
                if val and not re.search(r"payoff:\s*а\s*$", val, re.I):
                    description = val
                    break
        if tt_block.get("hashtags"):
            hashtags = tt_block.get("hashtags")
        if tt_block.get("title"):
            title = str(tt_block.get("title"))

    pinned = ""
    if isinstance(meta, dict):
        pinned = str(meta.get("pinned_comment") or "")
    if not pinned and isinstance(platforms.get("instagram"), dict):
        pinned = str((platforms.get("instagram") or {}).get("first_comment") or "")

    base["title"] = title
    base["_description"] = description
    base["_hashtags"] = _normalize_tags(hashtags)
    base["_pinned_comment"] = pinned
    return base


def _client_timeout() -> int:
    try:
        return max(120, int(os.getenv("VIDEOSHORTS_PUBLISH_CLIENT_TIMEOUT", "900")))
    except ValueError:
        return 900


def run_client(cfg: dict, args: list[str]) -> dict:
    client = Path(cfg["client"])
    if not client.is_file():
        return {"ok": False, "error": f"tiktok_client not found: {client}"}
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
        return {
            "ok": False,
            "error": f"timeout {_client_timeout()}с (env VIDEOSHORTS_PUBLISH_CLIENT_TIMEOUT)",
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "cmd": cmd[1:],
        }
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
    parser = argparse.ArgumentParser(description="VideoShorts → TikTok Studio")
    parser.add_argument("clips_dir", type=Path, nargs="?", default=None)
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    cfg = resolve_config()
    if args.status:
        print(
            json.dumps(
                {
                    "ok": True,
                    "client_ok": cfg["client_ok"],
                    "has_cookies": cfg["has_cookies"],
                    "storage": str(cfg["storage"]),
                    "visibility": cfg["visibility"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.login_only:
        print("TikTok: check session (VPN must be ON)…")
        result = run_client(cfg, ["--login-only"])
        print("[OK]" if result["ok"] else (result.get("stderr") or "fail"))
        sys.exit(0 if result["ok"] else 1)

    if args.clips_dir is None or args.index is None:
        print("[ERROR] Need clips_dir and --index", file=sys.stderr)
        sys.exit(2)

    clips_dir = args.clips_dir
    item = _clip_payload(clips_dir, args.index)
    video, cover = item.get("video"), item.get("cover")
    title = str(item.get("title") or f"clip_{args.index:02d}")
    description = str(item.get("_description") or "")
    tags = ", ".join(item.get("_hashtags") or [])
    pinned = str(item.get("_pinned_comment") or "")

    if not video or not Path(str(video)).is_file():
        print(f"[ERROR] video missing clip_{args.index:02d}", file=sys.stderr)
        sys.exit(3)
    if not cover or not Path(str(cover)).is_file():
        print(f"[ERROR] cover missing clip_{args.index:02d}", file=sys.stderr)
        sys.exit(4)

    print(f"TikTok: clip_{args.index:02d} · visibility={cfg['visibility']}")
    print(f"  title: {title}")
    print(f"  description ({len(description)} chars): {description[:160].replace(chr(10), ' ')}…")
    print(f"  tags: {tags}")
    print(f"  cover: {cover}")
    print(f"  pinned_comment: {pinned[:80] if pinned else '(none — post-publish manual)'}")
    print("  VPN must stay ON (non-RU IP)")

    cli = [
        "--video", str(video),
        "--title", title,
        "--description", description,
        "--cover", str(cover),
    ]
    if tags:
        cli.extend(["--tags", tags])
    if pinned:
        cli.extend(["--pinned-comment", pinned])
    if args.draft:
        cli.append("--draft")

    result = run_client(cfg, cli)
    result["mode"] = "draft" if args.draft else "publish"
    result["index"] = args.index
    result["visibility"] = cfg["visibility"]
    result["title"] = title
    result["description"] = description
    result["tags"] = tags
    result["cover"] = str(cover)
    result["pinned_comment"] = pinned
    _write_json(clips_dir / "tiktok-publish-log.json", result)

    if result["ok"]:
        print("[OK] TikTok: posted")
        if pinned:
            print(f"[NOTE] Закрепите комментарий вручную: {pinned}")
        sys.exit(0)
    print(result.get("stderr") or result.get("stdout") or "fail", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
