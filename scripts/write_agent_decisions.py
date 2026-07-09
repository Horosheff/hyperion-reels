#!/usr/bin/env python3
"""VideoShorts — черновик агентных решений по клипам.

Local fallback использует этот файл только как эвристический draft. В Agent mode
субагент обязан прочитать, отредактировать и подтвердить решения вручную.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

from videoshorts_core import configure_stdio, segments_from_json

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


def _overlaps(item: dict, start: float, end: float) -> bool:
    try:
        s = float(item.get("start", -1))
        e = float(item.get("end", s))
    except Exception:
        return False
    return e >= start and s <= end


def _duration(items: list[dict]) -> float:
    total = 0.0
    for item in items:
        try:
            total += max(0.0, float(item.get("end", 0)) - float(item.get("start", 0)))
        except Exception:
            pass
    return round(total, 3)


def _clip_text(segments: list, start: float, end: float) -> str:
    return _clean(" ".join(s.text for s in segments if s.end > start and s.start < end), 900)


def _score_by_index(scores: dict) -> dict[str, dict]:
    return {
        str(item.get("index")): item
        for item in scores.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(scores, dict) else {}


def _confidence(score: dict, clip: dict, decision_source: str) -> float:
    quality = float(score.get("quality_score") or clip.get("quality_score") or clip.get("score") or 0)
    completeness = float(score.get("completeness_score") or clip.get("completeness_score") or 0)
    confidence = min(0.95, max(0.25, (quality * 0.006) + (completeness * 0.004)))
    if decision_source == "local_heuristic_draft":
        confidence = min(confidence, 0.62)
    if score.get("reject_reason") or clip.get("reject_reason"):
        confidence = min(confidence, 0.45)
    return round(confidence, 2)


def build_decisions(
    transcript_path: Path,
    moments_path: Path,
    cleanup_path: Path | None,
    scores_path: Path | None,
    refined_path: Path | None,
    *,
    selected_by_agent: bool,
    decision_source: str,
) -> dict:
    transcript = _load_json(transcript_path, {})
    moments = _load_json(moments_path, {"clips": []})
    refined = _load_json(refined_path, moments) if refined_path else moments
    cleanup = _load_json(cleanup_path, {})
    scores = _score_by_index(_load_json(scores_path, {"clips": []}))
    segments = segments_from_json(transcript)
    clips = [c for c in refined.get("clips", []) if isinstance(c, dict)]
    rejected_clips = [c for c in refined.get("rejected_clips", []) if isinstance(c, dict)]
    all_clips = [*clips, *rejected_clips]

    decisions: list[dict] = []
    for index, clip in enumerate(all_clips, 1):
        start = float(clip.get("start", 0))
        end = float(clip.get("end", start))
        score = scores.get(str(clip.get("index") or index), {})
        evidence = clip.get("semantic_boundary_evidence") if isinstance(clip.get("semantic_boundary_evidence"), dict) else {}
        cleanup_items = [
            item for item in cleanup.get("safe_removal_plan", [])
            if isinstance(item, dict) and _overlaps(item, start, end)
        ] if isinstance(cleanup, dict) else []
        review_items = [
            item for item in cleanup.get("review_only", [])
            if isinstance(item, dict) and _overlaps(item, start, end)
        ] if isinstance(cleanup, dict) else []
        silence_items = [item for item in cleanup_items if item.get("type") == "silence_gap"]
        filler_items = [item for item in cleanup_items if item.get("type") == "filler_word"]
        transcript_excerpt = _clean(
            clip.get("transcript_excerpt")
            or evidence.get("transcript_excerpt")
            or _clip_text(segments, start, end),
            900,
        )
        reject_reason = score.get("reject_reason") or clip.get("reject_reason")
        is_rejected = str(clip.get("status") or "").upper() == "REJECT" or bool(reject_reason)
        hook_score = score.get("hook_score") or clip.get("hook_score")
        virality_score = score.get("virality_score") or clip.get("virality_score")
        quality_score = score.get("quality_score") or clip.get("quality_score") or clip.get("score")

        decisions.append({
            "index": int(clip.get("index") or index),
            "selected_by_agent": bool(selected_by_agent and not is_rejected),
            "decision_source": decision_source,
            "agent_confirmation_required": decision_source == "local_heuristic_draft",
            "status": "REJECT" if is_rejected else "CANDIDATE",
            "why_this_moment": _clean(clip.get("editorial_rationale") or clip.get("reason") or "Черновой кандидат: агент должен подтвердить, что здесь есть самостоятельная микромысль.", 420),
            "hook_assessment": {
                "hook": _clean(clip.get("hook") or evidence.get("hook") or transcript_excerpt[:160], 220),
                "score": hook_score,
                "triggers": score.get("hook_triggers", []),
                "notes": "Агент должен подтвердить, что первые секунды цепляют без контекста полного видео.",
            },
            "viral_hypothesis": _clean(
                f"Черновая гипотеза: клип может сработать как короткий тезис/вывод; virality_score={virality_score}, quality_score={quality_score}.",
                360,
            ),
            "thought_start_evidence": _clean(evidence.get("why_start") or "Нет подтверждённого evidence начала мысли.", 360),
            "thought_end_evidence": _clean(
                evidence.get("why_end")
                or clip.get("payoff_ending")
                or evidence.get("payoff_ending")
                or "Нет подтверждённого evidence завершённой мысли.",
                420,
            ),
            "cleanup_applied": bool(cleanup_items),
            "silence_removed": {
                "count": len(silence_items),
                "seconds": _duration(silence_items),
                "items": silence_items[:12],
            },
            "fillers_removed": {
                "count": len(filler_items),
                "items": filler_items[:20],
            },
            "cleanup_review_items": review_items[:12],
            "glue_or_transition_notes": _clean(
                "Склейка допустима только если удаление паузы/filler не ломает интонацию и причинно-следственную связь.",
                260,
            ),
            "cut_instruction": {
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(max(0.0, end - start), 3),
                "notes": _clean(clip.get("boundary_refinement", {}).get("duration_policy") if isinstance(clip.get("boundary_refinement"), dict) else "Резать по refined boundaries.", 220),
            },
            "reject_if": [
                "нет законченной мысли или payoff",
                "начало требует контекста до клипа",
                "конец открывает следующий пункт",
                "после cleanup клип звучит как склейка",
                "hook выглядит скучным в первые 3 секунды",
            ],
            "reject_reason": reject_reason,
            "confidence": _confidence(score, clip, decision_source),
            "agent_notes": "Local fallback: это эвристический draft, не финальное LLM-решение. В Agent mode субагент обязан заменить/подтвердить этот блок и поставить selected_by_agent=true только после редакторской проверки.",
            "transcript_excerpt": transcript_excerpt,
        })

    return {
        "schema_version": 1,
        "mode": "agent_decision_contract",
        "decision_source": decision_source,
        "local_fallback_note": "local_heuristic_draft не является решением LLM-субагента; он нужен для тестов и UI.",
        "source_transcript": str(transcript_path.resolve()),
        "source_moments": str(moments_path.resolve()),
        "source_refined_moments": str(refined_path.resolve()) if refined_path and refined_path.is_file() else None,
        "source_cleanup_plan": str(cleanup_path.resolve()) if cleanup_path and cleanup_path.is_file() else None,
        "source_scores": str(scores_path.resolve()) if scores_path and scores_path.is_file() else None,
        "clips": decisions,
        "summary": {
            "total": len(decisions),
            "selected_by_agent": sum(1 for item in decisions if item.get("selected_by_agent")),
            "needs_agent_confirmation": sum(1 for item in decisions if item.get("agent_confirmation_required")),
            "with_cleanup_applied": sum(1 for item in decisions if item.get("cleanup_applied")),
            "rejected_or_risky": sum(1 for item in decisions if item.get("reject_reason")),
            "rejected": sum(1 for item in decisions if item.get("status") == "REJECT"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: build clip decision draft")
    parser.add_argument("transcript", type=Path)
    parser.add_argument("moments", type=Path)
    parser.add_argument("--cleanup-plan", type=Path, default=None)
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("--refined", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--agent-confirmed", action="store_true", help="Use only inside Cursor Agent mode after manual subagent review.")
    args = parser.parse_args()

    if not args.transcript.is_file() or not args.moments.is_file():
        print("[ERROR] transcript or moments not found", file=sys.stderr)
        sys.exit(1)

    decision_source = "subagent_confirmed" if args.agent_confirmed else "local_heuristic_draft"
    payload = build_decisions(
        args.transcript,
        args.moments,
        args.cleanup_plan,
        args.scores,
        args.refined,
        selected_by_agent=args.agent_confirmed,
        decision_source=decision_source,
    )
    out = args.output or (args.moments.parent / "clip-decisions.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Clip decisions: {out}")
    print(f"   source={decision_source} clips={payload['summary']['total']} needs_confirmation={payload['summary']['needs_agent_confirmation']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
