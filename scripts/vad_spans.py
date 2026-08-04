#!/usr/bin/env python3
"""VideoShorts — Silero VAD карта речи/тишины (vad-speech-spans.json).

В отличие от косвенных word-gap эвристик cleanup_plan.py, здесь тишина
определяется по самому аудио нейросетевым VAD (Silero, ONNX) — sample-accurate.
Результат используют cleanup_plan.py (silence_gaps) и refine_boundaries.py
(snap точек реза к центру тишины).

Запуск:
    python vad_spans.py <video_or_audio> -o ../videoshorts-memory/transcripts/<stem>/vad-speech-spans.json

Env-ручки:
    VIDEOSHORTS_VAD=1                 — 0 отключает VAD (cleanup вернётся к word-gap)
    VIDEOSHORTS_VAD_THRESHOLD=0.5     — порог вероятности речи
    VIDEOSHORTS_VAD_MIN_SILENCE_MS=300 — min тишина внутри речи, чтобы разорвать span
    VIDEOSHORTS_VAD_SPEECH_PAD_MS=120  — паддинг вокруг speech span (защита фонем)
    VIDEOSHORTS_VAD_MIN_GAP_SEC=0.25   — min длительность silence gap в отчёте
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from videoshorts_core import configure_stdio, find_ffmpeg

configure_stdio()

SAMPLE_RATE = 16000


def vad_enabled() -> bool:
    return os.environ.get("VIDEOSHORTS_VAD", "1").strip().lower() not in {"0", "false", "off"}


def vad_available() -> bool:
    try:
        import silero_vad  # noqa: F401
        return True
    except Exception:
        return False


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def extract_audio_16k(source: Path) -> Path:
    """Декодирует любое видео/аудио в mono 16kHz WAV во временный файл."""
    ffmpeg = find_ffmpeg()
    fd, tmp = tempfile.mkstemp(prefix="videoshorts_vad_", suffix=".wav")
    os.close(fd)
    out = Path(tmp)
    cmd = [
        ffmpeg, "-y", "-i", str(source),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-acodec", "pcm_s16le", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        tail = (proc.stderr or b"")[-2000:].decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg audio extract failed ({proc.returncode}): {tail}")
    return out


def compute_speech_spans(wav_path: Path) -> dict:
    """Silero VAD → speech spans (секунды) + параметры прогона."""
    import numpy as np
    import torch
    from silero_vad import load_silero_vad, get_speech_timestamps

    threshold = _env_float("VIDEOSHORTS_VAD_THRESHOLD", 0.5)
    min_silence_ms = _env_int("VIDEOSHORTS_VAD_MIN_SILENCE_MS", 300)
    speech_pad_ms = _env_int("VIDEOSHORTS_VAD_SPEECH_PAD_MS", 120)

    import wave
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    audio_int16 = np.frombuffer(frames, dtype=np.int16)
    wav = torch.from_numpy(audio_int16.astype(np.float32) / 32768.0)

    torch.set_num_threads(1)
    model = load_silero_vad(onnx=True)
    timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=SAMPLE_RATE,
        threshold=threshold,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
        return_seconds=True,
    )
    spans = [
        {"start": round(float(ts["start"]), 3), "end": round(float(ts["end"]), 3)}
        for ts in timestamps
    ]
    duration = round(len(audio_int16) / SAMPLE_RATE, 3)
    return {
        "duration": duration,
        "speech_spans": spans,
        "params": {
            "threshold": threshold,
            "min_silence_duration_ms": min_silence_ms,
            "speech_pad_ms": speech_pad_ms,
            "sampling_rate": SAMPLE_RATE,
            "model": "silero-vad onnx",
        },
    }


def spans_to_silence_gaps(
    speech_spans: list[dict],
    duration: float,
    *,
    min_gap: float | None = None,
) -> list[dict]:
    """Инвертирует speech spans в silence gaps (включая края записи)."""
    if min_gap is None:
        min_gap = _env_float("VIDEOSHORTS_VAD_MIN_GAP_SEC", 0.25)
    gaps: list[dict] = []
    cursor = 0.0
    for span in speech_spans:
        start = float(span["start"])
        if start - cursor >= min_gap:
            gaps.append({"start": round(cursor, 3), "end": round(start, 3),
                         "duration": round(start - cursor, 3)})
        cursor = max(cursor, float(span["end"]))
    if duration - cursor >= min_gap:
        gaps.append({"start": round(cursor, 3), "end": round(duration, 3),
                     "duration": round(duration - cursor, 3)})
    return gaps


def build_vad_map(source: Path) -> dict:
    wav = extract_audio_16k(source)
    try:
        result = compute_speech_spans(wav)
    finally:
        wav.unlink(missing_ok=True)
    gaps = spans_to_silence_gaps(result["speech_spans"], result["duration"])
    return {
        "schema_version": 1,
        "source_media": str(source.resolve()),
        "duration": result["duration"],
        "params": result["params"],
        "speech_spans": result["speech_spans"],
        "silence_gaps": gaps,
        "summary": {
            "speech_spans": len(result["speech_spans"]),
            "silence_gaps": len(gaps),
            "speech_seconds": round(sum(s["end"] - s["start"] for s in result["speech_spans"]), 3),
            "silence_seconds": round(sum(g["duration"] for g in gaps), 3),
        },
    }


def load_vad_map(path: Path) -> dict | None:
    """Читает vad-speech-spans.json; None если файла нет или он битый."""
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and isinstance(data.get("silence_gaps"), list):
                return data
    except Exception:
        pass
    return None


def default_vad_path_for_transcript(transcript_path: Path) -> Path:
    return transcript_path.parent / "vad-speech-spans.json"


def snap_to_silence(ts: float, gaps: list[dict], max_dist: float = 0.6) -> float:
    """Snap точки реза к центру ближайшей VAD-тишины, если она в пределах max_dist."""
    best_ts: float | None = None
    best_dist = max_dist
    for gap in gaps:
        try:
            start = float(gap["start"])
            end = float(gap["end"])
        except Exception:
            continue
        center = (start + end) / 2.0
        dist = abs(center - ts)
        if dist <= best_dist:
            best_dist = dist
            best_ts = center
    return round(best_ts, 3) if best_ts is not None else ts


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: Silero VAD speech/silence map")
    parser.add_argument("source", type=Path, help="Видео или аудио источник")
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"[ERROR] Source not found: {args.source}", file=sys.stderr)
        sys.exit(1)
    if not vad_available():
        print("[ERROR] silero-vad не установлен: pip install silero-vad", file=sys.stderr)
        sys.exit(1)

    vad_map = build_vad_map(args.source)
    out = args.output or (args.source.parent / "vad-speech-spans.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(vad_map, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = vad_map["summary"]
    print(f"✅ VAD map: {out}")
    print(f"   speech={summary['speech_spans']} spans ({summary['speech_seconds']}s), "
          f"silence={summary['silence_gaps']} gaps ({summary['silence_seconds']}s)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
