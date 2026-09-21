#!/usr/bin/env python3
"""VideoShorts — Jev (TypeSafe) scoring for clip-scores.json (text-only).

Pilot path for scorekeeper / editor clip-scores. Does not cut video or run Whisper.

Enable:
  VIDEOSHORTS_JEV_SCORES=1
  TYPESAFE_API_KEY=...

Example:
  cd scripts
  python3 jev_score_clips.py \\
    ../videoshorts-memory/moments/demo-moments.json \\
    ../videoshorts-memory/transcripts/demo/transcript.json \\
    -o ../videoshorts-memory/moments/clip-scores.json \\
    --min 30 --max 60
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from agent_artifact_guard import stamp_jev
from typesafe_client import TypeSafeApiError, TypeSafeClient, load_typesafe_api_key
from videoshorts_core import clips_from_json, configure_stdio, segments_from_json

configure_stdio()

# Five ordered levels → raw Score in [0, 4]; map to 0–100 via /4 * 100.
SCORE_LEVELS = 4

HOOK_CRITERIA = [
    "нет хука: слабое или контекстное начало без обещания",
    "слабый интерес: тема есть, но первые секунды не цепляют",
    "средний хук: понятно о чём ролик, интерес умеренный",
    "сильный хук: ясное обещание/провокация, хочется смотреть дальше",
    "исключительный scroll-stop хук: сразу цепляет и задаёт stakes",
]

VIRALITY_CRITERIA = [
    "нулевая шарибельность: скучно, нет spare/comment повода",
    "слабая: узкая польза, почти никто не перешлёт",
    "умеренная: есть полезный тезис, но без сильного триггера",
    "высокая: хочется сохранить или переслать коллеге",
    "вирусный потенциал: сильный insight + comment/share триггер",
]

QUALITY_CRITERIA = [
    "плохой шорт: путаница, шум, нет ценности",
    "ниже среднего: ценность слабая или подача рваная",
    "средний: смотрибельно, но без яркого преимущества",
    "хороший: ясная мысль, полезная подача",
    "отличный шорт по тексту: плотно, понятно, сильная ценность",
]

PACING_CRITERIA = [
    "длительность сильно мимо brief (слишком коротко/длинно для мысли)",
    "слабый pacing: заметно жмёт или тянет относительно min/max",
    "приемлемый pacing: в окне brief с оговорками",
    "хороший pacing: длительность хорошо ложится на мысль",
    "идеальный pacing: плотно в brief, без воды и обрыва",
]

COMPLETENESS_CRITERIA = [
    "обрубок: нет самостоятельной мысли и payoff",
    "неполное: старт или финал висят, payoff слабый",
    "почти целое: мысль читается, но payoff размыт",
    "завершённая мысль с понятным payoff",
    "идеально standalone: setup→натяжение→payoff, можно смотреть отдельно",
]

REJECT_NOUL_INSTRUCTIONS = (
    "Should this clip be REJECTED as a short-form video based only on the transcript text? "
    "Yes means reject (incomplete thought, no payoff, boring, contextless, weak hook without rescue). "
    "No means keep/pass for further editorial review."
)


Opener = Callable[..., Any]


def _clean(text: str, limit: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if limit and len(value) > limit:
        return value[: max(0, limit - 3)].rstrip(" ,.;:") + "..."
    return value


def _clip_text(segments: list, start: float, end: float) -> str:
    return _clean(" ".join(s.text for s in segments if s.end > start and s.start < end), 1200)


def score_to_100(raw: float, *, max_level: int = SCORE_LEVELS) -> int:
    """Map TypeSafe weighted score (0..max_level) to integer 0–100."""
    if max_level <= 0:
        return 0
    return max(0, min(100, int(round(float(raw) / max_level * 100))))


def _answer_score(answers: dict, key: str) -> float:
    item = answers.get(key) or {}
    if not isinstance(item, dict):
        return 0.0
    try:
        return float(item.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _answer_noul(answers: dict, key: str) -> float:
    item = answers.get(key) or {}
    if not isinstance(item, dict):
        return 0.0
    try:
        return float(item.get("noul") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_clip_questions() -> dict[str, dict]:
    """Atomic Score + optional Noul questions for one clip (composite scoring)."""
    return {
        "hook": {
            "type": "score",
            "instructions": (
                "Rate hook strength for a short-form vertical video using ONLY the transcript text "
                "(Russian or English OK). Focus on the opening / hook field and first lines."
            ),
            "criteria": HOOK_CRITERIA,
        },
        "virality": {
            "type": "score",
            "instructions": (
                "Rate shareability / virality potential from the transcript alone: "
                "would someone save or share this insight?"
            ),
            "criteria": VIRALITY_CRITERIA,
        },
        "quality": {
            "type": "score",
            "instructions": (
                "Rate overall short-form quality from text: clarity, value density, "
                "watchability of the thought (not video production)."
            ),
            "criteria": QUALITY_CRITERIA,
        },
        "pacing": {
            "type": "score",
            "instructions": (
                "Rate pacing fit vs brief duration window. Use `duration_sec`, `min_sec`, `max_sec` "
                "in state: does length match a finished micro-thought without drag or rush?"
            ),
            "criteria": PACING_CRITERIA,
        },
        "completeness": {
            "type": "score",
            "instructions": (
                "Rate completeness: standalone finished thought with clear payoff_ending. "
                "Penalize clipped endings, dangling intros, missing conclusion."
            ),
            "criteria": COMPLETENESS_CRITERIA,
        },
        "should_reject": {
            "type": "noul",
            "instructions": REJECT_NOUL_INSTRUCTIONS,
            "criteria": {
                "true": "Reject: incomplete, boring, contextless, or no payoff",
                "false": "Keep for editorial review",
            },
        },
    }


def build_clip_state(
    *,
    index: int,
    start: float,
    end: float,
    duration: float,
    min_sec: float,
    max_sec: float,
    text: str,
    hook_text: str,
    payoff: str,
    why_start: str,
    why_end: str,
) -> dict:
    return {
        "clip_index": index,
        "start_sec": round(start, 3),
        "end_sec": round(end, 3),
        "duration_sec": round(duration, 3),
        "min_sec": min_sec,
        "max_sec": max_sec,
        "hook": hook_text,
        "payoff_ending": payoff,
        "transcript_excerpt": text,
        "why_start": why_start,
        "why_end": why_end,
    }


def map_jev_answers_to_clip(
    *,
    index: int,
    start: float,
    end: float,
    duration: float,
    min_sec: float,
    max_sec: float,
    answers: dict,
    model: str | None = None,
) -> dict:
    """Convert TypeSafe answers into clip-scores schema fields."""
    hook_score = score_to_100(_answer_score(answers, "hook"))
    virality_score = score_to_100(_answer_score(answers, "virality"))
    quality_score = score_to_100(_answer_score(answers, "quality"))
    pacing_score = score_to_100(_answer_score(answers, "pacing"))
    completeness_score = score_to_100(_answer_score(answers, "completeness"))
    reject_prob = _answer_noul(answers, "should_reject")

    # Soft duration nudge in code (brief is authoritative).
    if duration < min_sec:
        pacing_score = min(pacing_score, 35)
    elif duration > max_sec:
        pacing_score = min(pacing_score, 40)

    reject_reasons: list[str] = []
    if duration < min_sec:
        reject_reasons.append("too_short")
    if duration > max_sec:
        reject_reasons.append("too_long")
    if hook_score < 28 and completeness_score < 55:
        reject_reasons.append("weak_hook")
    if hook_score < 35 and virality_score < 40 and quality_score < 45:
        reject_reasons.append("boring_or_low_viral_potential")
    if completeness_score < 50:
        reject_reasons.append("incomplete_thought")
    if completeness_score < 45:
        reject_reasons.append("clipped_ending")
    if quality_score < 40:
        reject_reasons.append("low_quality")
    if reject_prob >= 0.55:
        if "boring_or_low_viral_potential" not in reject_reasons and quality_score < 55:
            reject_reasons.append("boring_or_low_viral_potential")
        if completeness_score < 60 and "incomplete_thought" not in reject_reasons:
            reject_reasons.append("incomplete_thought")
        if not reject_reasons:
            reject_reasons.append("jev_reject")

    # Validator: quality < 40 requires reject_reason
    if quality_score < 40 and not reject_reasons:
        reject_reasons.append("low_quality")

    seen: set[str] = set()
    uniq: list[str] = []
    for reason in reject_reasons:
        if reason not in seen:
            seen.add(reason)
            uniq.append(reason)

    status = "REJECT" if uniq else "PASS"
    return {
        "index": index,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(duration, 3),
        "hook_score": hook_score,
        "virality_score": virality_score,
        "quality_score": quality_score,
        "pacing_score": pacing_score,
        "completeness_score": completeness_score,
        "hook_assessment": "сильный" if hook_score >= 55 else "средний" if hook_score >= 35 else "слабый",
        "viral_hypothesis": (
            "Jev: понятный hook и самостоятельная микромысль."
            if status == "PASS"
            else "Jev: слабая вирусная гипотеза или incompleteness — нужна редактура/reject."
        ),
        "reject_reason": ", ".join(uniq) if uniq else None,
        "status": status,
        "jev": {
            "model": model,
            "reject_probability": round(reject_prob, 4),
            "raw_scores": {
                "hook": _answer_score(answers, "hook"),
                "virality": _answer_score(answers, "virality"),
                "quality": _answer_score(answers, "quality"),
                "pacing": _answer_score(answers, "pacing"),
                "completeness": _answer_score(answers, "completeness"),
            },
        },
    }


def score_clip_with_jev(
    index: int,
    clip,
    segments: list,
    min_sec: float,
    max_sec: float,
    client: TypeSafeClient,
) -> dict:
    start = float(clip.start)
    end = float(clip.end)
    duration = max(0.0, end - start)
    evidence = clip.semantic_boundary_evidence if isinstance(clip.semantic_boundary_evidence, dict) else {}
    text = _clean(
        clip.transcript_excerpt or evidence.get("transcript_excerpt") or _clip_text(segments, start, end),
        1200,
    )
    hook_text = _clean(clip.hook or evidence.get("hook") or text[:160], 180)
    payoff = _clean(getattr(clip, "payoff_ending", None) or evidence.get("payoff_ending") or "", 240)
    why_start = _clean(evidence.get("why_start") or "", 240)
    why_end = _clean(evidence.get("why_end") or "", 240)

    state = build_clip_state(
        index=index,
        start=start,
        end=end,
        duration=duration,
        min_sec=min_sec,
        max_sec=max_sec,
        text=text,
        hook_text=hook_text,
        payoff=payoff,
        why_start=why_start,
        why_end=why_end,
    )
    response = client.system_one(state, build_clip_questions())
    answers = response.get("answers") or {}
    if not isinstance(answers, dict):
        raise TypeSafeApiError(f"clip {index}: answers missing")
    return map_jev_answers_to_clip(
        index=index,
        start=start,
        end=end,
        duration=duration,
        min_sec=min_sec,
        max_sec=max_sec,
        answers=answers,
        model=str(response.get("model") or ""),
    )


def build_scores_payload(
    *,
    moments_path: Path,
    transcript_path: Path,
    clips_scores: list[dict],
    authored_by: str = "videoshorts-editor",
) -> dict:
    payload = {
        "schema_version": 1,
        "source_moments": str(moments_path.resolve()),
        "source_transcript": str(transcript_path.resolve()),
        "clips": clips_scores,
        "summary": {
            "total": len(clips_scores),
            "passed": sum(1 for item in clips_scores if item.get("status") == "PASS"),
            "rejected": sum(1 for item in clips_scores if item.get("status") == "REJECT"),
            "average_quality": (
                round(sum(float(item.get("quality_score") or 0) for item in clips_scores) / len(clips_scores), 2)
                if clips_scores
                else 0
            ),
        },
    }
    return stamp_jev(payload, authored_by=authored_by)


def score_moments_file(
    moments_path: Path,
    transcript_path: Path,
    *,
    min_sec: float = 30.0,
    max_sec: float = 60.0,
    api_key: str | None = None,
    opener: Opener | None = None,
    authored_by: str = "videoshorts-editor",
) -> dict:
    if not moments_path.is_file() or not transcript_path.is_file():
        raise FileNotFoundError("moments or transcript not found")

    key = (api_key or load_typesafe_api_key() or "").strip()
    if not key:
        raise TypeSafeApiError("TYPESAFE_API_KEY не задан (env или videoshorts.local.env)")

    moments_data = json.loads(moments_path.read_text(encoding="utf-8-sig"))
    transcript_data = json.loads(transcript_path.read_text(encoding="utf-8-sig"))
    clips = clips_from_json(moments_data)
    segments = segments_from_json(transcript_data)

    client_kwargs: dict[str, Any] = {}
    if opener is not None:
        client_kwargs["opener"] = opener
    client = TypeSafeClient(key, **client_kwargs)

    scores = [
        score_clip_with_jev(i, clip, segments, min_sec, max_sec, client)
        for i, clip in enumerate(clips, 1)
    ]
    return build_scores_payload(
        moments_path=moments_path,
        transcript_path=transcript_path,
        clips_scores=scores,
        authored_by=authored_by,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VideoShorts: Jev (TypeSafe) clip scores")
    parser.add_argument("moments", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--min", type=float, default=30, dest="min_sec")
    parser.add_argument("--max", type=float, default=60, dest="max_sec")
    parser.add_argument(
        "--authored-by",
        default="videoshorts-editor",
        help="authored_by stamp (default videoshorts-editor for slim editor gate)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate existing clip-scores artifact and exit (no API calls)",
    )
    args = parser.parse_args(argv)

    out = args.output or (args.moments.parent / "clip-scores.json")
    if args.validate:
        from validate_agent_artifacts import validate_kind

        ok, errors = validate_kind("clip-scores", out)
        if ok:
            print(f"✅ validate clip-scores: {out}")
            return 0
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 2

    try:
        payload = score_moments_file(
            args.moments,
            args.transcript,
            min_sec=args.min_sec,
            max_sec=args.max_sec,
            authored_by=args.authored_by,
        )
    except (TypeSafeApiError, FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Jev clip scores: {out}")
    print(f"   pass={payload['summary']['passed']} reject={payload['summary']['rejected']}")
    print(f"   scoring_engine={payload.get('scoring_engine')} decision_source={payload.get('decision_source')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
