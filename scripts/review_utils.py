#!/usr/bin/env python3
"""Shared lightweight helpers for VideoShorts local review drafts."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def read_json(path: Path | None, default: Any) -> Any:
    if not path or not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clean(text: str, limit: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if limit and len(value) > limit:
        return value[: max(0, limit - 3)].rstrip(" ,.;:") + "..."
    return value


def clip_text(segments: list, start: float, end: float, limit: int = 1200) -> str:
    return clean(" ".join(s.text for s in segments if s.end > start and s.start < end), limit)


def items_by_index(payload: dict) -> dict[str, dict]:
    return {
        str(item.get("index")): item
        for item in payload.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(payload, dict) else {}


def candidate_overlap(candidate: dict, start: float, end: float) -> float:
    try:
        s = float(candidate.get("start", 0))
        e = float(candidate.get("end", s))
    except Exception:
        return 0.0
    overlap = max(0.0, min(e, end) - max(s, start))
    duration = max(0.001, min(e - s, end - start))
    return overlap / duration


def best_candidate_for_clip(candidates: list[dict], start: float, end: float) -> dict:
    best: tuple[float, dict] = (0.0, {})
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        overlap = candidate_overlap(candidate, start, end)
        if overlap > best[0]:
            best = (overlap, candidate)
    return best[1] if best[0] >= 0.25 else {}


def looks_incomplete(text: str) -> bool:
    tail = clean(text).lower()[-180:].strip(" \t\r\n.,!?…:;-")
    if not tail:
        return True
    return tail.startswith((
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
    )) or tail in {"так", "итак", "сейчас", "дальше"}


def has_payoff(text: str) -> bool:
    """Detect insight/result ending — including RU webinar Q&A / mythbust punchlines."""
    tail = clean(text).lower()[-420:]
    if re.search(
        r"(итог|вывод|поэтому|так что|вот так|главная суть|суть|получается|"
        r"результат|в итоге|значит|запомните|conclusion|therefore|so the point|"
        r"потому что|только\s+\w+|нужен\s+\w+|не\s+нужен|не\s+подойд|"
        r"наоборот|миф|ключевое|пока\b|оплачива|его\s+cursor|его\s+курсор|"
        r"плагин|субагент|хайпанул|проще\s+нет|нет[,.]?\s*$|"
        # Procedural / live-proof closers (INC-0919)
        r"по\s+триггеру|триггер[аеу]?\b|идём\s+проверять|идем\s+проверять|"
        r"распаковать|установ(ка|ить|им)|extensions?|chrome|яндекс|"
        r"сработало|опубликова|готово\b|кот\s+в\s+мешке)",
        tail,
    ):
        return True
    # Short decisive verdict at end: «только курсор», «нет — нужен Cursor»
    if re.search(r"(только\s+[\w\-]+|нет\s*[—\-–:]|да\s*[—\-–:]|нужен\s+[\w\-]+)\s*[.!?…]*\s*$", tail):
        return True
    # Procedural closer at end of clip
    if re.search(
        r"(по\s+триггеру|идём\s+проверять|идем\s+проверять|распаковать|"
        r"установим|установка|extensions?)\s*[.!?…]*\s*$",
        tail,
    ):
        return True
    return False
