#!/usr/bin/env python3
"""VideoShorts — local heuristic draft for candidate-moments.json."""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from review_utils import clean, clip_text, has_payoff, write_json
from videoshorts_core import analyze_hook_quality_2026, configure_stdio, segments_from_json
from agent_artifact_guard import add_decision_mode_args, enforce_decision_mode, stamp_heuristic

configure_stdio()


def hook_type(triggers: list[str], text: str) -> str:
    if "question_hook" in triggers or "?" in text[:160]:
        return "question_hook"
    if "curiosity_gap" in triggers:
        return "curiosity_gap"
    if "value_promise" in triggers:
        return "value_promise"
    if "pattern_interrupt" in triggers:
        return "pattern_interrupt"
    if "number_pattern" in triggers:
        return "number_pattern"
    return "insight_or_story"


def audience_pain(text: str) -> str:
    low = text.lower()
    if any(w in low for w in ("деньги", "продаж", "клиент", "лид", "бизнес")):
        return "как получить клиентов/деньги быстрее и без лишних действий"
    if any(w in low for w in ("ошиб", "нельзя", "проблем", "слом", "плохо")):
        return "как избежать ошибки, которая съедает результат"
    if any(w in low for w in ("нейросет", "ai", "gpt", "cursor", "автоматизац")):
        return "как применить AI/автоматизацию практически, а не ради хайпа"
    return "как получить понятный короткий вывод без просмотра полного видео"


def possible_title(text: str, htype: str) -> str:
    head = clean(text, 96)
    if htype == "question_hook":
        return head if head.endswith("?") else f"Почему это работает: {head}"
    if htype == "curiosity_gap":
        return f"Вот почему: {head}"
    if htype == "value_promise":
        return f"Как сделать: {head}"
    return head


def build_candidates(transcript: dict, min_sec: float, max_sec: float, target: int) -> dict:
    segments = segments_from_json(transcript)
    candidates: list[dict] = []
    if not segments:
        return {"schema_version": 1, "candidates": [], "summary": {"total": 0}}

    # Variable windows: short / mid / long buckets from brief range (not fixed midpoint).
    span = max(0.0, max_sec - min_sec)
    mid = min_sec + span * 0.5
    short_w = max(min_sec, min(max_sec, min_sec + span * 0.25))
    mid_w = max(min_sec, min(max_sec, mid))
    long_w = max(min_sec, min(max_sec, max_sec - min(12.0, span * 0.15)))
    windows = [short_w, mid_w, long_w]
    if span >= 40:
        # Extra long near ceiling when UI asks e.g. 30–90
        windows.append(max(min_sec, min(max_sec, max_sec - 5.0)))

    step = max(6.0, mid_w / 3.5)
    t = max(0.0, segments[0].start)
    raw: list[dict] = []
    window_i = 0
    while t < segments[-1].end - min_sec:
        window = windows[window_i % len(windows)]
        window_i += 1
        start = t
        end = min(start + window, segments[-1].end)
        if end - start >= min_sec:
            text = clip_text(segments, start, end, 1400)
            if len(text.split()) >= 18:
                hook = analyze_hook_quality_2026(text, clean(text, 180))
                triggers = list(hook.get("triggers") or [])
                payoff = has_payoff(text)
                score = int(hook.get("score") or 0) + (10 if payoff else 0) + min(20, len(text.split()) // 10)
                raw.append({
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "duration": round(end - start, 3),
                    "score": score,
                    "transcript_excerpt": clean(text, 900),
                    "hook_type": hook_type(triggers, text),
                    "hook_triggers": triggers,
                    "has_payoff_signal": payoff,
                })
        t += step

    raw.sort(key=lambda item: item["score"], reverse=True)
    selected: list[dict] = []
    used: list[tuple[float, float]] = []
    for item in raw:
        overlaps = any(item["start"] < e and item["end"] > s for s, e in used)
        if overlaps and len(selected) >= min(30, target):
            continue
        selected.append(item)
        used.append((item["start"], item["end"]))
        if len(selected) >= target:
            break
    selected.sort(key=lambda item: item["start"])

    for index, item in enumerate(selected, 1):
        text = item["transcript_excerpt"]
        item.update({
            "index": index,
            "candidate_id": f"cand_{index:03d}",
            "candidate_reason": clean(
                f"{item['hook_type']} с hook_score={item['score']}; "
                f"{'есть сигнал payoff' if item['has_payoff_signal'] else 'payoff нужно проверить редактором'}.",
                280,
            ),
            "audience_pain": audience_pain(text),
            "possible_title": possible_title(text, item["hook_type"]),
            "why_not_cut_yet": (
                "Это только local heuristic draft: редактор, вирусолог и драматург должны подтвердить самостоятельность мысли, контекст и финал."
            ),
        })

    durations = [float(item.get("duration") or 0) for item in selected]
    return {
        "schema_version": 1,
        "artifact": "candidate-moments",
        "decision_source": "local_heuristic_draft",
        "local_fallback_note": "Скрипт создаёт список кандидатов для диагностики; в Agent mode финальное решение принимает videoshorts-candidate-generator.",
        "selection_contract": {
            "target_candidates": "30-80",
            "min_sec": min_sec,
            "max_sec": max_sec,
            "required_fields": ["candidate_reason", "hook_type", "audience_pain", "possible_title", "why_not_cut_yet"],
            "scripts_are_tools_only": True,
            "duration_policy": "variable_short_mid_long_from_brief",
        },
        "candidates": selected,
        "summary": {
            "total": len(selected),
            "with_payoff_signal": sum(1 for item in selected if item.get("has_payoff_signal")),
            "average_score": round(sum(item.get("score", 0) for item in selected) / len(selected), 2) if selected else 0,
            "duration_min": round(min(durations), 3) if durations else 0,
            "duration_max": round(max(durations), 3) if durations else 0,
            "duration_avg": round(sum(durations) / len(durations), 3) if durations else 0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: generate 30-80 local candidate drafts")
    parser.add_argument("transcript", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--min", type=float, default=30, dest="min_sec")
    parser.add_argument("--max", type=float, default=60, dest="max_sec")
    parser.add_argument("--target", type=int, default=60)
    add_decision_mode_args(parser)
    args = parser.parse_args()
    _artifact_path = args.output or (args.transcript.resolve().parents[2] / 'moments' / 'candidate-moments.json')
    enforce_decision_mode(args, kind='candidates', path=_artifact_path)
    if not args.transcript.is_file():
        print(f"[ERROR] Transcript not found: {args.transcript}", file=sys.stderr)
        sys.exit(1)
    import json

    transcript = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    target = max(30, min(80, args.target))
    payload = build_candidates(transcript, args.min_sec, args.max_sec, target)
    out = args.output or (args.transcript.parents[1] / "moments" / "candidate-moments.json")
    write_json(out, stamp_heuristic(payload, 'generate_candidates'))
    print(f"✅ Candidate moments: {out} ({payload['summary']['total']})")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
