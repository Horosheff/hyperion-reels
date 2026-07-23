#!/usr/bin/env python3
"""VideoShorts — уточнение start/end по сегментам, словам и паузам."""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from videoshorts_core import Clip, configure_stdio, segments_from_json, words_from_transcript_json
from agent_artifact_guard import add_decision_mode_args, enforce_decision_mode, stamp_heuristic

configure_stdio()


def _clean(text: str, limit: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if limit and len(value) > limit:
        return value[: max(0, limit - 3)].rstrip(" ,.;:") + "..."
    return value


def _load_json(path: Path | None, default):
    if not path or not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _clip_text(segments: list, start: float, end: float) -> str:
    return _clean(" ".join(s.text for s in segments if s.end > start and s.start < end), 900)


def _overlapping_items(cleanup: dict, start: float, end: float, key: str) -> list[dict]:
    if not isinstance(cleanup, dict):
        return []
    items = cleanup.get(key, [])
    hits: list[dict] = []
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


def _estimated_cleanup_removal(
    cleanup: dict,
    start: float,
    end: float,
    *,
    hook_protect_sec: float = 1.2,
) -> tuple[float, list[dict]]:
    """Estimate final duration after safe cleanup before cutter runs.

    This is intentionally conservative: preserve the first hook beat and count
    only safe silence/filler spans. Review-only false starts stay for agents.
    """
    applied: list[dict] = []
    total = 0.0
    protect_until = start + hook_protect_sec
    for item in _overlapping_items(cleanup, start, end, "safe_removal_plan"):
        if not item.get("safe", True):
            continue
        try:
            s = max(start, float(item.get("start", -1)))
            e = min(end, float(item.get("end", s)))
        except Exception:
            continue
        if e - s < 0.08:
            continue
        if item.get("type") == "silence_gap" and s < protect_until and e > start:
            continue
        duration = e - s
        total += duration
        applied.append({
            "type": item.get("type"),
            "start": round(s, 3),
            "end": round(e, 3),
            "duration": round(duration, 3),
            "text": item.get("text"),
        })
    return round(total, 3), applied


def _duration_estimate(start: float, end: float, cleanup: dict) -> dict:
    raw_duration = round(end - start, 3)
    estimated_removed, items = _estimated_cleanup_removal(cleanup, start, end)
    return {
        "raw_duration": raw_duration,
        "estimated_removed_seconds": estimated_removed,
        "estimated_clean_duration": round(max(0.0, raw_duration - estimated_removed), 3),
        "estimated_items": items[:30],
    }


def _trim_cleanup_edges(
    start: float,
    end: float,
    cleanup: dict,
    *,
    protect_hook_start: bool = True,
) -> tuple[float, float, dict]:
    """Trim edge silence — but never eat the first ~1.2s after a thought_start hook.

    Leading silence right after the hook word is often intentional pause/punch;
    snapping start forward (383.58→385.26) kills the hook.
    """
    safe_items = _overlapping_items(cleanup, start, end, "safe_removal_plan")
    leading = []
    trailing = []
    original_start = start
    hook_protect_until = original_start + 1.2 if protect_hook_start else original_start
    for item in safe_items:
        try:
            s = float(item.get("start", -1))
            e = float(item.get("end", s))
        except Exception:
            continue
        if item.get("type") == "silence_gap" and start <= s <= start + 1.4 and e > start:
            # Skip silence that begins inside the protected hook window
            if protect_hook_start and s < hook_protect_until:
                continue
            start = max(start, e)
            leading.append(item)
        if item.get("type") == "silence_gap" and end - 1.4 <= s <= end and e >= end:
            end = min(end, s)
            trailing.append(item)
    return round(start, 3), round(end, 3), {
        "safe_items_in_clip": len(safe_items),
        "leading_silence_trimmed": leading,
        "trailing_silence_trimmed": trailing,
        "hook_start_protected": protect_hook_start,
        "fillers_in_clip": [item for item in safe_items if item.get("type") == "filler_word"][:20],
        "review_only_in_clip": _overlapping_items(cleanup, start, end, "review_only")[:12],
    }


def _looks_incomplete_ending(text: str) -> bool:
    clean = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not clean:
        return True
    tail = clean[-180:].strip(" \t\r\n.,!?…:;—-")
    dangling_prefixes = (
        "первое",
        "второе",
        "третье",
        "дальше",
        "следующее",
        "сейчас объясню",
        "сейчас покажу",
        "давайте посмотрим",
        "next",
        "first",
        "second",
        "let me explain",
    )
    return tail.startswith(dangling_prefixes) or tail in {"так", "итак", "сейчас", "дальше"}


def _has_finished_payoff_closer(raw: dict, evidence: dict, text: str) -> bool:
    """True when clip already ends on a finished payoff — do not expand past it."""
    if raw.get("payoff_ending") or evidence.get("payoff_ending"):
        return True
    if evidence.get("why_end") and re.search(r"[.!?…]\s*$", text or ""):
        return True
    try:
        from review_utils import has_payoff
        if text and has_payoff(text) and re.search(r"[.!?…]\s*$", text):
            return True
    except Exception:
        pass
    return bool(text and re.search(r"[.!?…]\s*$", text) and not _looks_incomplete_ending(text))


def _topic_shift_after_expand(before_text: str, after_text: str) -> bool:
    """Heuristic: expansion pulled in a new unrelated opener (e.g. Tilda after Cursor payoff)."""
    before = re.sub(r"\s+", " ", (before_text or "").strip().lower())
    after = re.sub(r"\s+", " ", (after_text or "").strip().lower())
    if not before or not after or len(after) <= len(before) + 12:
        return False
    added = after[len(before):].strip(" ,.;:!?…—-")
    if len(added) < 18:
        return False
    # New sentence that looks like a fresh topic / product digression
    new_openers = (
        r"^(внутрянка|тильд|tilda|а\s+ещ[её]|теперь\s+про|следующ|"
        r"кстати|отдельно|другой\s+момент|перейд[её]м)",
    )
    first = added.split(".")[0].strip() if added else ""
    return any(re.search(p, first, re.I) for p in new_openers)


_HARD_SCORE_REJECTS = (
    "incomplete_thought",
    "clipped_ending",
    "contextless_start",
    "boring_or_low_viral_potential",
    "weak_hook_first_3s",
    "too_short",
    "too_long",
)


def _score_reject_tokens(score: dict, raw: dict) -> list[str]:
    raw_reason = str(score.get("reject_reason") or raw.get("reject_reason") or "")
    reasons = score.get("reject_reasons") if isinstance(score.get("reject_reasons"), list) else []
    tokens = [raw_reason] if raw_reason else []
    tokens.extend(str(r) for r in reasons if r)
    # Also split comma/semicolon lists
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(re.split(r"[,;|/]+", token))
    return [t.strip().lower() for t in expanded if t and t.strip()]


def _has_finished_thought(raw: dict, evidence: dict, text: str, score: dict) -> tuple[bool, str | None]:
    tokens = _score_reject_tokens(score, raw)
    for hard in _HARD_SCORE_REJECTS:
        hit = next((t for t in tokens if hard in t), None)
        if hit:
            return False, hit
    # Bare `weak_hook` (without first_3s) is soft — agent/scorekeeper may override
    if evidence.get("why_end") and (raw.get("payoff_ending") or evidence.get("payoff_ending") or re.search(r"[.!?…]\s*$", text)):
        return True, None
    if raw.get("payoff_ending") and not _looks_incomplete_ending(text):
        return True, None
    if re.search(r"[.!?…]\s*$", text) and not _looks_incomplete_ending(text):
        return True, None
    return False, "missing_finished_thought_evidence"


def _candidate_boundaries(segments: list, words: list[dict], cleanup: dict) -> list[float]:
    points: set[float] = set()
    for seg in segments:
        points.add(round(float(seg.start), 3))
        points.add(round(float(seg.end), 3))
    for word in words:
        try:
            points.add(round(float(word.get("start", 0)), 3))
            points.add(round(float(word.get("end", 0)), 3))
        except Exception:
            pass
    for gap in cleanup.get("silence_gaps", []) if isinstance(cleanup, dict) else []:
        try:
            points.add(round(float(gap.get("start")), 3))
            points.add(round(float(gap.get("end")), 3))
        except Exception:
            pass
    return sorted(p for p in points if p >= 0)


def _nearest(points: list[float], target: float, direction: str, window: float = 2.5) -> float:
    if not points:
        return round(target, 3)
    if direction == "start":
        candidates = [p for p in points if target - window <= p <= target + window]
        candidates.sort(key=lambda p: (abs(p - target), 0 if p >= target else 1))
    else:
        candidates = [p for p in points if target - window <= p <= target + window]
        candidates.sort(key=lambda p: (abs(p - target), 0 if p <= target else 1))
    return round(candidates[0] if candidates else target, 3)


def _score_by_index(scores: dict) -> dict[str, dict]:
    return {
        str(item.get("index")): item
        for item in scores.get("clips", []) if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(scores, dict) else {}


def refine_clip(index: int, raw: dict, segments: list, points: list[float], cleanup: dict, score: dict, min_sec: float, max_sec: float) -> tuple[dict | None, dict | None]:
    original_start = float(raw.get("start", 0))
    original_end = float(raw.get("end", original_start))
    start = _nearest(points, original_start, "start")
    end = _nearest(points, original_end, "end")
    start, end, cleanup_refinement = _trim_cleanup_edges(start, end, cleanup)
    duration = end - start

    if duration < min_sec:
        target_end = min(start + max(min_sec, duration), segments[-1].end if segments else original_end)
        end = _nearest(points, target_end, "end", window=4.0)
    clean_estimate = _duration_estimate(start, end, cleanup)
    expansion_attempts = []
    text_before_expand = _clip_text(segments, start, end)
    evidence_pre = raw.get("semantic_boundary_evidence") if isinstance(raw.get("semantic_boundary_evidence"), dict) else {}
    # INC-0917: if thought already has finished payoff, prefer keeping punch/silence
    # over expanding into the next unrelated topic just to pad clean duration.
    payoff_locked = _has_finished_payoff_closer(raw, evidence_pre, text_before_expand)
    # Account for expected cuts before render: choose a wider raw window when
    # cleanup would make the final clip too short — but never past a finished payoff
    # into a new micro-topic.
    for _ in range(4):
        if clean_estimate["estimated_clean_duration"] >= min_sec:
            break
        if payoff_locked:
            expansion_attempts.append({
                "from_end": round(end, 3),
                "to_end": round(end, 3),
                "clean_before": clean_estimate["estimated_clean_duration"],
                "reason": "skip_expand_past_finished_payoff",
            })
            break
        deficit = min_sec - clean_estimate["estimated_clean_duration"]
        raw_cap = max_sec + min(20.0, clean_estimate["estimated_removed_seconds"] + deficit + 0.5)
        if end - start >= raw_cap:
            break
        target_end = min(
            start + raw_cap,
            end + deficit + 0.8,
            segments[-1].end if segments else original_end,
        )
        new_end = _nearest(points, target_end, "end", window=4.0)
        if new_end <= end:
            break
        text_after = _clip_text(segments, start, new_end)
        if _topic_shift_after_expand(text_before_expand, text_after):
            expansion_attempts.append({
                "from_end": round(end, 3),
                "to_end": round(new_end, 3),
                "clean_before": clean_estimate["estimated_clean_duration"],
                "reason": "blocked_expand_topic_shift",
            })
            break
        expansion_attempts.append({
            "from_end": round(end, 3),
            "to_end": round(new_end, 3),
            "clean_before": clean_estimate["estimated_clean_duration"],
            "reason": "estimated_clean_duration_below_min",
        })
        end = new_end
        clean_estimate = _duration_estimate(start, end, cleanup)
    if end - start > max_sec and clean_estimate["estimated_clean_duration"] > max_sec:
        target_end = start + max_sec
        end = _nearest(points, target_end, "end", window=4.0)
        clean_estimate = _duration_estimate(start, end, cleanup)
    if end <= start:
        end = round(start + min_sec, 3)
        clean_estimate = _duration_estimate(start, end, cleanup)

    duration = round(end - start, 3)
    text = _clip_text(segments, start, end)
    evidence = raw.get("semantic_boundary_evidence") if isinstance(raw.get("semantic_boundary_evidence"), dict) else {}
    finished, reject_gate = _has_finished_thought(raw, evidence, text, score)
    if not finished:
        rejected = {
            **raw,
            "index": index,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": duration,
            "status": "REJECT",
            "reject_reason": reject_gate,
            "transcript_excerpt": text or raw.get("transcript_excerpt", ""),
            "boundary_refinement": {
                "status": "rejected",
                "reason": reject_gate,
                "original_start": round(original_start, 3),
                "original_end": round(original_end, 3),
                "cleanup_refinement": cleanup_refinement,
            },
        }
        return None, rejected
    evidence = {
        **evidence,
        "why_start": f"Boundary-refiner поставил начало на ближайшую границу речи/паузы: {start:.3f}s.",
        "why_end": f"Boundary-refiner поставил конец на ближайшую границу речи/паузы: {end:.3f}s.",
        "variable_duration": duration,
        "refined_from": {"start": round(original_start, 3), "end": round(original_end, 3)},
        "boundary_type": "segment_word_silence_boundary",
        "transcript_excerpt": text or evidence.get("transcript_excerpt", ""),
        "finished_thought_gate": "pass",
    }

    return {
        **raw,
        "index": index,
        "start": round(start, 3),
        "end": round(end, 3),
        "score": score.get("quality_score", raw.get("score")),
        "hook_score": score.get("hook_score"),
        "virality_score": score.get("virality_score"),
        "quality_score": score.get("quality_score"),
        "pacing_score": score.get("pacing_score"),
        "completeness_score": score.get("completeness_score"),
        "reject_reason": score.get("reject_reason"),
        "duration": duration,
        "estimated_clean_duration": clean_estimate["estimated_clean_duration"],
        "estimated_cleanup_removed_seconds": clean_estimate["estimated_removed_seconds"],
        "transcript_excerpt": text or raw.get("transcript_excerpt", ""),
        "semantic_boundary_evidence": evidence,
        "boundary_refinement": {
            "status": "refined",
            "original_start": round(original_start, 3),
            "original_end": round(original_end, 3),
            "delta_start": round(start - original_start, 3),
            "delta_end": round(end - original_end, 3),
            "duration_policy": "variable_30_60_sec",
            "clean_duration_policy": "expand raw boundaries when planned cleanup would make final clip too short",
            "estimated_clean_duration": clean_estimate["estimated_clean_duration"],
            "estimated_cleanup_removed_seconds": clean_estimate["estimated_removed_seconds"],
            "cleanup_duration_expansion": expansion_attempts,
            "cleanup_estimated_items": clean_estimate["estimated_items"],
            "cleanup_refinement": cleanup_refinement,
            "finished_thought_gate": "pass",
        },
    }, None


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: refine moment boundaries")
    parser.add_argument("moments", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--cleanup-plan", type=Path, default=None)
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--min", type=float, default=30, dest="min_sec")
    parser.add_argument("--max", type=float, default=60, dest="max_sec")
    add_decision_mode_args(parser)
    args = parser.parse_args()
    _artifact_path = args.output or (args.moments.parent / 'refined-moments.json')
    enforce_decision_mode(args, kind='refined-moments', path=_artifact_path)

    if not args.moments.is_file() or not args.transcript.is_file():
        print("[ERROR] moments or transcript not found", file=sys.stderr)
        sys.exit(1)

    moments = json.loads(args.moments.read_text(encoding="utf-8-sig"))
    transcript = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    cleanup = _load_json(args.cleanup_plan, {})
    scores = _score_by_index(_load_json(args.scores, {}))
    segments = segments_from_json(transcript)
    words = words_from_transcript_json(transcript)
    points = _candidate_boundaries(segments, words, cleanup)
    raw_clips = [c for c in moments.get("clips", []) if isinstance(c, dict)]
    refined: list[dict] = []
    rejected: list[dict] = []
    for i, raw in enumerate(raw_clips, 1):
        clip, rejected_clip = refine_clip(i, raw, segments, points, cleanup, scores.get(str(i), {}), args.min_sec, args.max_sec)
        if clip:
            refined.append(clip)
        if rejected_clip:
            rejected.append(rejected_clip)
    payload = {
        **moments,
        "clips": refined,
        "count": len(refined),
        "rejected_clips": rejected,
        "source_moments": str(args.moments.resolve()),
        "source_transcript": str(args.transcript.resolve()),
        "source_cleanup_plan": str(args.cleanup_plan.resolve()) if args.cleanup_plan and args.cleanup_plan.is_file() else None,
        "source_scores": str(args.scores.resolve()) if args.scores and args.scores.is_file() else None,
        "selection_contract": {
            **(moments.get("selection_contract") if isinstance(moments.get("selection_contract"), dict) else {}),
            "boundary_refiner": "segment_word_silence_snap",
            "fixed_duration": False,
            "finished_thought_gate": "required",
            "cleanup_policy": "silence and filler spans inform boundaries; review-only items stay visible for agent decision",
        },
    }
    out = args.output or (args.moments.parent / "refined-moments.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stamp_heuristic(payload, 'refine_boundaries'), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Refined moments: {out}")
    for i, clip in enumerate(refined, 1):
        print(f"   {i}: {clip['start']:.1f}-{clip['end']:.1f}s dur={clip['duration']:.1f}s score={clip.get('quality_score')}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
