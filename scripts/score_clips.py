#!/usr/bin/env python3
"""VideoShorts — оценка выбранных моментов перед уточнением границ."""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

from videoshorts_core import analyze_hook_quality_2026, clips_from_json, configure_stdio, segments_from_json
from agent_artifact_guard import add_decision_mode_args, enforce_decision_mode, stamp_heuristic

configure_stdio()


def _clean(text: str, limit: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if limit and len(value) > limit:
        return value[: max(0, limit - 3)].rstrip(" ,.;:") + "..."
    return value


def _clip_text(segments: list, start: float, end: float) -> str:
    return _clean(" ".join(s.text for s in segments if s.end > start and s.start < end), 1200)


def _looks_incomplete_ending(text: str) -> bool:
    clean = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not clean:
        return True
    tail_sentences = [s.strip(" \t\r\n.,!?…:;—-") for s in re.split(r"(?<=[.!?…])\s+", clean) if s.strip()]
    tail = tail_sentences[-1] if tail_sentences else clean[-120:]
    dangling_exact = {
        "первое",
        "второе",
        "третье",
        "следующее",
        "дальше",
        "итак",
        "так",
        "сейчас",
        "сейчас объясню",
        "сейчас покажу",
        "я объясню",
        "объясню",
        "начнем",
        "продолжим",
        "one",
        "two",
        "next",
        "first",
        "second",
        "let me explain",
    }
    if tail in dangling_exact:
        return True
    dangling_prefixes = (
        "первое ",
        "второе ",
        "третье ",
        "следующий пункт",
        "следующая ",
        "сейчас объясню",
        "сейчас покажу",
        "давайте посмотрим",
        "я объясню",
        "let me explain",
        "here is why",
        "next ",
    )
    return tail.startswith(dangling_prefixes)


def _has_payoff_signal(text: str) -> bool:
    from review_utils import has_payoff
    return has_payoff(text)


def _looks_like_contextless_start(text: str) -> bool:
    clean = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not clean:
        return True
    first_words = " ".join(clean.split()[:5])
    weak_prefixes = (
        "и вот",
        "так вот",
        "ну вот",
        "вот это",
        "то есть",
        "поэтому если",
        "потому что",
        "а дальше",
        "и дальше",
        "and then",
        "so if",
        "because",
    )
    return first_words.startswith(weak_prefixes)


def _load_json(path: Path | None, default):
    if not path or not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _cleanup_density(cleanup: dict, start: float, end: float) -> tuple[int, int]:
    safe = 0
    review = 0
    for item in cleanup.get("safe_removal_plan", []) if isinstance(cleanup, dict) else []:
        s = float(item.get("start", -1))
        e = float(item.get("end", s))
        if e >= start and s <= end:
            safe += 1
    for item in cleanup.get("review_only", []) if isinstance(cleanup, dict) else []:
        s = float(item.get("start", -1))
        e = float(item.get("end", s))
        if e >= start and s <= end:
            review += 1
    return safe, review


def score_clip(index: int, clip, segments: list, cleanup: dict, min_sec: float, max_sec: float) -> dict:
    start = float(clip.start)
    end = float(clip.end)
    duration = max(0.0, end - start)
    evidence = clip.semantic_boundary_evidence if isinstance(clip.semantic_boundary_evidence, dict) else {}
    text = _clean(clip.transcript_excerpt or evidence.get("transcript_excerpt") or _clip_text(segments, start, end), 1200)
    hook_text = _clean(clip.hook or evidence.get("hook") or text[:160], 180)
    # Prefer real first ~3s window for boring/live_proof gates (INC-0912)
    first3s = _clip_text(segments, start, min(end, start + 3.0)) or " ".join(text.split()[:18])
    hook = analyze_hook_quality_2026(text, first3s or hook_text)
    # Also score declared hook phrase — take the stronger signal for webinar openers
    hook_phrase = analyze_hook_quality_2026(hook_text, hook_text)
    if int(hook_phrase.get("score", 0)) > int(hook.get("score", 0)):
        # Keep first3s boring penalty if present
        if "boring_first_3s" in (hook.get("triggers") or []) and "boring_first_3s" not in (hook_phrase.get("triggers") or []):
            merged_score = max(0, int(hook_phrase.get("score", 0)) - 35)
            hook = {
                **hook_phrase,
                "score": merged_score,
                "triggers": list(set((hook_phrase.get("triggers") or []) + ["boring_first_3s"])),
            }
        else:
            hook = hook_phrase
    safe_cleanup, review_cleanup = _cleanup_density(cleanup, start, end)

    hook_score = int(hook.get("score", 0))
    virality_score = min(100, int(hook_score * 0.62 + min(38, len(text.split()) / 3)))
    duration_mid = (min_sec + max_sec) / 2
    pacing_score = max(0, min(100, int(100 - abs(duration - duration_mid) * 2.2 - safe_cleanup * 2.5)))
    completeness_score = 58
    if evidence.get("why_start"):
        completeness_score += 8
    if evidence.get("why_end"):
        completeness_score += 8
    if re.search(r"[.!?…]\s*$", text):
        completeness_score += 6
    if _has_payoff_signal(text):
        completeness_score += 10
    if not evidence.get("payoff_ending") and not clip.payoff_ending:
        completeness_score -= 12
    if _looks_incomplete_ending(text):
        completeness_score -= 32
    if _looks_like_contextless_start(text) and not evidence.get("why_start"):
        completeness_score -= 12
    quality_score = max(0, min(100, int((hook_score + virality_score + pacing_score + completeness_score) / 4 - review_cleanup * 1.5)))

    reject_reasons: list[str] = []
    if duration < min_sec:
        reject_reasons.append("too_short")
    if duration > max_sec:
        reject_reasons.append("too_long")
    # Soft gate: regex hook alone must not mass-reject finished RU Q&A/mythbust
    # (see pitfalls + analyze_hook_quality_2026 webinar_qa_opener). Hard reject only
    # when hook is weak AND completeness/context also fail.
    if hook_score < 22:
        reject_reasons.append("weak_hook")
    elif hook_score < 35 and completeness_score < 62 and _looks_like_contextless_start(text):
        reject_reasons.append("weak_hook")
    if "boring_first_3s" in (hook.get("triggers") or []) and hook_score < 40:
        reject_reasons.append("weak_hook_first_3s")
        reject_reasons.append("boring_or_low_viral_potential")
    elif hook_score < 28 and virality_score < 34 and quality_score < 45:
        reject_reasons.append("boring_or_low_viral_potential")
    if _looks_like_contextless_start(text) and not evidence.get("why_start"):
        reject_reasons.append("contextless_start")
    if completeness_score < 68:
        reject_reasons.append("incomplete_thought")
    if _looks_incomplete_ending(text) and not (evidence.get("why_end") or clip.payoff_ending):
        reject_reasons.append("clipped_ending")
    if review_cleanup >= 5:
        reject_reasons.append("too_many_review_cleanup_candidates")

    # Dedupe reject reasons while preserving order
    seen: set[str] = set()
    uniq_reasons: list[str] = []
    for r in reject_reasons:
        if r not in seen:
            seen.add(r)
            uniq_reasons.append(r)

    return {
        "index": index,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(duration, 3),
        "hook_score": hook_score,
        "virality_score": virality_score,
        "quality_score": quality_score,
        "pacing_score": pacing_score,
        "completeness_score": max(0, min(100, completeness_score)),
        "cleanup_candidates": safe_cleanup + review_cleanup,
        "cleanup_safe_candidates": safe_cleanup,
        "cleanup_review_candidates": review_cleanup,
        "hook_triggers": hook.get("triggers", []),
        "hook_assessment": "сильный" if hook_score >= 55 else "средний" if hook_score >= 35 else "слабый",
        "viral_hypothesis": (
            "Есть понятный hook и самостоятельная микромысль."
            if hook_score >= 40 and virality_score >= 45 and completeness_score >= 68
            else "Слабая вирусная гипотеза: агент должен заменить или отклонить клип."
        ),
        "reject_reason": ", ".join(uniq_reasons) if uniq_reasons else None,
        "status": "REJECT" if uniq_reasons else "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: score selected clips")
    parser.add_argument("moments", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--cleanup-plan", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--min", type=float, default=30, dest="min_sec")
    parser.add_argument("--max", type=float, default=60, dest="max_sec")
    add_decision_mode_args(parser)
    args = parser.parse_args()
    _artifact_path = args.output or (args.moments.parent / 'clip-scores.json')
    enforce_decision_mode(args, kind='clip-scores', path=_artifact_path)

    if not args.moments.is_file() or not args.transcript.is_file():
        print("[ERROR] moments or transcript not found", file=sys.stderr)
        sys.exit(1)

    moments_data = json.loads(args.moments.read_text(encoding="utf-8-sig"))
    transcript_data = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    cleanup = _load_json(args.cleanup_plan, {})
    clips = clips_from_json(moments_data)
    segments = segments_from_json(transcript_data)
    scores = [score_clip(i, clip, segments, cleanup, args.min_sec, args.max_sec) for i, clip in enumerate(clips, 1)]
    payload = {
        "schema_version": 1,
        "source_moments": str(args.moments.resolve()),
        "source_transcript": str(args.transcript.resolve()),
        "source_cleanup_plan": str(args.cleanup_plan.resolve()) if args.cleanup_plan and args.cleanup_plan.is_file() else None,
        "clips": scores,
        "summary": {
            "total": len(scores),
            "passed": sum(1 for item in scores if item["status"] == "PASS"),
            "rejected": sum(1 for item in scores if item["status"] == "REJECT"),
            "average_quality": round(sum(item["quality_score"] for item in scores) / len(scores), 2) if scores else 0,
        },
    }
    out = args.output or (args.moments.parent / "clip-scores.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stamp_heuristic(payload, 'score_clips'), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Clip scores: {out}")
    print(f"   pass={payload['summary']['passed']} reject={payload['summary']['rejected']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
