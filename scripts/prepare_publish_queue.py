#!/usr/bin/env python3
"""Собрать очередь публикации: выбранные клипы + метаданные + обложки.

Платформенные адаптеры (YouTube/Instagram/TikTok API) подключаются позже.
Сейчас готовится красивый READY_TO_PUBLISH пакет.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from publish_selection import load_selection
from videoshorts_core import configure_stdio

configure_stdio()


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: prepare publish queue")
    parser.add_argument("clips_dir", type=Path)
    args = parser.parse_args()
    clips_dir = args.clips_dir
    if not clips_dir.is_dir():
        print(f"[ERROR] clips_dir not found: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    selection = load_selection(clips_dir)
    selected = selection.get("selected") or []
    if not selected:
        print("[ERROR] Нет selected клипов", file=sys.stderr)
        sys.exit(2)

    covers = _read_json(clips_dir / "covers-manifest.json")
    cover_by_index = {
        int(item["index"]): item
        for item in covers.get("covers", [])
        if isinstance(item, dict) and item.get("ok") and item.get("index") is not None
    }
    meta_manifest = _read_json(clips_dir / "metadata-manifest.json")
    meta_by_index = {
        int(item["index"]): item
        for item in meta_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    }

    items = []
    blockers = []
    for item in selected:
        index = int(item["index"])
        meta = meta_by_index.get(index)
        cover = cover_by_index.get(index)
        platforms = item.get("platforms") or ["youtube", "instagram", "tiktok"]
        if not meta:
            blockers.append(f"clip_{index:02d}: metadata missing")
            continue
        if not cover:
            blockers.append(f"clip_{index:02d}: cover missing")
            continue
        video_name = meta.get("clip_file") or f"clip_{index:02d}.mp4"
        video_path = clips_dir / video_name
        if not video_path.is_file():
            alt = clips_dir / f"clip_{index:02d}.mp4"
            video_path = alt if alt.is_file() else video_path
        platform_jobs = {}
        for platform in platforms:
            pack = (meta.get("platforms") or {}).get(platform) or {
                "title": meta.get("title"),
                "description": meta.get("description") or meta.get("caption"),
                "hashtags": meta.get("hashtags"),
            }
            if not isinstance(pack, dict):
                pack = {
                    "title": meta.get("title"),
                    "description": meta.get("description") or meta.get("caption"),
                    "hashtags": meta.get("hashtags"),
                }
            else:
                pack = dict(pack)
            if not pack.get("hashtags"):
                pack["hashtags"] = meta.get("hashtags") or []
            if platform in ("zen", "vk") and isinstance(pack.get("hashtags"), list):
                # Дзен: максимум 5 чипов; без #
                pack["hashtags"] = [
                    str(t).strip().lstrip("#").strip()
                    for t in pack["hashtags"]
                    if str(t).strip()
                ][:5]
            if platform == "zen":
                adapter = "playwright:dzen"
            elif platform == "vk":
                adapter = "future:vk"
            else:
                adapter = f"future:{platform}"
            platform_jobs[platform] = {
                "status": "pending",
                "adapter": adapter,
                "payload": pack,
            }
        items.append({
            "index": index,
            "status": "ready",
            "video": str(video_path.resolve()),
            "video_file": video_path.name,
            "cover": cover.get("cover_path"),
            "cover_file": cover.get("cover_file"),
            "cover_text": cover.get("cover_text") or meta.get("cover_text"),
            "cover_prompt": meta.get("cover_prompt"),
            "title": meta.get("title"),
            "platforms": platform_jobs,
            "seo_keywords": meta.get("seo_keywords") or [],
        })

    status = "READY_TO_PUBLISH" if items and not blockers else ("BLOCKED" if blockers else "EMPTY")
    queue = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clips_dir": str(clips_dir.resolve()),
        "status": status,
        "selected_count": len(selected),
        "ready_count": len(items),
        "blockers": blockers,
        "items": items,
        "platforms_supported_now": ["zen"],
        "platforms_planned": ["youtube", "instagram", "tiktok", "telegram", "vk", "zen"],
        "next_step": (
            "publish_dzen_or_adapters"
            if status == "READY_TO_PUBLISH"
            else ("prepare_covers" if any("cover" in b for b in blockers) else "fix_selection")
        ),
        "note": (
            "Пакет готов. Дзен: Results → «Опубликовать в Дзен» (Playwright). "
            "VK/YouTube/IG/TT/TG — adapters позже. Очередь содержит video + cover + SEO."
        ),
    }
    out = clips_dir / "publish-queue.json"
    out.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

    # Human-readable checklist
    lines = [
        "# Publish queue",
        "",
        f"status: {status}",
        f"ready: {len(items)}/{len(selected)}",
        "",
    ]
    for entry in items:
        lines.append(f"## clip_{entry['index']:02d} — {entry['title']}")
        lines.append(f"- video: `{entry['video_file']}`")
        lines.append(f"- cover: `{entry.get('cover_file')}`")
        lines.append(f"- platforms: {', '.join(entry['platforms'].keys())}")
        for name, job in entry["platforms"].items():
            payload = job.get("payload") or {}
            lines.append(f"  - **{name} title:** {payload.get('title') or payload.get('caption') or '-'}")
        lines.append("")
    if blockers:
        lines.append("## Blockers")
        lines.extend([f"- {b}" for b in blockers])
    (clips_dir / "publish-queue.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"✅ Publish queue: {out}")
    print(f"   status={status} ready={len(items)}/{len(selected)}")
    if blockers:
        for b in blockers:
            print(f"   ❌ {b}")
    if status != "READY_TO_PUBLISH":
        sys.exit(2)


if __name__ == "__main__":
    main()
