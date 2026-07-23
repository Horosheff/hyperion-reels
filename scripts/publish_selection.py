#!/usr/bin/env python3
"""Сохранить выбор клипов для публикации (галочки в Results UI)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from videoshorts_core import configure_stdio

configure_stdio()

DEFAULT_PLATFORMS = ["youtube", "instagram", "tiktok"]
ALLOWED_PLATFORMS = {
    "youtube",
    "instagram",
    "tiktok",
    "telegram",
    "vk",
    "zen",
}


def selection_path(clips_dir: Path) -> Path:
    return clips_dir / "publish-selection.json"


def load_selection(clips_dir: Path) -> dict:
    path = selection_path(clips_dir)
    if not path.is_file():
        return {"schema_version": 1, "clips_dir": str(clips_dir.resolve()), "selected": [], "status": "EMPTY"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"selected": []}
    except Exception:
        return {"selected": [], "status": "INVALID"}


def save_selection(clips_dir: Path, items: list[dict], platforms_default: list[str] | None = None) -> Path:
    platforms_default = platforms_default or DEFAULT_PLATFORMS
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        selected = bool(item.get("selected", True))
        platforms = item.get("platforms") or platforms_default
        platforms = [str(p).lower() for p in platforms if str(p).lower() in ALLOWED_PLATFORMS]
        if not platforms:
            platforms = list(platforms_default)
        if not selected:
            continue
        normalized.append({
            "index": index,
            "selected": True,
            "platforms": platforms,
            "clip_file": item.get("clip_file"),
            "title": item.get("title"),
        })
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clips_dir": str(clips_dir.resolve()),
        "status": "SELECTION_SAVED" if normalized else "EMPTY",
        "selected_count": len(normalized),
        "selected": normalized,
        "next_step": "prepare_covers" if normalized else "select_clips",
    }
    path = selection_path(clips_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: publish selection")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--set-json", type=Path, default=None, help="JSON file with selected clips")
    parser.add_argument("--indexes", default="", help="Comma-separated indexes, e.g. 1,3,5")
    parser.add_argument("--platforms", default="youtube,instagram,tiktok")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    if not args.clips_dir.is_dir():
        print(f"[ERROR] clips_dir not found: {args.clips_dir}", file=sys.stderr)
        sys.exit(1)

    platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    if args.show:
        print(json.dumps(load_selection(args.clips_dir), ensure_ascii=False, indent=2))
        return

    items: list[dict] = []
    if args.set_json and args.set_json.is_file():
        data = json.loads(args.set_json.read_text(encoding="utf-8"))
        items = data.get("selected") if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []
    elif args.indexes:
        for part in args.indexes.split(","):
            part = part.strip()
            if part.isdigit():
                items.append({"index": int(part), "selected": True, "platforms": platforms})
    else:
        print("[ERROR] Provide --set-json or --indexes", file=sys.stderr)
        sys.exit(1)

    path = save_selection(args.clips_dir, items, platforms_default=platforms)
    print(f"✅ Publish selection: {path}")


if __name__ == "__main__":
    main()
