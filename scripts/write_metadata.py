#!/usr/bin/env python3
"""VideoShorts — публикационные поля для каждого клипа.

Это инструмент агента videoshorts-metadata-writer. Он не публикует ролики,
а готовит title/description/hashtags/pinned_comment/cover_prompt рядом с MP4.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

from videoshorts_core import clips_from_json, configure_stdio, segments_from_json

configure_stdio()


def _clean(text: str, limit: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if limit and len(value) > limit:
        # Prefer word boundary — never mid-word + «...»
        cut = value[:limit].rstrip(" ,.;:…-—")
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0].rstrip(" ,.;:…-—")
        return cut
    return value


def _phrase_aware_cut(text: str, limit: int) -> str:
    """Cut on phrase/clause boundary when possible — avoid mid-phrase titles (INC-0933)."""
    value = _clean(text)
    if len(value) <= limit:
        return value
    # Prefer first complete sentence / clause within limit
    for pat in (
        rf"^(.{{12,{limit}}}?[.!?…])(?:\s|$)",
        rf"^(.{{12,{limit}}}?[:;—–\-])(?:\s|$)",
        rf"^(.{{12,{limit}}}?[,])(?:\s|$)",
    ):
        match = re.search(pat, value)
        if match:
            candidate = match.group(1).rstrip(" ,.;:…-—")
            if 12 <= len(candidate) <= limit:
                return candidate
    # Fall back to last whole word inside limit
    return _clean(value, limit)


def _clip_text(segments: list[dict], start: float, end: float) -> str:
    parts = [
        str(seg.get("text", "")).strip()
        for seg in segments
        if float(seg.get("end", 0)) > start and float(seg.get("start", 0)) < end
    ]
    return _clean(" ".join(p for p in parts if p))


def _first_sentence(text: str, limit: int = 70) -> str:
    clean = _clean(text)
    match = re.search(r"^(.{8,}?[.!?…])(?:\s|$)", clean)
    sentence = match.group(1) if match else clean
    return _phrase_aware_cut(sentence, limit)


def _title_from_hook(hook: str, limit: int = 70) -> str:
    title = _phrase_aware_cut(hook, limit)
    # Drop trailing ellipsis artifacts from older drafts
    title = re.sub(r"\.{2,}$", "", title).rstrip(" …")
    # Avoid dangling mid-phrase tails («ещё не», «и мы», «потому что»)
    dangling_tails = (
        "ещё не", "еще не", "и мы", "и я", "потому что", "то есть",
        "а если", "ну и", "как бы", "в том", "для того",
    )
    lower = title.lower()
    for tail in dangling_tails:
        if lower.endswith(tail):
            title = title[: -len(tail)].rstrip(" ,.;:…-—")
            break
    if not title:
        return "Главный инсайт"
    return title


def _summary_lines(text: str, payoff: str, hook: str) -> str:
    """2–4 line description from hook/payoff + one clean beat (not raw dump)."""
    lines: list[str] = []
    hook_line = _phrase_aware_cut(hook, 110)
    if hook_line:
        lines.append(hook_line)
    payoff_line = _phrase_aware_cut(payoff, 140)
    if payoff_line and payoff_line.lower() not in (hook_line or "").lower():
        lines.append(payoff_line)
    # One short supporting beat: complete sentence only
    body = _clean(text)
    if body:
        sentences = re.split(r"(?<=[.!?…])\s+", body)
        pick = ""
        for s in reversed(sentences):
            s = _clean(s)
            if not re.search(r"[.!?…]$", s):
                continue
            s = _phrase_aware_cut(s, 120)
            if len(s) < 24:
                continue
            if hook_line and s.lower()[:40] == hook_line.lower()[:40]:
                continue
            if payoff_line and payoff_line.lower() in s.lower():
                continue
            # Skip mid-thought / filler beats
            if re.match(r"^(то есть|ну|типа|короче|итак)\b", s.lower()):
                continue
            pick = s
            break
        if pick and len(lines) < 3:
            lines.append(pick)
    if len(lines) < 2:
        lines.append("Смотри до конца — разбор без воды.")
    elif len(lines) < 4:
        lines.append("Сохрани и забери в работу.")
    return "\n\n".join(lines[:4])


def _hashtags(profile: str, text: str) -> list[str]:
    base = ["#shorts", "#reels", "#вебинар", "#инсайт"]
    if profile == "sales":
        base = ["#shorts", "#reels", "#продажи", "#маркетинг", "#бизнес"]
    elif profile == "education":
        base = ["#shorts", "#reels", "#обучение", "#инструкция", "#разбор"]
    elif profile == "podcast":
        base = ["#shorts", "#reels", "#подкаст", "#мнение", "#инсайт"]

    lower = text.lower()
    topical: list[str] = []
    keyword_map = [
        ("курсор", "#cursor"),
        ("cursor", "#cursor"),
        ("teya", "#teya"),
        ("тея", "#teya"),
        ("vscode", "#vscode"),
        ("vs code", "#vscode"),
        ("codex", "#codex"),
        ("плагин", "#cursor"),
        ("субагент", "#aiagents"),
        ("нейросет", "#нейросети"),
        (" ai", "#ai"),
        ("make.com", "#make"),
        (" make ", "#make"),
        ("автоматиза", "#автоматизация"),
        ("контент", "#контент"),
        ("воронк", "#воронка"),
        ("вайбкод", "#вайбкодинг"),
        ("mcp", "#mcp"),
    ]
    for key, tag in keyword_map:
        if key in lower and tag not in topical:
            topical.append(tag)

    tags: list[str] = []
    for tag in [*base, *topical]:
        if tag.lower() not in [t.lower() for t in tags]:
            tags.append(tag)
    return tags[:8]


def _pinned_comment(index: int, hook: str, payoff: str, text: str) -> str:
    topic = _phrase_aware_cut(hook or payoff or text, 48)
    # Prefer a short noun phrase without dangling mid-cut
    if topic and not re.search(r"[.!?…]$", topic):
        # Keep whole words only; drop trailing conjunctions
        topic = re.sub(
            r"\s+(и|а|но|или|потому|то|как|что|ещё|еще|не)\s*$",
            "",
            topic,
            flags=re.I,
        ).rstrip(" ,.;:…-—")
    templates = [
        f"Согласны с «{topic}»? Пишите в комментах.",
        f"Что думаете про это: {topic}?",
        f"Какой момент разобрать следующим после «{topic}»?",
        f"Сохраняйте, если зашло: {topic}",
        f"А у вас как с этим? {topic}",
        f"Вопрос в зал: согласны с выводом про «{topic}»?",
        f"Напишите свой кейс по теме: {topic}",
    ]
    return templates[(index - 1) % len(templates)]


def build_metadata(index: int, clip: dict, text: str, profile: str) -> dict:
    evidence = clip.get("semantic_boundary_evidence") if isinstance(clip.get("semantic_boundary_evidence"), dict) else {}
    hook_raw = clip.get("hook") or evidence.get("hook") or _first_sentence(text)
    hook = _phrase_aware_cut(hook_raw, 80)
    title = _title_from_hook(hook, 70)
    payoff = _phrase_aware_cut(clip.get("payoff_ending") or evidence.get("payoff_ending") or "", 180)
    description = _summary_lines(text, payoff, hook)
    tags = _hashtags(profile, f"{text} {hook} {payoff}")
    cover_hook = _phrase_aware_cut(hook, 42)
    return {
        "index": index,
        "clip_file": clip.get("final_file") or clip.get("file"),
        "start": clip.get("start"),
        "end": clip.get("end"),
        "duration": round(float(clip.get("end", 0)) - float(clip.get("start", 0)), 2),
        "profile": profile,
        "hook": hook,
        "title": title,
        "description": description,
        "hashtags": tags,
        "pinned_comment": _pinned_comment(index, hook, payoff, text),
        "cover_prompt": (
            f"Вертикальная обложка 9:16 для Shorts/Reels. Крупный эмоциональный герой, "
            f"контрастный современный дизайн, короткий русский хук: «{cover_hook}». "
            "Не использовать скриншот как единственный визуал, собрать сцену по смыслу клипа."
        ),
        "transcript_excerpt": _clean(text, 900),
        "semantic_boundary_evidence": evidence,
        "copy_block": "\n".join([title, "", description, "", " ".join(tags)]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: metadata per clip")
    parser.add_argument("transcript", type=Path)
    parser.add_argument("moments", type=Path)
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--profile", default="webinar", choices=["webinar", "sales", "education", "podcast"])
    parser.add_argument("-o", "--output-dir", type=Path, default=None)
    args = parser.parse_args()

    if not args.transcript.is_file() or not args.moments.is_file() or not args.clips_dir.is_dir():
        print("[ERROR] transcript, moments or clips_dir not found", file=sys.stderr)
        sys.exit(1)

    transcript_data = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    moments_data = json.loads(args.moments.read_text(encoding="utf-8-sig"))
    segments = [s.__dict__ for s in segments_from_json(transcript_data)]
    moment_clips = [c.__dict__ for c in clips_from_json(moments_data)]

    manifest_path = args.clips_dir / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"clips": []}
    manifest_clips = manifest_data.get("clips", []) if isinstance(manifest_data, dict) else []
    source_clips = manifest_clips or moment_clips

    out_dir = args.output_dir or (args.clips_dir / "metadata")
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    keep_indexes: set[int] = set()
    for index, clip in enumerate(source_clips, 1):
        idx = int(clip.get("index") or index)
        keep_indexes.add(idx)
        start = float(clip.get("start", 0))
        end = float(clip.get("end", 0))
        evidence = clip.get("semantic_boundary_evidence") if isinstance(clip.get("semantic_boundary_evidence"), dict) else {}
        text = _clean(
            clip.get("transcript_excerpt")
            or evidence.get("transcript_excerpt")
            or _clip_text(segments, start, end)
        )
        metadata = build_metadata(idx, clip, text, args.profile)
        json_name = f"clip_{idx:02d}.metadata.json"
        md_name = f"clip_{idx:02d}.metadata.md"
        (out_dir / json_name).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / md_name).write_text(
            "\n".join([
                f"# {metadata['title']}",
                "",
                "## Описание",
                metadata["description"],
                "",
                "## Хештеги",
                " ".join(metadata["hashtags"]),
                "",
                "## Закреплённый комментарий",
                metadata["pinned_comment"],
                "",
                "## Обложка",
                metadata["cover_prompt"],
            ]),
            encoding="utf-8",
        )
        entries.append({"index": idx, "json": json_name, "markdown": md_name, **metadata})

    # Remove stale metadata from previous larger keep sets
    for stale in out_dir.glob("clip_*.metadata.*"):
        m = re.search(r"clip_(\d+)", stale.name)
        if m and int(m.group(1)) not in keep_indexes:
            stale.unlink(missing_ok=True)

    manifest = {
        "schema_version": 1,
        "profile": args.profile,
        "clips": entries,
        "source_transcript": str(args.transcript.resolve()),
        "source_moments": str(args.moments.resolve()),
    }
    (args.clips_dir / "metadata-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Metadata for {len(entries)} clip(s) → {out_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
