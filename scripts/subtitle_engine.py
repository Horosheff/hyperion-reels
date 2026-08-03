"""
Subtitle Engine — ASS/SSA karaoke + SRT.
Порт из shorts_service/backend/app/subtitle_engine.py (standalone, без FastAPI settings).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from safe_zones import subtitle_min_margin_v, subtitle_side_margins


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


@dataclass
class SubtitleTemplate:
    name: str = "default"
    font: str = "Arial"
    font_size: int = 24
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFFF00"
    outline_color: str = "#000000"
    back_color: str = "#00000080"
    outline_width: int = 2
    shadow: int = 1
    bold: bool = True
    italic: bool = False
    uppercase: bool = True
    position: str = "bottom"
    margin_v: int = 50
    margin_h: int = 20
    alignment: int = 2
    animation: str = "karaoke"
    words_per_line: int = 4
    max_chars_per_line: int = 35


TEMPLATES: dict[str, SubtitleTemplate] = {
    "default": SubtitleTemplate(),
    "mrbeast": SubtitleTemplate(
        name="mrbeast", font="Impact", font_size=52,
        primary_color="#FFFFFF", highlight_color="#FFFFFF",
        outline_width=4, bold=True, uppercase=True,
        margin_v=120, animation="karaoke", words_per_line=3,
    ),
    "hormozi": SubtitleTemplate(
        name="hormozi", font="Arial", font_size=48,
        highlight_color="#00FF00", outline_width=3,
        margin_v=100, words_per_line=4,
    ),
    "minimal": SubtitleTemplate(
        name="minimal", font="Arial", font_size=20,
        bold=False, uppercase=False, margin_v=30, animation="fade", words_per_line=5,
    ),
    "neon": SubtitleTemplate(
        name="neon", font="Arial", font_size=26,
        primary_color="#FF00FF", highlight_color="#00FFFF",
        position="center", words_per_line=3,
    ),
    "fire": SubtitleTemplate(
        name="fire", font="Impact", font_size=30,
        primary_color="#FF6600", highlight_color="#FF0000",
        position="center", words_per_line=3,
    ),
}


def hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 8:
        r, g, b, a = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), int(hex_color[6:8], 16)
    elif len(hex_color) == 6:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        a = alpha
    else:
        return "&H00FFFFFF"
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


def get_template(name: str) -> SubtitleTemplate:
    return TEMPLATES.get(name.lower(), TEMPLATES["default"])


def load_custom_template(path: Path) -> SubtitleTemplate | None:
    """Load a shorts_service-compatible JSON subtitle template."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return SubtitleTemplate(
            name=str(data.get("name", "custom")),
            font=str(data.get("font", "Arial")),
            font_size=int(data.get("fontSize", data.get("font_size", 24))),
            primary_color=str(data.get("primaryColor", data.get("primary_color", "#FFFFFF"))),
            highlight_color=str(data.get("highlightColor", data.get("highlight_color", "#FFFF00"))),
            outline_color=str(data.get("outlineColor", data.get("outline_color", "#000000"))),
            back_color=str(data.get("backColor", data.get("back_color", "#00000080"))),
            outline_width=int(data.get("outlineWidth", data.get("outline_width", 2))),
            shadow=int(data.get("shadow", 1)),
            bold=bool(data.get("bold", True)),
            italic=bool(data.get("italic", False)),
            uppercase=bool(data.get("uppercase", True)),
            position=str(data.get("position", "bottom")),
            margin_v=int(data.get("marginV", data.get("margin_v", 50))),
            margin_h=int(data.get("marginH", data.get("margin_h", 20))),
            alignment=int(data.get("alignment", 2)),
            animation=str(data.get("animation", "karaoke")),
            words_per_line=int(data.get("wordsPerLine", data.get("words_per_line", 4))),
            max_chars_per_line=int(data.get("maxCharsPerLine", data.get("max_chars_per_line", 35))),
        )
    except Exception:
        return None


def resolve_template(template_name: str = "mrbeast", custom_template: Path | None = None) -> SubtitleTemplate:
    if custom_template:
        template = load_custom_template(custom_template)
        if template:
            return template
    env_template = os.environ.get("VIDEOSHORTS_SUBTITLES_TEMPLATE_JSON", "").strip()
    if env_template:
        template = load_custom_template(Path(env_template))
        if template:
            return template
    return get_template(template_name)


def list_templates() -> list[str]:
    return list(TEMPLATES.keys())


def format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_header(template: SubtitleTemplate, video_width: int = 720, video_height: int = 1280) -> str:
    base_align = template.alignment
    if template.position == "top":
        alignment = base_align + 6
    elif template.position == "center":
        alignment = base_align + 3
    else:
        alignment = base_align

    primary = hex_to_ass_color(template.primary_color)
    secondary = hex_to_ass_color(template.highlight_color)
    outline = hex_to_ass_color(template.outline_color)
    back = hex_to_ass_color(template.back_color, 128)
    bold = -1 if template.bold else 0
    italic = -1 if template.italic else 0

    # Safe zone: субтитры не должны попадать под UI платформы (название/описание
    # снизу, колонка лайков справа). Отступы шаблона только увеличиваем.
    margin_v = template.margin_v
    margin_l = template.margin_h
    margin_r = template.margin_h
    if template.position == "bottom":
        margin_v = max(margin_v, subtitle_min_margin_v(video_height))
    min_l, min_r = subtitle_side_margins(video_width)
    margin_l = max(margin_l, min_l)
    margin_r = max(margin_r, min_r)

    return f"""[Script Info]
Title: VideoShorts Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{template.font},{template.font_size},{primary},{secondary},{outline},{back},{bold},{italic},0,0,100,100,0,0,1,{template.outline_width},{template.shadow},{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def generate_karaoke_line(
    words: list[dict[str, Any]],
    template: SubtitleTemplate,
    line_start: float,
    line_end: float,
    hook_style: bool = False,
    hook_scale: float = 1.3,
) -> str:
    start_ts = format_ass_time(line_start)
    end_ts = format_ass_time(line_end)
    parts = []
    for i, word in enumerate(words):
        word_text = word["word"].strip()
        if not word_text:
            continue
        k_duration = max(1, int((word["end"] - word["start"]) * 100))
        if template.uppercase:
            word_text = word_text.upper()
        is_first = (i == 0) and hook_style
        scale_pct = int(hook_scale * 100) if is_first else 100
        if template.animation == "karaoke":
            if is_first:
                parts.append(f"{{\\fscx{scale_pct}\\fscy{scale_pct}\\kf{k_duration}}}{word_text}{{\\fscx100\\fscy100}}")
            else:
                parts.append(f"{{\\kf{k_duration}}}{word_text}")
        else:
            parts.append(f"{{\\k{k_duration}}}{word_text}")
    text = " ".join(parts)
    return f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}"


HOOK_KEY_COLOR = "#FFE500"  # жёлтая плашка ключевого слова (как «NEWS» на референсе)


def _hook_top_margin(video_height: int) -> int:
    """Верхняя треть кадра, но ниже шапки канала (safe top)."""
    from safe_zones import get_safe_zone
    return get_safe_zone(1, video_height).top + int(video_height * 0.13)


def generate_hook_styles(template: SubtitleTemplate, video_width: int, video_height: int) -> str:
    """Доп. стили Hook/HookKey для заголовка-заставки (pop-in, жёлтая плашка)."""
    size = max(template.font_size + 10, int(template.font_size * 1.6))
    margin_v = _hook_top_margin(video_height)
    margin_l, margin_r = subtitle_side_margins(video_width)
    margin_l = max(margin_l, template.margin_h)
    margin_r = max(margin_r, template.margin_h)
    white = hex_to_ass_color(template.primary_color)
    outline = hex_to_ass_color(template.outline_color)
    black = hex_to_ass_color("#000000")
    key_bg = hex_to_ass_color(HOOK_KEY_COLOR)
    key_text = black
    box_outline = hex_to_ass_color(HOOK_KEY_COLOR)
    return (
        f"Style: Hook,{template.font},{size},{white},{white},{outline},{black},-1,0,0,0,100,100,0,0,1,{max(4, template.outline_width + 1)},1,8,{margin_l},{margin_r},{margin_v},1\n"
        f"Style: HookKey,{template.font},{size},{key_text},{key_text},{box_outline},{key_bg},-1,0,0,0,100,100,0,0,3,4,0,8,{margin_l},{margin_r},{margin_v},1\n"
    )


def _hook_clean_words(text: str, max_words: int = 6) -> list[str]:
    words = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-–][0-9A-Za-zА-Яа-яЁё]+)?", text or "")
    words = [w for w in words if not w.lower().startswith(("http", "www"))]
    return [w.upper() for w in words[:max_words]]


def _hook_wrap(words: list[str], max_chars: int = 12, max_lines: int = 3) -> list[list[str]]:
    """Строки ≤ max_chars; слова, не влезшие в max_lines строк, отбрасываются —
    заставка обязана остаться внутри safe width, а не дословной цитатой."""
    lines: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if current and sum(len(w) for w in current) + len(current) - 1 + 1 + len(word) > max_chars:
            lines.append(current)
            current = []
            if len(lines) >= max_lines:
                break
        current.append(word)
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _hook_keyword_index(words: list[str]) -> int:
    best, best_len = 0, 0
    for i, word in enumerate(words):
        if len(word) >= 4 and len(word) > best_len:
            best, best_len = i, len(word)
    return best


def generate_hook_event(
    hook_text: str,
    template: SubtitleTemplate,
    duration: float = 3.0,
    word_stagger: float = 0.16,
    video_width: int = 720,
    video_height: int = 1280,
) -> list[str]:
    r"""По одному Dialogue на строку заставки: pop-in пословно + bounce,
    жёлтая плашка ключевого слова, fade-out. Каждая строка на явном \pos —
    libass якорит многострочные блоки непредсказуемо, по-строчно надёжнее."""
    words = _hook_clean_words(hook_text)
    if not words:
        return []
    key_idx = _hook_keyword_index(words)
    lines = _hook_wrap(words)
    hook_style_size = max(template.font_size + 10, int(template.font_size * 1.6))
    line_height = int(hook_style_size * 1.35)
    top_y = _hook_top_margin(video_height)
    center_x = video_width // 2
    end_ts = format_ass_time(max(duration, 0.6))
    events: list[str] = []
    word_pos = 0
    for li, line in enumerate(lines):
        parts: list[str] = []
        for wi, word in enumerate(line):
            t0 = int(word_pos * word_stagger * 1000)
            t1 = t0 + 160
            t2 = t0 + 280
            pop = (
                f"{{\\alpha&HFF&\\fscx150\\fscy150"
                f"\\t({t0},{t1},\\fscx118\\fscy118\\alpha&H00&)"
                f"\\t({t1},{t2},\\fscx100\\fscy100)}}"
            )
            if word_pos == key_idx:
                parts.append(f"{{\\rHookKey}}{pop}{word}{{\\rHook}}")
            else:
                parts.append(f"{pop}{word}")
            if wi < len(line) - 1:
                parts.append(" ")
            word_pos += 1
        y = top_y + li * line_height
        events.append(
            f"Dialogue: 1,0:00:00.00,{end_ts},Hook,,0,0,0,,"
            f"{{\\an8\\pos({center_x},{y})\\fad(0,280)}}{''.join(parts)}"
        )
    return events


EMOJI_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(важно|главное|attention|important)\b", re.I), " ⚡"),
    (re.compile(r"\b(огонь|круто|вау|wow|amazing|incredible)\b", re.I), " 🔥"),
    (re.compile(r"\b(шок|офигеть|невероятно|shocking|crazy)\b", re.I), " 😱"),
    (re.compile(r"\b(деньги|продажи|выручка|money|sales)\b", re.I), " 💰"),
    (re.compile(r"\b(нейросет|ai|ии|gpt|cursor)\b", re.I), " 🤖"),
]


def add_rule_based_emojis(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Graceful local fallback for SUBTITLES_EMOJI without paid API keys."""
    if not words:
        return words
    max_emojis = int(os.environ.get("VIDEOSHORTS_SUBTITLES_EMOJI_MAX", "8"))
    result = [w.copy() for w in words]
    used = 0
    last_time = -999.0
    for item in result:
        text = str(item.get("word", ""))
        start = float(item.get("start", 0))
        if start - last_time < 2.0:
            continue
        for pattern, emoji in EMOJI_RULES:
            if pattern.search(text):
                if emoji.strip() not in text:
                    item["word"] = text.rstrip() + emoji
                    used += 1
                    last_time = start
                break
        if used >= max_emojis:
            break
    return result


def write_ass(
    path: Path,
    words: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
    template_name: str = "mrbeast",
    video_width: int = 720,
    video_height: int = 1280,
    custom_template: Path | None = None,
    emoji: bool | None = None,
    hook_text: str | None = None,
) -> None:
    template = resolve_template(template_name, custom_template)
    hook_style = _env_bool("VIDEOSHORTS_SUBTITLES_HOOK_STYLE", "0")
    hook_scale = _env_float("VIDEOSHORTS_SUBTITLES_HOOK_SCALE", "1.3")
    hook_duration = _env_float("VIDEOSHORTS_HOOK_TITLE_DURATION", "3.0")

    clip_words = []
    for w in words:
        if w["end"] > clip_start and w["start"] < clip_end:
            clip_words.append({
                "start": max(0, w["start"] - clip_start),
                "end": min(clip_end - clip_start, w["end"] - clip_start),
                "word": w["word"],
            })

    if emoji if emoji is not None else _env_bool("VIDEOSHORTS_SUBTITLES_EMOJI", "0"):
        clip_words = add_rule_based_emojis(clip_words)

    if not clip_words:
        header = generate_ass_header(template, video_width, video_height)
        hook_events = (
            generate_hook_event(hook_text, template, duration=hook_duration,
                                video_width=video_width, video_height=video_height)
            if hook_text else []
        )
        if hook_events:
            header = header.replace(
                "\n[Events]",
                "\n" + generate_hook_styles(template, video_width, video_height) + "[Events]",
                1,
            )
            header += "\n".join(hook_events) + "\n"
        path.write_text(header, encoding="utf-8")
        return

    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_chars = 0
    for word in clip_words:
        word_text = word["word"].strip()
        if not word_text:
            continue
        start_new = False
        if len(current_line) >= template.words_per_line:
            start_new = True
        elif current_chars + len(word_text) + 1 > template.max_chars_per_line:
            start_new = True
        elif current_line and word["start"] - current_line[-1]["end"] > 1.5:
            start_new = True
        if start_new and current_line:
            lines.append(current_line)
            current_line = []
            current_chars = 0
        current_line.append(word)
        current_chars += len(word_text) + 1
    if current_line:
        lines.append(current_line)

    content = generate_ass_header(template, video_width, video_height)
    hook_events = (
        generate_hook_event(hook_text, template, duration=hook_duration,
                            video_width=video_width, video_height=video_height)
        if hook_text else []
    )
    if hook_events:
        content = content.replace(
            "\n[Events]",
            "\n" + generate_hook_styles(template, video_width, video_height) + "[Events]",
            1,
        )
        content += "\n".join(hook_events) + "\n"
    for line_words in lines:
        if not line_words:
            continue
        dialogue = generate_karaoke_line(
            line_words, template, line_words[0]["start"], line_words[-1]["end"],
            hook_style=hook_style, hook_scale=hook_scale,
        )
        content += dialogue + "\n"
    path.write_text(content, encoding="utf-8")


def write_srt_for_clip(
    path: Path,
    segments: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
    max_chars: int | None = None,
    words: list[dict[str, Any]] | None = None,
    words_per_group: int | None = None,
    uppercase: bool = True,
) -> None:
    max_chars = max_chars or int(os.environ.get("VIDEOSHORTS_SUBTITLES_MAX_CHARS", "35"))
    words_per_group = words_per_group or int(os.environ.get("VIDEOSHORTS_SUBTITLES_WORDS_PER_GROUP", "4"))

    def fmt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    entries: list[tuple[float, float, str]] = []
    clip_words = [
        w for w in (words or [])
        if float(w.get("end", 0)) > clip_start and float(w.get("start", 0)) < clip_end
    ]
    if clip_words:
        group: list[dict[str, Any]] = []
        chars = 0
        for word in clip_words:
            text = str(word.get("word", "")).strip()
            if not text:
                continue
            gap = float(word.get("start", 0)) - float(group[-1].get("end", 0)) if group else 0
            if group and (len(group) >= words_per_group or chars + len(text) + 1 > max_chars or gap > 1.0):
                start = max(0, float(group[0]["start"]) - clip_start)
                end = min(clip_end - clip_start, float(group[-1]["end"]) - clip_start)
                line = " ".join(str(w.get("word", "")).strip() for w in group)
                entries.append((start, end, line.upper() if uppercase else line))
                group = []
                chars = 0
            group.append(word)
            chars += len(text) + 1
        if group:
            start = max(0, float(group[0]["start"]) - clip_start)
            end = min(clip_end - clip_start, float(group[-1]["end"]) - clip_start)
            line = " ".join(str(w.get("word", "")).strip() for w in group)
            entries.append((start, end, line.upper() if uppercase else line))
    else:
        for seg in segments:
            s0, s1 = float(seg["start"]), float(seg["end"])
            if s1 <= clip_start or s0 >= clip_end:
                continue
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            entries.append((max(0, s0 - clip_start), min(clip_end - clip_start, s1 - clip_start), text[:max_chars]))

    lines: list[str] = []
    for i, (a, b, text) in enumerate(entries, 1):
        lines.extend([str(i), f"{fmt_time(a)} --> {fmt_time(b)}", text, ""])
    path.write_text("\n".join(lines), encoding="utf-8")
