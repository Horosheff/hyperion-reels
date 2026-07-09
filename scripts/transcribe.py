#!/usr/bin/env python3
"""VideoShorts — шаг транскрипции (Whisper)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from videoshorts_core import (
    configure_stdio,
    extract_audio,
    prepend_nvidia_wheel_bins_to_path,
    segments_to_json,
    transcribe,
    write_srt,
)

configure_stdio()
prepend_nvidia_wheel_bins_to_path()


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: транскрипция видео через faster-whisper")
    parser.add_argument("video", type=Path, help="Входное видео")
    parser.add_argument("-o", "--output-dir", type=Path, default=None, help="Папка вывода (transcript.json, audio.wav, transcript.srt)")
    parser.add_argument("-m", "--model", default="base", choices=["tiny", "base", "small", "medium", "large", "turbo"])
    parser.add_argument("--force-cpu", action="store_true", help="Принудительно использовать CPU/int8 для Whisper")
    parser.add_argument("--word-timestamps", action=argparse.BooleanOptionalAction, default=True, help="Word timestamps для karaoke ASS")
    parser.add_argument("--language", default=None, help="Язык Whisper, например ru/en; по умолчанию auto")
    parser.add_argument("--beam-size", type=int, default=None, help="Beam size faster-whisper")
    args = parser.parse_args()

    if args.force_cpu:
        os.environ["VIDEOSHORTS_WHISPER_FORCE_CPU"] = "1"
    os.environ["VIDEOSHORTS_WHISPER_WORD_TIMESTAMPS"] = "1" if args.word_timestamps else "0"
    if args.language:
        os.environ["VIDEOSHORTS_WHISPER_LANGUAGE"] = args.language
    if args.beam_size is not None:
        os.environ["VIDEOSHORTS_WHISPER_BEAM_SIZE"] = str(args.beam_size)

    if not args.video.is_file():
        print(f"[ERROR] Video not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.output_dir or (Path("videoshorts-memory/transcripts") / args.video.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    audio_path = out_dir / "audio.wav"
    print(f"🔊 Extracting audio → {audio_path}")
    if not extract_audio(args.video, audio_path):
        print("[ERROR] Failed to extract audio", file=sys.stderr)
        sys.exit(1)

    print(f"🎤 Transcribing with Whisper ({args.model})...")
    segments, meta = transcribe(audio_path, args.model)
    payload = segments_to_json(segments, meta)
    json_path = out_dir / "transcript.json"
    srt_path = out_dir / "transcript.srt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(segments, srt_path)

    print(f"✅ Done: {len(segments)} segments")
    print(f"   JSON: {json_path}")
    print(f"   SRT:  {srt_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
