#!/usr/bin/env python3
"""Quality presets для draft/release рендера Гиперион."""
from __future__ import annotations

import os

from typing import Any


PRESETS: dict[str, dict[str, Any]] = {
    "draft": {
        "width": 720,
        "height": 1280,
        "video_preset": "veryfast",
        "crf": 26,
        "maxrate": "5M",
        "bufsize": "10M",
        "audio_bitrate": "128k",
        "audio_rate": 48000,
        "pix_fmt": "yuv420p",
        "label": "Draft 720p — быстро",
    },
    "release": {
        "width": 1080,
        "height": 1920,
        "video_preset": "medium",
        "crf": 19,
        "maxrate": "12M",
        "bufsize": "24M",
        "audio_bitrate": "192k",
        "audio_rate": 48000,
        "pix_fmt": "yuv420p",
        "label": "Release 1080p — публикация",
    },
}

DEFAULT_PRESET = "release"

# Loudness targets for Reels / Shorts (close to platform loudness)
LOUDNORM_I = -14.0
LOUDNORM_TP = -1.5
LOUDNORM_LRA = 11.0

FPS_CAP = 60.0  # источники >60 fps (slow-mo) приводим к 60


def resolve_preset(name: str | None = None) -> dict[str, Any]:
    key = (name or DEFAULT_PRESET).strip().lower()
    if key not in PRESETS:
        key = DEFAULT_PRESET
    return {"name": key, **PRESETS[key]}


def video_encode_args(preset: dict[str, Any] | str | None = None) -> list[str]:
    cfg = resolve_preset(preset) if not isinstance(preset, dict) else preset
    args = [
        "-c:v", "libx264",
        "-preset", str(cfg.get("video_preset") or "medium"),
        "-crf", str(cfg.get("crf") or 19),
        "-pix_fmt", str(cfg.get("pix_fmt") or "yuv420p"),
        "-profile:v", "high",
        "-level", "5.1",
    ]
    maxrate = cfg.get("maxrate")
    if maxrate:
        args += ["-maxrate", str(maxrate), "-bufsize", str(cfg.get("bufsize") or maxrate)]
    args += ["-movflags", "+faststart"]
    return args


def scale_filter(width: int, height: int) -> str:
    """Lanczos-ресемплинг: заметно чётче дефолтного bilinear при даунскейле."""
    return f"scale={width}:{height}:flags=lanczos"


def sharpen_filter() -> str:
    """Лёгкий unsharp после даунскейла — «чёткость шортсов». VIDEOSHORTS_SHARPEN=0 отключает."""
    if os.getenv("VIDEOSHORTS_SHARPEN", "1").strip().lower() in {"0", "false", "off"}:
        return ""
    return "unsharp=5:5:0.6:5:5:0.0"


def color_grade_filter(*, hdr: bool = False) -> str:
    """HDR→SDR тонемаппинг (zscale+tonemap) или лёгкий грейд SDR. VIDEOSHORTS_COLOR_GRADE=0 отключает."""
    if os.getenv("VIDEOSHORTS_COLOR_GRADE", "1").strip().lower() in {"0", "false", "off"}:
        return ""
    if hdr:
        return (
            "zscale=tin=smpte2084:min=bt2020nc:pin=bt2020:npl=100,"
            "tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:p=bt709:r=tv,"
            "format=yuv420p"
        )
    return "eq=contrast=1.02:saturation=1.05"


def fps_cap_filter(fps: float | None, *, cap: float = FPS_CAP) -> str:
    """Ограничить кадровую частоту сверху (slow-mo источники >60 fps)."""
    if fps is None or fps <= cap:
        return ""
    return f"fps={int(cap)}"


def finishing_filters(*, hdr: bool = False, fps: float | None = None) -> list[str]:
    """Финишная цепочка после основного кадрирования: цвет → резкость → fps-cap."""
    parts = [
        color_grade_filter(hdr=hdr),
        sharpen_filter(),
        fps_cap_filter(fps),
    ]
    return [part for part in parts if part]


def audio_encode_args(preset: dict[str, Any] | str | None = None) -> list[str]:
    cfg = resolve_preset(preset) if not isinstance(preset, dict) else preset
    return [
        "-c:a", "aac",
        "-b:a", str(cfg.get("audio_bitrate") or "192k"),
        "-ar", str(cfg.get("audio_rate") or 48000),
    ]


def loudnorm_filter(
    measured: dict | None = None,
    *,
    i: float = LOUDNORM_I,
    tp: float = LOUDNORM_TP,
    lra: float = LOUDNORM_LRA,
) -> str:
    if measured and measured.get("input_i") is not None:
        return (
            f"loudnorm=I={i}:TP={tp}:LRA={lra}:"
            f"measured_I={measured.get('input_i')}:"
            f"measured_TP={measured.get('input_tp')}:"
            f"measured_LRA={measured.get('input_lra')}:"
            f"measured_thresh={measured.get('input_thresh')}:"
            f"offset={measured.get('target_offset', 0)}:"
            f"linear=true"
        )
    return f"loudnorm=I={i}:TP={tp}:LRA={lra}"
