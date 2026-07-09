#!/usr/bin/env python3
"""VideoShorts — безопасный план чистки транскрипта.

Скрипт ничего не удаляет из transcript.json. Он строит машинно-читаемые планы:
silence gaps, filler words и осторожные эвристики повторов/false starts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

from videoshorts_core import configure_stdio, segments_from_json, words_from_transcript_json

configure_stdio()

FILLER_RE = re.compile(
    r"^(?:э+|э+м+|эм+|мм+|м+|а+а+|ну+|типа|короче|как\s+бы|значит|в общем|"
    r"собственно|это|вот|то есть|um+|uh+|erm+|hmm+|like|you know|so|basically)$",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+(?:[-'][A-Za-zА-Яа-яЁё0-9]+)?")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower().replace("ё", "е") for m in TOKEN_RE.finditer(text or "")]


def _word_text(word: dict) -> str:
    return str(word.get("word") or word.get("text") or "").strip(" ,.!?;:…—-").lower().replace("ё", "е")


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def detect_silence_gaps(segments: list, words: list[dict], threshold: float) -> list[dict]:
    gaps: list[dict] = []
    timeline: list[tuple[float, float, str]] = []
    if words:
        for word in words:
            start = _float(word.get("start"))
            end = _float(word.get("end"), start)
            if end >= start:
                timeline.append((start, end, _word_text(word)))
    else:
        for seg in segments:
            timeline.append((float(seg.start), float(seg.end), _clean(seg.text)[:80]))

    timeline.sort(key=lambda item: item[0])
    for prev, curr in zip(timeline, timeline[1:]):
        gap = curr[0] - prev[1]
        if gap >= threshold:
            gaps.append({
                "type": "silence_gap",
                "start": round(prev[1], 3),
                "end": round(curr[0], 3),
                "duration": round(gap, 3),
                "previous": prev[2],
                "next": curr[2],
                "action": "candidate_trim_gap",
                "safe": True,
            })
    return gaps


def detect_fillers(segments: list, words: list[dict]) -> list[dict]:
    findings: list[dict] = []
    if words:
        for i, word in enumerate(words, 1):
            text = _word_text(word)
            if text and FILLER_RE.match(text):
                findings.append({
                    "type": "filler_word",
                    "index": i,
                    "text": text,
                    "start": round(_float(word.get("start")), 3),
                    "end": round(_float(word.get("end"), word.get("start")), 3),
                    "action": "candidate_remove_word",
                    "safe": True,
                })
        return findings

    for si, seg in enumerate(segments, 1):
        for token in _tokens(seg.text):
            if FILLER_RE.match(token):
                findings.append({
                    "type": "filler_word",
                    "segment_index": si,
                    "text": token,
                    "start": round(float(seg.start), 3),
                    "end": round(float(seg.end), 3),
                    "action": "review_segment_for_filler",
                    "safe": False,
                })
    return findings


def detect_repeats_and_false_starts(segments: list) -> list[dict]:
    findings: list[dict] = []
    for i, seg in enumerate(segments, 1):
        tokens = _tokens(seg.text)
        if not tokens:
            continue
        repeated = []
        for a, b in zip(tokens, tokens[1:]):
            if a == b and len(a) > 2:
                repeated.append(a)
        if repeated:
            findings.append({
                "type": "repeated_word",
                "segment_index": i,
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "tokens": sorted(set(repeated)),
                "text": _clean(seg.text)[:220],
                "action": "review_repeat",
                "safe": False,
            })

        if len(tokens) >= 8:
            head = tokens[:3]
            for offset in range(3, min(9, len(tokens) - 2)):
                if tokens[offset:offset + 3] == head:
                    findings.append({
                        "type": "false_start",
                        "segment_index": i,
                        "start": round(float(seg.start), 3),
                        "end": round(float(seg.end), 3),
                        "phrase": " ".join(head),
                        "text": _clean(seg.text)[:220],
                        "action": "review_false_start",
                        "safe": False,
                    })
                    break

    for prev, curr in zip(segments, segments[1:]):
        prev_tail = _tokens(prev.text)[-4:]
        curr_head = _tokens(curr.text)[:4]
        overlap = 0
        for n in (4, 3, 2):
            if len(prev_tail) >= n and len(curr_head) >= n and prev_tail[-n:] == curr_head[:n]:
                overlap = n
                break
        if overlap:
            findings.append({
                "type": "cross_segment_repeat",
                "start": round(float(curr.start), 3),
                "end": round(float(curr.end), 3),
                "phrase": " ".join(curr_head[:overlap]),
                "action": "review_boundary_repeat",
                "safe": False,
            })
    return findings


def build_plan(transcript_path: Path, gap_threshold: float) -> tuple[dict, dict]:
    data = json.loads(transcript_path.read_text(encoding="utf-8-sig"))
    segments = segments_from_json(data)
    words = words_from_transcript_json(data)
    silence = detect_silence_gaps(segments, words, gap_threshold)
    fillers = detect_fillers(segments, words)
    repeats = detect_repeats_and_false_starts(segments)
    safe_removals = [item for item in [*silence, *fillers] if item.get("safe")]
    review_only = [item for item in [*fillers, *repeats] if not item.get("safe")]

    cleanup = {
        "schema_version": 1,
        "mode": "plan_only",
        "source_transcript": str(transcript_path.resolve()),
        "summary": {
            "segments": len(segments),
            "words": len(words),
            "silence_gaps": len(silence),
            "filler_candidates": len(fillers),
            "repeat_or_false_start_candidates": len(repeats),
            "safe_plan_items": len(safe_removals),
            "review_only_items": len(review_only),
        },
        "silence_gaps": silence,
        "filler_words": fillers,
        "repeat_false_start_candidates": repeats,
        "safe_removal_plan": safe_removals,
        "review_only": review_only,
        "notes": [
            "План не изменяет transcript.json.",
            "safe=true означает кандидат на аккуратный trim/removal, но финальное решение принимает агент.",
            "Повторы и false starts по умолчанию review-only.",
        ],
    }
    filler_plan = {
        "schema_version": 1,
        "mode": "plan_only",
        "source_transcript": str(transcript_path.resolve()),
        "items": fillers,
        "safe_items": [item for item in fillers if item.get("safe")],
        "review_only": [item for item in fillers if not item.get("safe")],
    }
    return cleanup, filler_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: cleanup trim plan from transcript")
    parser.add_argument("transcript", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--filler-output", type=Path, default=None)
    parser.add_argument("--gap-threshold", type=float, default=0.72)
    args = parser.parse_args()

    if not args.transcript.is_file():
        print(f"[ERROR] Transcript not found: {args.transcript}", file=sys.stderr)
        sys.exit(1)

    cleanup, filler = build_plan(args.transcript, args.gap_threshold)
    out = args.output or (args.transcript.parent / "cleanup-plan.json")
    filler_out = args.filler_output or (args.transcript.parent / "filler-removal-plan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    filler_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cleanup, ensure_ascii=False, indent=2), encoding="utf-8")
    filler_out.write_text(json.dumps(filler, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Cleanup plan: {out}")
    print(f"✅ Filler plan:  {filler_out}")
    print(f"   safe={cleanup['summary']['safe_plan_items']} review={cleanup['summary']['review_only_items']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
