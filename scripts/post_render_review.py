#!/usr/bin/env python3
"""VideoShorts — local heuristic draft for post-render-review.json."""
from __future__ import annotations

import argparse
import subprocess
import sys
import traceback
from pathlib import Path

from review_utils import items_by_index, read_json, write_json
from videoshorts_core import configure_stdio

configure_stdio()


def probe(path: Path, entry: str) -> str | None:
    cmd = ["ffprobe", "-v", "error", "-show_entries", entry, "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: post-render review draft")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--qa-report", type=Path, default=None)
    parser.add_argument("--montage-plan", type=Path, default=None)
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.clips_dir.is_dir():
        print(f"[ERROR] clips_dir not found: {args.clips_dir}", file=sys.stderr)
        sys.exit(1)
    manifest = read_json(args.clips_dir / "manifest.json", {"clips": []})
    qa = read_json(args.qa_report or (args.clips_dir / "qa-report.json"), {"clips": []})
    montage = items_by_index(read_json(args.montage_plan, {"clips": []}))
    scores = items_by_index(read_json(args.scores, {"clips": []}))
    broll_report = read_json(args.clips_dir / "broll-report.json", {"clips": []})
    broll_by_index = {
        str(item.get("clip_index")): item for item in broll_report.get("clips", [])
        if isinstance(item, dict) and item.get("clip_index") is not None
    } if isinstance(broll_report, dict) else {}
    qa_by_file = {
        str(item.get("file")): item
        for item in qa.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(qa, dict) else {}
    reviews = []
    for i, clip in enumerate([c for c in manifest.get("clips", []) if isinstance(c, dict)], 1):
        idx = int(clip.get("index") or i)
        final_name = str(clip.get("final_file") or "")
        cropped_name = str(clip.get("cropped_file") or clip.get("file") or "")
        file_name = final_name if final_name and (args.clips_dir / final_name).is_file() else cropped_name
        path = args.clips_dir / file_name
        qa_item = qa_by_file.get(file_name) or qa_by_file.get(cropped_name) or {}
        duration_raw = probe(path, "format=duration") if path.is_file() else None
        duration = None
        try:
            duration = float(duration_raw) if duration_raw else None
        except Exception:
            duration = None
        reasons: list[str] = []
        subtitle_issue = False
        hook_failed = False
        audio_issue = False
        boundary_issue = False
        broll_issue = False
        if not path.is_file():
            reasons.append("missing_rendered_file")
        if qa_item.get("ok") is False:
            reasons.extend(qa_item.get("issues") or ["qa_failed"])
        if not final_name:
            subtitle_issue = True
            reasons.append("subtitle_burn_missing_or_not_requested")
        score = scores.get(str(idx), {})
        if score and int(score.get("hook_score") or 0) < 35:
            hook_failed = True
            reasons.append("hook_failed")
        if qa_item.get("has_audio") is False:
            audio_issue = True
            reasons.append("audio_issue")
        if duration is not None and clip.get("duration") and abs(float(clip.get("duration") or 0) - duration) > 4:
            boundary_issue = True
            reasons.append("boundary_duration_drift")
        if montage.get(str(idx), {}).get("status") == "REVIEW":
            boundary_issue = True
            reasons.append("montage_plan_requires_review")
        broll_item = broll_by_index.get(str(idx), {})
        if broll_item.get("status") == "FAIL":
            broll_issue = True
            reasons.append("broll_composite_failed")
        approve = not reasons
        reviews.append({
            "index": idx,
            "file": file_name,
            "approve": approve,
            "rerender_reason": ", ".join(sorted(set(reasons))) if reasons else None,
            "subtitle_issue": subtitle_issue,
            "hook_failed": hook_failed,
            "audio_issue": audio_issue,
            "boundary_issue": boundary_issue,
            "broll_issue": broll_issue,
            "duration": duration,
            "reviewer_notes": (
                "Render looks usable for packaging."
                if approve else "Нужен retry/rerender перед финальной упаковкой."
            ),
        })
    payload = {
        "schema_version": 1,
        "artifact": "post-render-review",
        "decision_source": "local_heuristic_draft",
        "local_fallback_note": "Черновик; в Agent mode videoshorts-post-render-reviewer должен оценить готовые клипы, а не только JSON.",
        "clips": reviews,
        "summary": {
            "total": len(reviews),
            "approved": sum(1 for item in reviews if item.get("approve")),
            "rejected": sum(1 for item in reviews if not item.get("approve")),
        },
    }
    out = args.output or (args.clips_dir / "post-render-review.json")
    write_json(out, payload)
    print(f"✅ Post-render review: {out} approved={payload['summary']['approved']} rejected={payload['summary']['rejected']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
