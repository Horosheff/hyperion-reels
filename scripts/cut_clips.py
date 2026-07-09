#!/usr/bin/env python3
"""VideoShorts — нарезка dual-screen клипов 9:16."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from videoshorts_core import clips_from_json, configure_stdio, create_webinar_split

configure_stdio()


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: dual-screen рендер клипов")
    parser.add_argument("video", type=Path, help="Исходное видео")
    parser.add_argument("moments", type=Path, help="moments.json от find_moments.py")
    parser.add_argument("-o", "--output-dir", type=Path, default=None, help="Папка для clip_XX.mp4")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--top-ratio", type=float, default=0.30)
    parser.add_argument("--montage-plan", type=Path, default=None, help="montage-plan.json with jump/silence/filler removals")
    parser.add_argument("--min-duration", type=float, default=30.0, help="Do not apply cleanup cuts that make a clip shorter than this")
    parser.add_argument("--workers", type=int, default=1, help="Параллельных рендеров (render_workers)")
    args = parser.parse_args()

    if not args.video.is_file():
        print(f"[ERROR] Video not found: {args.video}", file=sys.stderr)
        sys.exit(1)
    if not args.moments.is_file():
        print(f"[ERROR] Moments not found: {args.moments}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(args.moments.read_text(encoding="utf-8-sig"))
    clips = clips_from_json(data)
    if not clips:
        print("[ERROR] No clips in moments.json", file=sys.stderr)
        sys.exit(1)

    out_dir = args.output_dir or (Path("videoshorts-memory/output/clips") / args.video.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    montage_by_index: dict[int, dict] = {}
    if args.montage_plan and args.montage_plan.is_file():
        montage_data = json.loads(args.montage_plan.read_text(encoding="utf-8-sig"))
        if isinstance(montage_data, dict):
            montage_by_index = {
                int(item.get("index")): item
                for item in montage_data.get("clips", [])
                if isinstance(item, dict) and item.get("index") is not None
            }

    workers = max(1, args.workers)
    print(f"✂️ Rendering {len(clips)} dual-screen clips → {out_dir} (workers={workers})")

    def collect_cut_intervals(montage_item: dict | None, clip_start: float, clip_end: float) -> tuple[list[tuple[float, float]], dict]:
        if not montage_item:
            return [], {"applied": False, "removed_seconds": 0.0, "items": []}

        items: list[dict] = []
        for item in montage_item.get("jump_cuts", []) or []:
            if isinstance(item, dict):
                items.append({**item, "source": "jump_cuts"})
        silence = montage_item.get("silence_remove") or {}
        for item in silence.get("items", []) or []:
            if isinstance(item, dict) and item.get("safe", True):
                items.append({**item, "source": "silence_remove"})
        fillers = montage_item.get("filler_remove") or {}
        for item in fillers.get("items", []) or []:
            if isinstance(item, dict) and item.get("safe", False):
                items.append({**item, "source": "filler_remove"})

        intervals: list[tuple[float, float]] = []
        applied_items: list[dict] = []
        skipped_items: list[dict] = []
        seen_intervals: set[tuple[float, float]] = set()
        max_remove = max(0.0, (clip_end - clip_start) - max(0.0, args.min_duration))
        removed_so_far = 0.0
        for item in items:
            try:
                start = max(clip_start, float(item["start"]))
                end = min(clip_end, float(item["end"]))
            except (KeyError, TypeError, ValueError):
                continue
            duration = end - start
            if duration < 0.08:
                continue
            interval_key = (round(start, 2), round(end, 2))
            if interval_key in seen_intervals:
                continue
            item_summary = {
                "source": item.get("source"),
                "start": start,
                "end": end,
                "duration": round(duration, 3),
                "reason": item.get("reason") or item.get("text") or item.get("type"),
            }
            if removed_so_far + duration > max_remove:
                skipped_items.append({**item_summary, "skip_reason": "min_duration_guard"})
                continue
            seen_intervals.add(interval_key)
            intervals.append((start, end))
            applied_items.append(item_summary)
            removed_so_far += duration

        removed_seconds = round(sum(end - start for start, end in intervals), 3)
        return intervals, {
            "applied": bool(intervals),
            "removed_seconds": removed_seconds,
            "items": applied_items,
            "skipped": skipped_items,
            "min_duration_guard": args.min_duration,
            "jump_cuts": len([x for x in applied_items if x.get("source") == "jump_cuts"]),
            "silence_remove": len([x for x in applied_items if x.get("source") == "silence_remove"]),
            "filler_remove": len([x for x in applied_items if x.get("source") == "filler_remove"]),
        }

    def render_one(clip, ordinal: int) -> dict:
        i = int(getattr(clip, "index", None) or ordinal)
        out_path = out_dir / f"clip_{i:02d}_cropped.mp4"
        montage_item = montage_by_index.get(i) or montage_by_index.get(ordinal)
        cut_intervals, cleanup_applied = collect_cut_intervals(montage_item, clip.start, clip.end)
        removed = cleanup_applied["removed_seconds"]
        suffix = f", cleanup -{removed:.2f}s" if removed else ""
        print(f"   clip {i} ({ordinal}/{len(clips)}): {clip.start:.1f}-{clip.end:.1f}s{suffix}", flush=True)
        success = create_webinar_split(
            args.video,
            out_path,
            clip.start,
            clip.end,
            top_ratio=args.top_ratio,
            output_width=args.width,
            output_height=args.height,
            cut_intervals=cut_intervals,
        )
        if not success:
            print(f"   [WARN] Failed: clip {i}", file=sys.stderr)
        rendered_duration = max(0.0, (clip.end - clip.start) - removed)
        return {
            "index": i,
            "file": str(out_path.name),
            "cropped_file": str(out_path.name),
            "final_file": f"clip_{i:02d}.mp4",
            "start": clip.start,
            "end": clip.end,
            "duration": rendered_duration,
            "source_duration": clip.end - clip.start,
            "cleanup_applied": cleanup_applied,
            "montage_plan": montage_item or None,
            "score": clip.score,
            "reason": clip.reason,
            "hook": clip.hook,
            "payoff_ending": clip.payoff_ending,
            "transcript_excerpt": clip.transcript_excerpt,
            "semantic_boundary_evidence": clip.semantic_boundary_evidence,
            "ok": success,
        }

    manifest: list[dict] = []
    ok_count = 0
    if workers == 1:
        for ordinal, clip in enumerate(clips, 1):
            entry = render_one(clip, ordinal)
            manifest.append(entry)
            if entry["ok"]:
                ok_count += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(render_one, clip, ordinal): int(getattr(clip, "index", None) or ordinal)
                for ordinal, clip in enumerate(clips, 1)
            }
            results: dict[int, dict] = {}
            for future in as_completed(futures):
                entry = future.result()
                results[entry["index"]] = entry
                if entry["ok"]:
                    ok_count += 1
            manifest = [results[i] for i in sorted(results)]

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"clips": manifest, "ok_count": ok_count, "total": len(clips)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ Rendered {ok_count}/{len(clips)} clips")
    print(f"   Manifest: {manifest_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
