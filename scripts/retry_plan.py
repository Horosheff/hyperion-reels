#!/usr/bin/env python3
"""VideoShorts — строит retry-plan.json по run-state/manifest/QA."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from videoshorts_core import configure_stdio

configure_stdio()


def _read(path: Path, default):
    if path and path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def build_retry_plan(clips_dir: Path, state_path: Path | None = None) -> dict:
    manifest = _read(clips_dir / "manifest.json", {"clips": []})
    qa = _read(clips_dir / "qa-report.json", {})
    state = _read(state_path, {}) if state_path else {}
    memory_root = Path(__file__).resolve().parents[1] / "videoshorts-memory"
    moments_root = memory_root / "moments"
    decisions = _read(moments_root / "clip-decisions.json", {"clips": []})
    editor = _read(moments_root / "editor-review.json", {"clips": []})
    virality = _read(moments_root / "virality-review.json", {"clips": []})
    post_render = _read(clips_dir / "post-render-review.json", {"clips": []})
    failed: list[dict] = []

    qa_by_file = {
        str(item.get("file")): item
        for item in qa.get("clips", []) if isinstance(item, dict) and item.get("file")
    } if isinstance(qa, dict) else {}
    decisions_by_index = {
        str(item.get("index")): item
        for item in decisions.get("clips", []) if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(decisions, dict) else {}
    editor_by_index = {
        str(item.get("index")): item
        for item in editor.get("clips", []) if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(editor, dict) else {}
    virality_by_index = {
        str(item.get("index")): item
        for item in virality.get("clips", []) if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(virality, dict) else {}
    post_by_index = {
        str(item.get("index")): item
        for item in post_render.get("clips", []) if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(post_render, dict) else {}

    for clip in manifest.get("clips", []) if isinstance(manifest, dict) else []:
        if not isinstance(clip, dict):
            continue
        file_name = str(clip.get("final_file") or clip.get("cropped_file") or clip.get("file") or "")
        qa_item = qa_by_file.get(file_name) or qa_by_file.get(str(clip.get("cropped_file") or ""))
        reasons: list[str] = []
        if clip.get("ok") is False:
            reasons.append("render_failed")
        if qa_item and qa_item.get("ok") is False:
            reasons.extend(qa_item.get("issues") or ["qa_failed"])
        if file_name and not (clips_dir / file_name).is_file() and not (clips_dir / str(clip.get("cropped_file") or "")).is_file():
            reasons.append("missing_file")
        idx = str(clip.get("index"))
        decision_item = decisions_by_index.get(idx, {})
        if not decision_item:
            reasons.append("no_agent_decision")
        elif decision_item.get("agent_confirmation_required") or decision_item.get("selected_by_agent") is False:
            reasons.append("agent_decision_not_confirmed")
        editor_item = editor_by_index.get(idx, {})
        if editor_item.get("reject"):
            reasons.append("editor_rejected")
        virality_item = virality_by_index.get(idx, {})
        if virality_item.get("status") == "REJECT":
            reasons.append(str(virality_item.get("reject_reason") or "virality_below_threshold"))
        post_item = post_by_index.get(idx, {})
        if post_item and post_item.get("approve") is False:
            reasons.append(str(post_item.get("rerender_reason") or "post_render_rejected"))
        if reasons:
            failed.append({
                "index": clip.get("index"),
                "file": file_name,
                "start": clip.get("start"),
                "end": clip.get("end"),
                "reasons": sorted(set(reasons)),
                "retry_stage": (
                    "cutter" if "render_failed" in reasons or "missing_file" in reasons
                    else "post-render-reviewer" if post_item and post_item.get("approve") is False
                    else "agent-review-loop" if any(r in reasons for r in ("no_agent_decision", "agent_decision_not_confirmed", "editor_rejected")) or any("virality" in r for r in reasons)
                    else "guardian"
                ),
            })

    for item in state.get("failed_clips", []) if isinstance(state, dict) else []:
        if isinstance(item, dict) and item not in failed:
            failed.append(item)

    return {
        "schema_version": 1,
        "clips_dir": str(clips_dir.resolve()),
        "run_state": str(state_path.resolve()) if state_path and state_path.is_file() else None,
        "status": "RETRY_NEEDED" if failed else "NO_RETRY_NEEDED",
        "failed_clips": failed,
        "retryable_stages": sorted(set(str(item.get("retry_stage")) for item in failed if item.get("retry_stage"))),
        "incident_policy": {
            "no_agent_decision": "retry-or-open-incident",
            "editor_rejected": "retry-or-open-incident",
            "virality_below_threshold": "retry-or-open-incident",
            "post_render_rejected": "retry-or-open-incident",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: create retry-plan.json")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()
    plan = build_retry_plan(args.clips_dir, args.state)
    out = args.output or (args.clips_dir / "retry-plan.json")
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Retry plan: {out} ({plan['status']})")


if __name__ == "__main__":
    main()
