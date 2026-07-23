#!/usr/bin/env python3
"""VideoShorts — local heuristic draft for virality-review.json."""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

from review_utils import clean, clip_text, has_payoff, items_by_index, read_json, write_json
from videoshorts_core import analyze_hook_quality_2026, configure_stdio, segments_from_json
from agent_artifact_guard import add_decision_mode_args, enforce_decision_mode, stamp_heuristic

configure_stdio()


def score_dimension(text: str, patterns: tuple[str, ...], base: int = 28) -> int:
    value = base + min(28, len(text.split()) // 4)
    low = text.lower()
    for pattern in patterns:
        if re.search(pattern, low):
            value += 18
    return max(0, min(100, value))


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: virality critic draft")
    parser.add_argument("moments", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("--editor-review", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--threshold", type=int, default=55)
    add_decision_mode_args(parser)
    args = parser.parse_args()
    _artifact_path = args.output or (args.moments.parent / 'virality-review.json')
    enforce_decision_mode(args, kind='virality-review', path=_artifact_path)
    if not args.moments.is_file() or not args.transcript.is_file():
        print("[ERROR] moments or transcript not found", file=sys.stderr)
        sys.exit(1)

    moments = read_json(args.moments, {"clips": []})
    transcript = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    segments = segments_from_json(transcript)
    scores = items_by_index(read_json(args.scores, {"clips": []}))
    editor = items_by_index(read_json(args.editor_review, {"clips": []}))
    reviews: list[dict] = []
    for i, clip in enumerate([c for c in moments.get("clips", []) if isinstance(c, dict)], 1):
        idx = int(clip.get("index") or i)
        start = float(clip.get("start", 0))
        end = float(clip.get("end", start))
        text = clean(clip.get("transcript_excerpt") or clip_text(segments, start, end), 1200)
        hook = analyze_hook_quality_2026(text, clean(clip.get("hook") or text[:180], 220))
        shareability = score_dimension(text, (r"(ошиб|нельзя|секрет|правда|миф|быстр|рост)",))
        comment_trigger = score_dimension(text, (r"(а вы|как вы|согласны|спорн|коммент|думаете|\?)",), 22)
        curiosity_gap = score_dimension(text, (r"(почему|вот что|вот почему|секрет|причина|мало кто)",), 24)
        save_value = score_dimension(text, (r"(шаг|способ|чеклист|формул|запомните|сохран|инструкц)",), 24)
        agent_score = scores.get(str(idx), {})
        aggregate = int(shareability * 0.28 + comment_trigger * 0.18 + curiosity_gap * 0.27 + save_value * 0.17 + int(hook.get("score") or 0) * 0.10)
        if agent_score.get("virality_score") is not None:
            aggregate = int(aggregate * 0.72 + int(agent_score.get("virality_score") or 0) * 0.28)
        editor_item = editor.get(str(idx), {})
        reject_reasons: list[str] = []
        if aggregate < args.threshold:
            reject_reasons.append("virality_below_threshold")
        if editor_item.get("reject"):
            reject_reasons.append("editor_rejected")
        reviews.append({
            "index": idx,
            "start": round(start, 3),
            "end": round(end, 3),
            "shareability": shareability,
            "comment_trigger": comment_trigger,
            "curiosity_gap": curiosity_gap,
            "save_value": save_value,
            "virality_score": aggregate,
            "threshold": args.threshold,
            "status": "REJECT" if reject_reasons else "PASS",
            "reject_reason": ", ".join(reject_reasons) if reject_reasons else None,
            "critic_notes": clean(
                "Есть повод досмотреть/сохранить/обсудить."
                if not reject_reasons else f"Слабый вирусный контур: {', '.join(reject_reasons)}.",
                360,
            ),
        })

    payload = {
        "schema_version": 1,
        "artifact": "virality-review",
        "decision_source": "local_heuristic_draft",
        "local_fallback_note": "Черновик; в Agent mode videoshorts-virality-critic вручную оценивает shareability/comment_trigger/curiosity_gap/save_value.",
        "clips": reviews,
        "summary": {
            "total": len(reviews),
            "passed": sum(1 for item in reviews if item.get("status") == "PASS"),
            "rejected": sum(1 for item in reviews if item.get("status") == "REJECT"),
            "threshold": args.threshold,
        },
    }
    out = args.output or (args.moments.parent / "virality-review.json")
    write_json(out, stamp_heuristic(payload, 'virality_review'))
    print(f"✅ Virality review: {out} pass={payload['summary']['passed']} reject={payload['summary']['rejected']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
