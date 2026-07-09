#!/usr/bin/env python3
"""VideoShorts — поиск лучших моментов по транскрипту."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from videoshorts_core import (
    clips_to_json,
    configure_stdio,
    enrich_semantic_boundaries,
    segments_from_json,
    select_clips,
    select_clips_advanced,
)

configure_stdio()


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: выбор хайлайтов 30-60 сек")
    parser.add_argument("transcript", type=Path, help="transcript.json от transcribe.py")
    parser.add_argument("-o", "--output", type=Path, default=None, help="moments.json")
    parser.add_argument("-c", "--clips", type=int, default=10, help="Количество клипов")
    parser.add_argument("--min", type=float, default=30, dest="min_sec", help="Мин. длина (сек)")
    parser.add_argument("--max", type=float, default=60, dest="max_sec", help="Макс. длина (сек)")
    parser.add_argument("--basic", action="store_true", help="Только webinar_cutter эвристики (без clip_selector)")
    args = parser.parse_args()

    if not args.transcript.is_file():
        print(f"[ERROR] Transcript not found: {args.transcript}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    segments = segments_from_json(data)
    if not segments:
        print("[ERROR] Empty transcript", file=sys.stderr)
        sys.exit(1)

    print(f"🔍 Selecting {args.clips} clips ({args.min_sec}-{args.max_sec}s)...")
    if args.basic:
        clips = select_clips(segments, args.clips, args.min_sec, args.max_sec)
    else:
        clips = select_clips_advanced(segments, args.clips, args.min_sec, args.max_sec)
    clips = enrich_semantic_boundaries(segments, clips, args.min_sec, args.max_sec)
    if not clips:
        print("[ERROR] No clips selected", file=sys.stderr)
        sys.exit(1)

    out_path = args.output or (Path("videoshorts-memory/moments") / f"{args.transcript.stem.replace('transcript', 'moments')}.json")
    if out_path.name == "transcript.json":
        out_path = out_path.parent / "moments.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        **clips_to_json(clips),
        "min_sec": args.min_sec,
        "max_sec": args.max_sec,
        "selection_contract": {
            "mode": "semantic_boundary",
            "fixed_duration": False,
            "duration_policy": "variable, transcript-boundary snapped, complete thought preferred",
            "required_evidence": [
                "why_start",
                "why_end",
                "hook",
                "payoff_ending",
                "transcript_excerpt",
                "variable_duration",
            ],
        },
        "source_transcript": str(args.transcript.resolve()),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ Selected {len(clips)} moments → {out_path}")
    for i, c in enumerate(clips, 1):
        print(f"   {i}: {c.start:.1f}-{c.end:.1f}s dur={c.end - c.start:.1f}s score={c.score:.0f} ({c.reason})")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
