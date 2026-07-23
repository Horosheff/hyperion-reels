#!/usr/bin/env python3
"""VideoShorts — local heuristic draft for dramaturgy-report.json."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from review_utils import clean, clip_text, has_payoff, items_by_index, looks_incomplete, read_json, write_json
from videoshorts_core import configure_stdio, segments_from_json
from agent_artifact_guard import add_decision_mode_args, enforce_decision_mode, stamp_heuristic

configure_stdio()


def thirds(text: str) -> tuple[str, str, str, str]:
    words = text.split()
    if not words:
        return "", "", "", ""
    q1 = max(1, len(words) // 4)
    q2 = max(q1 + 1, len(words) // 2)
    q3 = max(q2 + 1, (len(words) * 3) // 4)
    return (
        clean(" ".join(words[:q1]), 220),
        clean(" ".join(words[q1:q2]), 240),
        clean(" ".join(words[q2:q3]), 260),
        clean(" ".join(words[q3:]), 260),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: dramaturgy report draft")
    parser.add_argument("refined_moments", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--editor-review", type=Path, default=None)
    parser.add_argument("--virality-review", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    add_decision_mode_args(parser)
    args = parser.parse_args()
    _artifact_path = args.output or (args.refined_moments.parent / 'dramaturgy-report.json')
    enforce_decision_mode(args, kind='dramaturgy-report', path=_artifact_path)
    if not args.refined_moments.is_file() or not args.transcript.is_file():
        print("[ERROR] refined moments or transcript not found", file=sys.stderr)
        sys.exit(1)
    refined = read_json(args.refined_moments, {"clips": []})
    transcript = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    segments = segments_from_json(transcript)
    editor = items_by_index(read_json(args.editor_review, {"clips": []}))
    virality = items_by_index(read_json(args.virality_review, {"clips": []}))
    reports = []
    for i, clip in enumerate([c for c in refined.get("clips", []) if isinstance(c, dict)], 1):
        idx = int(clip.get("index") or i)
        start = float(clip.get("start", 0))
        end = float(clip.get("end", start))
        text = clean(clip.get("transcript_excerpt") or clip_text(segments, start, end), 1400)
        setup, tension, insight, ending = thirds(text)
        e = editor.get(str(idx), {})
        v = virality.get(str(idx), {})
        issues = []
        if not setup:
            issues.append("missing_setup")
        if len(tension.split()) < 6:
            issues.append("weak_tension")
        if not has_payoff(text):
            issues.append("weak_insight_or_result")
        if looks_incomplete(text):
            issues.append("unclean_ending")
        if e.get("reject"):
            issues.append("editor_rejected")
        if v.get("status") == "REJECT":
            issues.append("virality_rejected")
        reports.append({
            "index": idx,
            "start": round(start, 3),
            "end": round(end, 3),
            "setup": setup,
            "tension": tension,
            "insight_or_result": insight,
            "clean_ending": ending,
            "structure": "setup -> tension -> insight/result -> clean ending",
            "status": "REJECT" if issues else "PASS",
            "issues": issues,
            "dramaturg_notes": clean(
                "Дуга мысли читается без полного видео."
                if not issues else f"Нужно поправить драматургию/границы: {', '.join(issues)}.",
                420,
            ),
        })
    payload = {
        "schema_version": 1,
        "artifact": "dramaturgy-report",
        "decision_source": "local_heuristic_draft",
        "local_fallback_note": "Черновик; в Agent mode videoshorts-dramaturg подтверждает дугу мысли вручную.",
        "clips": reports,
        "summary": {
            "total": len(reports),
            "passed": sum(1 for item in reports if item.get("status") == "PASS"),
            "rejected": sum(1 for item in reports if item.get("status") == "REJECT"),
        },
    }
    out = args.output or (args.refined_moments.parent / "dramaturgy-report.json")
    write_json(out, stamp_heuristic(payload, 'dramaturgy_report'))
    print(f"✅ Dramaturgy report: {out} pass={payload['summary']['passed']} reject={payload['summary']['rejected']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
