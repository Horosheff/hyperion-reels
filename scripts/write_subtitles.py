#!/usr/bin/env python3
"""VideoShorts — генерация ASS/SRT субтитров для каждого клипа."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from subtitle_engine import list_templates, load_custom_template, write_ass, write_srt_for_clip
from videoshorts_core import clips_from_json, configure_stdio, segments_from_json, words_from_transcript_json

configure_stdio()


def _load_cutter_manifest(output_dir: Path) -> dict[int, dict]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    result: dict[int, dict] = {}
    for item in data.get("clips", []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and item.get("index") is not None:
            result[int(item["index"])] = item
    return result


def _cut_intervals(manifest_item: dict | None) -> list[tuple[float, float]]:
    if not manifest_item:
        return []
    cleanup = manifest_item.get("cleanup_applied") or {}
    intervals: list[tuple[float, float]] = []
    for item in cleanup.get("items", []) or []:
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end - start >= 0.08:
            intervals.append((start, end))
    intervals.sort()
    return intervals


def _removed_before(time_value: float, intervals: list[tuple[float, float]]) -> float:
    removed = 0.0
    for start, end in intervals:
        if time_value <= start:
            break
        removed += max(0.0, min(time_value, end) - start)
    return removed


def _inside_removed(start: float, end: float, intervals: list[tuple[float, float]]) -> bool:
    midpoint = (start + end) / 2
    return any(cut_start <= midpoint <= cut_end for cut_start, cut_end in intervals)


def _removed_timed_items(items: list[dict], clip_start: float, clip_end: float, intervals: list[tuple[float, float]]) -> list[dict]:
    removed: list[dict] = []
    if not intervals:
        return removed
    for item in items:
        try:
            original_start = max(clip_start, float(item["start"]))
            original_end = min(clip_end, float(item["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        if original_end <= clip_start or original_start >= clip_end or original_end <= original_start:
            continue
        if _inside_removed(original_start, original_end, intervals):
            removed.append({
                "start": round(original_start, 3),
                "end": round(original_end, 3),
                "text": str(item.get("word") or item.get("text") or "").strip(),
            })
    return removed


def _remap_timed_items(items: list[dict], clip_start: float, clip_end: float, intervals: list[tuple[float, float]]) -> list[dict]:
    if not intervals:
        return [
            {**item, "start": max(0.0, float(item["start"]) - clip_start), "end": min(clip_end - clip_start, float(item["end"]) - clip_start)}
            for item in items
            if float(item.get("end", 0)) > clip_start and float(item.get("start", 0)) < clip_end
        ]

    remapped: list[dict] = []
    for item in items:
        try:
            original_start = max(clip_start, float(item["start"]))
            original_end = min(clip_end, float(item["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        if original_end <= clip_start or original_start >= clip_end or original_end <= original_start:
            continue
        if _inside_removed(original_start, original_end, intervals):
            continue
        start = original_start - clip_start - _removed_before(original_start, intervals)
        end = original_end - clip_start - _removed_before(original_end, intervals)
        if end - start < 0.03:
            continue
        remapped.append({**item, "start": max(0.0, start), "end": max(0.0, end)})
    return remapped


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: ASS/SRT per clip")
    parser.add_argument("transcript", type=Path, help="transcript.json")
    parser.add_argument("moments", type=Path, help="moments.json")
    parser.add_argument("-o", "--output-dir", type=Path, required=True, help="clips dir with cropped mp4")
    parser.add_argument("-t", "--template", default="mrbeast", choices=list_templates())
    parser.add_argument("--template-json", type=Path, default=None, help="Custom JSON subtitle template")
    parser.add_argument("--format", choices=("ass", "srt", "both"), default="ass")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--karaoke", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--emoji", action=argparse.BooleanOptionalAction, default=False, help="Rule-based emoji subtitles")
    parser.add_argument("--hook-style", action=argparse.BooleanOptionalAction, default=None, help="Scale first word in each ASS line")
    parser.add_argument("--hook-scale", type=float, default=None, help="ASS hook-style scale, default 1.3")
    args = parser.parse_args()

    if not args.transcript.is_file() or not args.moments.is_file():
        print("[ERROR] transcript or moments not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    moments = json.loads(args.moments.read_text(encoding="utf-8-sig"))
    segments = [s.__dict__ for s in segments_from_json(data)]
    clips = clips_from_json(moments)
    raw_clips = [c for c in moments.get("clips", []) if isinstance(c, dict)]
    words = words_from_transcript_json(data)
    cutter_manifest = _load_cutter_manifest(args.output_dir)

    if args.template_json and not load_custom_template(args.template_json):
        print(f"[ERROR] Custom template is invalid or missing: {args.template_json}", file=sys.stderr)
        sys.exit(1)
    if args.hook_style is not None:
        import os
        os.environ["VIDEOSHORTS_SUBTITLES_HOOK_STYLE"] = "1" if args.hook_style else "0"
    if args.hook_scale is not None:
        import os
        os.environ["VIDEOSHORTS_SUBTITLES_HOOK_SCALE"] = str(args.hook_scale)

    sub_dir = args.output_dir / "subtitles"
    sub_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    use_ass = args.format in ("ass", "both") and words and args.karaoke
    keep_indexes: set[int] = set()

    for i, clip in enumerate(clips, 1):
        raw = raw_clips[i - 1] if i - 1 < len(raw_clips) else {}
        idx = int(raw.get("index") or i)
        keep_indexes.add(idx)
        ass_path = sub_dir / f"clip_{idx:02d}.ass"
        srt_path = sub_dir / f"clip_{idx:02d}.srt"
        cutter_item = cutter_manifest.get(idx)
        intervals = _cut_intervals(cutter_item)
        rendered_duration = float((cutter_item or {}).get("duration") or (clip.end - clip.start))
        removed_words = _removed_timed_items(words, clip.start, clip.end, intervals)
        removed_segments = _removed_timed_items(segments, clip.start, clip.end, intervals) if not words else []
        remapped_words = _remap_timed_items(words, clip.start, clip.end, intervals)
        remapped_segments = _remap_timed_items(segments, clip.start, clip.end, intervals)
        entry = {
            "index": idx,
            "start": clip.start,
            "end": clip.end,
            "rendered_duration": rendered_duration,
            "cleanup_remap": bool(intervals),
            "removed_subtitle_words": len(removed_words),
            "removed_subtitle_segments": len(removed_segments),
            "removed_subtitle_text_samples": [item["text"] for item in removed_words[:12] if item.get("text")],
        }

        if use_ass:
            write_ass(
                ass_path,
                remapped_words,
                0.0,
                rendered_duration,
                args.template,
                args.width,
                args.height,
                custom_template=args.template_json,
                emoji=args.emoji,
            )
            entry["ass"] = str(ass_path.name)
        if args.format in ("srt", "both") or not use_ass:
            write_srt_for_clip(srt_path, remapped_segments, 0.0, rendered_duration, words=remapped_words)
            entry["srt"] = str(srt_path.name)

        manifest.append(entry)
        print(f"   clip {idx}: subtitles → {sub_dir}")

    # Drop stale ASS/SRT from previous larger keep sets (e.g. 10 → 7)
    removed = 0
    for stale in list(sub_dir.glob("clip_*.ass")) + list(sub_dir.glob("clip_*.srt")):
        try:
            n = int(stale.stem.split("_")[1])
        except Exception:
            continue
        if n not in keep_indexes:
            stale.unlink(missing_ok=True)
            removed += 1
    if removed:
        print(f"   [info] removed {removed} stale subtitle file(s)")

    (args.output_dir / "subtitles-manifest.json").write_text(
        json.dumps(
            {
                "template": args.template,
                "template_json": str(args.template_json.resolve()) if args.template_json else None,
                "format": args.format,
                "karaoke": bool(use_ass),
                "emoji": bool(args.emoji),
                "clips": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"✅ Subtitles for {len(clips)} clips in {sub_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
