#!/usr/bin/env python3
"""Генерирует B-roll по агентному broll-plan.json, с resume по успешным assets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kie_client import KieApiError, KieClient, load_api_key
from videoshorts_core import configure_stdio

configure_stdio()


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default
    except (OSError, json.JSONDecodeError):
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: Kie B-roll generation")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    plan = read_json(args.plan, {"inserts": []})
    ready = [item for item in plan.get("inserts", []) if isinstance(item, dict) and item.get("status") == "READY"]
    jobs_path = args.clips_dir / "broll-jobs.json"
    jobs = read_json(jobs_path, {"schema_version": 1, "jobs": []})
    jobs["jobs"] = [item for item in jobs.get("jobs", []) if isinstance(item, dict)]
    if args.dry_run:
        print(f"B-roll dry-run: {len(ready)} ready insert(s); API calls skipped")
        return
    key = load_api_key()
    if not key:
        print("[ERROR] KIE_API_KEY is not configured. Copy videoshorts.env.example to videoshorts.local.env.", file=sys.stderr)
        sys.exit(2)
    client = KieClient(key)
    assets = args.clips_dir / "broll-assets"
    for item in ready:
        idx = int(item["clip_index"])
        asset_name = str(item.get("asset_file") or f"clip_{idx:02d}_broll.mp4")
        target = assets / asset_name
        existing = next((j for j in jobs["jobs"] if j.get("clip_index") == idx and j.get("status") == "SUCCESS"), None)
        if target.is_file() and target.stat().st_size > 0:
            continue
        try:
            image_task, image_urls = client.generate_image(str(item["image_prompt"]))
            video_task, video_urls = client.generate_video(str(item["video_prompt"]), image_urls[0])
            client.download(video_urls[0], target)
            jobs["jobs"].append({
                "clip_index": idx, "status": "SUCCESS", "image_task_id": image_task,
                "video_task_id": video_task, "image_url": image_urls[0], "video_url": video_urls[0],
                "asset_file": asset_name,
            })
        except (KeyError, ValueError, KieApiError) as exc:
            jobs["jobs"].append({"clip_index": idx, "status": "FAIL", "error": str(exc), "asset_file": asset_name})
            jobs_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[ERROR] B-roll clip {idx}: {exc}", file=sys.stderr)
            sys.exit(1)
        jobs_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"B-roll generation complete: {len(ready)} insert(s)")


if __name__ == "__main__":
    main()
