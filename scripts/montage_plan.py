#!/usr/bin/env python3
"""VideoShorts — local heuristic draft for montage-plan.json."""
from __future__ import annotations

import argparse
import re
import sys
import traceback
from pathlib import Path

from review_utils import clean, items_by_index, read_json, write_json
from videoshorts_core import configure_stdio

configure_stdio()


def cleanup_items(cleanup: dict, start: float, end: float, key: str) -> list[dict]:
    items = cleanup.get(key, []) if isinstance(cleanup, dict) else []
    hits = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            s = float(item.get("start", -1))
            e = float(item.get("end", s))
        except Exception:
            continue
        if e >= start and s <= end:
            hits.append(item)
    return hits


def _parse_brief_bool(brief: Path | None, *keys: str, default: bool | None = None) -> bool | None:
    """Read zoomPunch/progressBar from 00-brief.md or run-request.json."""
    if brief is None:
        return default
    if not brief.is_file():
        return default
    text = brief.read_text(encoding="utf-8-sig")
    # JSON run-request
    if brief.suffix.lower() == ".json":
        try:
            data = read_json(brief, {})
            settings = data.get("settings") if isinstance(data.get("settings"), dict) else data
            for key in keys:
                if key in settings:
                    val = settings[key]
                    if isinstance(val, bool):
                        return val
                    return str(val).strip().lower() in {"1", "true", "yes", "on"}
        except Exception:
            return default
        return default
    # Markdown brief: zoomPunch: false / zoom_punch: false
    for key in keys:
        m = re.search(rf"(?im)^\s*{re.escape(key)}\s*[:=]\s*(\S+)", text)
        if m:
            return m.group(1).strip().lower() in {"1", "true", "yes", "on"}
    return default


def _filter_silences_for_montage(
    silences: list[dict],
    start: float,
    *,
    hook_protect_sec: float = 1.2,
) -> tuple[list[dict], list[dict]]:
    """Drop leading silence inside hook window; keep mid/late gaps for jump cuts."""
    kept: list[dict] = []
    preserved: list[dict] = []
    protect_until = start + hook_protect_sec
    for item in silences:
        try:
            s = float(item.get("start", -1))
            e = float(item.get("end", s))
        except Exception:
            kept.append(item)
            continue
        # Preserve intentional pause overlapping the hook window after do_not_cut_before
        if s < protect_until and e > start:
            preserved.append({**item, "montage_note": "preserve_hook_pause"})
            continue
        # Mid-phrase long gaps early in clip often sit inside a spoken beat — exclude from auto jump cuts
        dur = max(0.0, e - s)
        if s < start + 4.0 and dur >= 1.8:
            preserved.append({**item, "montage_note": "hard_exclude_mid_phrase_silence"})
            continue
        kept.append(item)
    return kept, preserved


def _bounded_cleanup(items: list[dict], start: float, end: float, min_duration: float) -> tuple[list[dict], list[dict], float]:
    max_remove = max(0.0, (end - start) - min_duration)
    removed = 0.0
    applied: list[dict] = []
    skipped: list[dict] = []
    for item in items:
        try:
            s = max(start, float(item.get("start", -1)))
            e = min(end, float(item.get("end", s)))
        except Exception:
            continue
        duration = max(0.0, e - s)
        if duration < 0.08:
            continue
        normalized = {**item, "start": round(s, 3), "end": round(e, 3), "duration": round(duration, 3)}
        if removed + duration > max_remove:
            skipped.append({**normalized, "skip_reason": "min_duration_guard"})
            continue
        applied.append(normalized)
        removed += duration
    return applied, skipped, round(removed, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: montage plan draft")
    parser.add_argument("refined_moments", type=Path)
    parser.add_argument("--cleanup-plan", type=Path, default=None)
    parser.add_argument("--dramaturgy-report", type=Path, default=None)
    parser.add_argument("--brief", type=Path, default=None, help="00-brief.md or run-request.json")
    parser.add_argument("--zoom-punch", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--progress-bar", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--b-roll", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--min-duration", type=float, default=30.0)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.refined_moments.is_file():
        print("[ERROR] refined moments not found", file=sys.stderr)
        sys.exit(1)
    refined = read_json(args.refined_moments, {"clips": []})
    cleanup = read_json(args.cleanup_plan, {})
    dramaturgy = items_by_index(read_json(args.dramaturgy_report, {"clips": []}))

    brief_path = args.brief
    if brief_path is None:
        # Prefer memory-root siblings of refined moments
        candidates = [
            args.refined_moments.resolve().parents[1] / "00-brief.md",
            args.refined_moments.resolve().parents[1] / "run-request.json",
            Path("videoshorts-memory/00-brief.md"),
            Path("videoshorts-memory/run-request.json"),
        ]
        for cand in candidates:
            if cand.is_file():
                brief_path = cand
                break

    brief_zoom = _parse_brief_bool(brief_path, "zoomPunch", "zoom_punch")
    brief_progress = _parse_brief_bool(brief_path, "progressBar", "progress_bar")
    brief_broll = _parse_brief_bool(brief_path, "bRoll", "b_roll", default=False)
    if args.zoom_punch is not None:
        zoom_default = bool(args.zoom_punch)
    elif brief_zoom is not None:
        zoom_default = brief_zoom
    else:
        zoom_default = None  # per-clip heuristic only when brief silent

    if args.progress_bar is not None:
        progress_default = bool(args.progress_bar)
    elif brief_progress is not None:
        progress_default = brief_progress
    else:
        progress_default = False
    broll_enabled = bool(args.b_roll) if args.b_roll is not None else bool(brief_broll)

    plans = []
    for i, clip in enumerate([c for c in refined.get("clips", []) if isinstance(c, dict)], 1):
        idx = int(clip.get("index") or i)
        start = float(clip.get("start", 0))
        end = float(clip.get("end", start))
        raw_duration = round(end - start, 3)
        safe = cleanup_items(cleanup, start, end, "safe_removal_plan")
        silences_raw = [item for item in safe if item.get("type") == "silence_gap"]
        fillers = [item for item in safe if item.get("type") == "filler_word"]
        silences, preserved = _filter_silences_for_montage(silences_raw, start)
        planned_items = [{**item, "source": "silence_remove"} for item in silences]
        planned_items.extend({**item, "source": "filler_remove"} for item in fillers)
        applied_cleanup, skipped_cleanup, estimated_removed = _bounded_cleanup(planned_items, start, end, args.min_duration)
        applied_silences = [item for item in applied_cleanup if item.get("source") == "silence_remove"]
        applied_fillers = [item for item in applied_cleanup if item.get("source") == "filler_remove"]
        d = dramaturgy.get(str(idx), {})
        jump_cuts = []
        for item in applied_silences[:8]:
            jump_cuts.append({
                "start": item.get("start"),
                "end": item.get("end"),
                "reason": "remove_silence_gap",
            })
        if zoom_default is not None:
            zoom_punch = zoom_default
        else:
            zoom_punch = bool(clip.get("hook_score", 0) and int(clip.get("hook_score") or 0) >= 55)
        plans.append({
            "index": idx,
            "start": round(start, 3),
            "end": round(end, 3),
            "raw_duration": raw_duration,
            "estimated_cleanup_removed_seconds": estimated_removed,
            "estimated_clean_duration": round(raw_duration - estimated_removed, 3),
            "cleanup_min_duration_guard": args.min_duration,
            "cleanup_skipped_for_min_duration": skipped_cleanup[:12],
            "jump_cuts": jump_cuts,
            "silence_remove": {
                "count": len(applied_silences),
                "items": applied_silences[:12],
                "preserved_hook_or_midphrase": preserved[:8],
            },
            "filler_remove": {
                "count": len(applied_fillers),
                "items": applied_fillers[:12],
            },
            "glue_notes": clean(
                "Сохранять причинно-следственную связку setup -> tension -> insight/result -> clean ending; "
                "не склеивать поверх смыслового перехода."
                if d.get("status") != "REJECT" else d.get("dramaturg_notes", ""),
                420,
            ),
            "zoom_punch": zoom_punch,
            "progress_bar": bool(progress_default),
            "b_roll_enabled": broll_enabled,
            "do_not_cut_before": round(start, 3),
            "do_not_cut_after": round(end, 3),
            "status": "REVIEW" if d.get("status") == "REJECT" else "READY_FOR_CUTTER",
        })
    payload = {
        "schema_version": 1,
        "artifact": "montage-plan",
        "decision_source": "local_heuristic_draft",
        "local_fallback_note": (
            "Черновик монтажного ТЗ; brief zoomPunch/progressBar перекрывают hook_score heuristic. "
            "Leading silence в окне hook (~1.2s) и mid-phrase gaps не попадают в jump_cuts."
        ),
        "brief_overrides": {
            "brief_path": str(brief_path.resolve()) if brief_path and brief_path.is_file() else None,
            "zoom_punch": zoom_default,
            "progress_bar": progress_default,
            "b_roll_enabled": broll_enabled,
        },
        "clips": plans,
        "summary": {
            "total": len(plans),
            "ready": sum(1 for item in plans if item.get("status") == "READY_FOR_CUTTER"),
            "review": sum(1 for item in plans if item.get("status") != "READY_FOR_CUTTER"),
            "zoom_punch_enabled_clips": sum(1 for item in plans if item.get("zoom_punch")),
            "brief_zoom_punch": zoom_default,
            "brief_progress_bar": progress_default,
            "brief_b_roll": broll_enabled,
        },
    }
    out = args.output or (args.refined_moments.parent / "montage-plan.json")
    write_json(out, payload)
    print(
        f"✅ Montage plan: {out} ready={payload['summary']['ready']} "
        f"review={payload['summary']['review']} zoom={payload['summary']['zoom_punch_enabled_clips']}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
