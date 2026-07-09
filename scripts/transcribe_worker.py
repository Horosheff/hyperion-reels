#!/usr/bin/env python3
"""
Изолированный процесс для Whisper (faster-whisper).
Порт из shorts/webinar_cutter/transcribe_worker.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, List


def _configure_stdio() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _prepend_nvidia_wheel_bins_to_path() -> None:
    if sys.platform != "win32":
        return
    import site

    root = Path(__file__).resolve().parent
    site_dirs: list[str] = []
    try:
        site_dirs.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        u = site.getusersitepackages()
        if u:
            site_dirs.append(u)
    except Exception:
        pass
    for vdir in (".venv", ".venv310"):
        p = root / vdir / "Lib" / "site-packages"
        if p.is_dir():
            site_dirs.append(str(p))
    shorts_sp = root.parent.parent / "shorts" / "shorts_service" / "backend" / ".venv310" / "Lib" / "site-packages"
    if shorts_sp.is_dir():
        site_dirs.append(str(shorts_sp.resolve()))

    bins: list[str] = []
    seen_sp: set[str] = set()
    for sp in site_dirs:
        if not sp or sp in seen_sp:
            continue
        seen_sp.add(sp)
        nvidia_root = Path(sp) / "nvidia"
        if not nvidia_root.is_dir():
            continue
        for child in sorted(nvidia_root.iterdir()):
            if child.is_dir():
                b = child / "bin"
                if b.is_dir():
                    bins.append(str(b.resolve()))
    if bins:
        os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")


def _detect_device() -> str:
    try:
        import ctypes
        ctypes.CDLL("nvcuda.dll" if os.name == "nt" else "libcuda.so")
        return "cuda"
    except OSError:
        return "cpu"


def main() -> None:
    _configure_stdio()
    _prepend_nvidia_wheel_bins_to_path()

    if len(sys.argv) != 4:
        sys.stderr.write("usage: transcribe_worker.py <audio.wav> <model> <out.json>\n")
        sys.exit(2)

    audio_path = Path(sys.argv[1]).resolve()
    model_size = sys.argv[2]
    out_json = Path(sys.argv[3]).resolve()

    if not audio_path.is_file():
        sys.stderr.write(f"[ERROR] audio not found: {audio_path}\n")
        sys.exit(1)

    from faster_whisper import WhisperModel

    force_cpu = os.environ.get("VIDEOSHORTS_WHISPER_FORCE_CPU", "").strip().lower() in ("1", "true", "yes")
    device = "cpu" if force_cpu else (os.environ.get("VIDEOSHORTS_WHISPER_DEVICE", "").strip() or _detect_device())
    compute_type = os.environ.get("VIDEOSHORTS_WHISPER_COMPUTE_TYPE", "").strip() or (
        "int8" if device == "cpu" else "float16"
    )

    model: Any = None
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print(f"   Whisper: device={device} compute_type={compute_type}", flush=True)
    except Exception as e:
        print(f"   [warn] Whisper load {device}/{compute_type}: {e}", flush=True)
        if device == "cpu":
            print(f"[ERROR] Could not load Whisper model: {e}", flush=True)
            sys.exit(1)
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("   Whisper: fallback device=cpu compute_type=int8", flush=True)

    vad_params = dict(min_silence_duration_ms=500, speech_pad_ms=400, min_speech_duration_ms=250)
    lang = os.environ.get("VIDEOSHORTS_WHISPER_LANGUAGE", "").strip() or None
    beam_size = int(os.environ.get("VIDEOSHORTS_WHISPER_BEAM_SIZE", "1"))
    word_mode = os.environ.get("VIDEOSHORTS_WHISPER_WORD_TIMESTAMPS", "1").strip().lower() in ("1", "true", "yes")

    segments, info = model.transcribe(
        str(audio_path),
        vad_filter=True,
        vad_parameters=vad_params,
        language=lang,
        beam_size=beam_size,
        word_timestamps=word_mode,
    )
    print(f"   Language: {info.language} ({info.language_probability:.0%})", flush=True)

    segments_list = list(segments)
    print(f"   transcribe: materialized {len(segments_list)} segments", flush=True)

    rows = []
    all_words: list[dict] = []
    last_pulse = time.monotonic()
    for n, seg in enumerate(segments_list, 1):
        row = {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        rows.append(row)
        if word_mode and hasattr(seg, "words") and seg.words:
            for word in seg.words:
                w = str(word.word).strip()
                if w:
                    all_words.append({"start": float(word.start), "end": float(word.end), "word": w})
        now = time.monotonic()
        if n % 20 == 0 or now - last_pulse >= 8.0:
            print(f"   transcribe: {n} segments | t≈{seg.end/60:.1f} min", flush=True)
            last_pulse = now

    payload = {
        "language": info.language,
        "language_probability": float(info.language_probability),
        "segments": rows,
    }
    if all_words:
        payload["words"] = all_words
        if rows:
            rows[0]["_words"] = all_words
        print(f"   transcribe: {len(all_words)} word timestamps", flush=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
