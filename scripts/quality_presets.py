#!/usr/bin/env python3
"""Quality presets для draft/release рендера Гиперион."""
from __future__ import annotations

from typing import Any


PRESETS: dict[str, dict[str, Any]] = {
    "draft": {
        "width": 720,
        "height": 1280,
        "video_preset": "veryfast",
        "crf": 26,
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


def resolve_preset(name: str | None) -> dict[str, Any]:
    key = (name or DEFAULT_PRESET).strip().lower()
    if key not in PRESETS:
        key = DEFAULT_PRESET
    return {"name": key, **PRESETS[key]}


def video_encode_args(preset: dict[str, Any] | str | None = None) -> list[str]:
    cfg = resolve_preset(preset) if not isinstance(preset, dict) else preset
    return [
        "-c:v", "libx264",
        "-preset", str(cfg.get("video_preset") or "medium"),
        "-crf", str(cfg.get("crf") or 19),
        "-pix_fmt", str(cfg.get("pix_fmt") or "yuv420p"),
        "-profile:v", "high",
        "-level", "4.1",
        "-movflags", "+faststart",
    ]


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
