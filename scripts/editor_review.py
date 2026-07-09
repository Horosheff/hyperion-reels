#!/usr/bin/env python3
"""VideoShorts — local heuristic draft for editor-review.json."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from review_utils import best_candidate_for_clip, clean, clip_text, has_payoff, looks_incomplete, read_json, write_json
from videoshorts_core import configure_stdio, segments_from_json

configure_stdio()


def _clips_from(path: Path) -> list[dict]:
    data = read_json(path, {"clips": []})
    if isinstance(data, dict) and isinstance(data.get("clips"), list):
        return [c for c in data["clips"] if isinstance(c, dict)]
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        return [c for c in data["candidates"] if isinstance(c, dict)]
    return []


def review_clip(index: int, clip: dict, segments: list, candidate: dict) -> dict:
    start = float(clip.get("start", 0))
    end = float(clip.get("end", start))
    text = clean(
        clip.get("transcript_excerpt")
        or clip.get("semantic_boundary_evidence", {}).get("transcript_excerpt")
        or clip_text(segments, start, end),
        1000,
    )
    word_count = len(text.split())
    hook_text = clean(clip.get("hook") or text[:180], 220)
    needs_context = hook_text.lower().startswith(("и ", "а ", "ну ", "так вот", "то есть", "поэтому", "because", "so "))
    too_slow = word_count < 55 or (end - start > 52 and word_count < 110)
    no_payoff = not has_payoff(text) and looks_incomplete(text)
    duplicate_theme = False
    reject_reasons: list[str] = []
    if needs_context:
        reject_reasons.append("needs_context")
    if too_slow:
        reject_reasons.append("too_slow")
    if no_payoff:
        reject_reasons.append("no_payoff")
    if clip.get("reject_reason"):
        reject_reasons.append(str(clip.get("reject_reason")))
    keep = not reject_reasons
    return {
        "index": int(clip.get("index") or index),
        "candidate_id": candidate.get("candidate_id"),
        "start": round(start, 3),
        "end": round(end, 3),
        "keep": keep,
        "reject": not keep,
        "editor_notes": clean(
            "Оставить: есть самостоятельный тезис и темп подходит для Shorts."
            if keep else f"Отклонить/пересобрать: {', '.join(reject_reasons)}.",
            360,
        ),
        "needs_context": needs_context,
        "too_slow": too_slow,
        "no_payoff": no_payoff,
        "duplicate_theme": duplicate_theme,
        "candidate_reason": candidate.get("candidate_reason"),
        "transcript_excerpt": text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: editor review draft")
    parser.add_argument("moments", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--candidates", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.moments.is_file() or not args.transcript.is_file():
        print("[ERROR] moments or transcript not found", file=sys.stderr)
        sys.exit(1)

    transcript = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    segments = segments_from_json(transcript)
    clips = _clips_from(args.moments)
    candidates = read_json(args.candidates, {"candidates": []}).get("candidates", []) if args.candidates else []
    reviews = []
    for i, clip in enumerate(clips, 1):
        start = float(clip.get("start", 0))
        end = float(clip.get("end", start))
        candidate = best_candidate_for_clip(candidates, start, end)
        reviews.append(review_clip(i, clip, segments, candidate))

    payload = {
        "schema_version": 1,
        "artifact": "editor-review",
        "decision_source": "local_heuristic_draft",
        "local_fallback_note": "Это черновик для диагностики; в Agent mode videoshorts-editor обязан принять/исправить keep/reject сам.",
        "clips": reviews,
        "summary": {
            "total": len(reviews),
            "keep": sum(1 for item in reviews if item.get("keep")),
            "reject": sum(1 for item in reviews if item.get("reject")),
        },
    }
    out = args.output or (args.moments.parent / "editor-review.json")
    write_json(out, payload)
    print(f"✅ Editor review: {out} keep={payload['summary']['keep']} reject={payload['summary']['reject']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
