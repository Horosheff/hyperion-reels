#!/usr/bin/env python3
"""VideoShorts — вшивание ASS/SRT в MP4 (как shorts_service _burn_subtitles)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from videoshorts_core import configure_stdio, find_ffmpeg

configure_stdio()


def _escape_filter_path(path: Path) -> str:
    p = str(path.resolve())
    if os.name == "nt":
        p = p.replace("\\", "/").replace(":", "\\:")
    return p.replace("'", r"\'")


def probe_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        return None
    return None


def probe_resolution(path: Path) -> tuple[int, int] | None:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and "x" in result.stdout:
            w, h = result.stdout.strip().split("x", 1)
            return int(w), int(h)
    except Exception:
        return None
    return None


def get_progress_bar_filter(
    duration: float,
    width: int,
    height: int,
    bar_height: int = 12,
    color: str = "#FF0000",
    bg_color: str = "#FFFF00",
    position: str = "bottom",
) -> str:
    color = "0x" + color.lstrip("#")
    bg_color = "0x" + bg_color.lstrip("#")
    y = 0 if position == "top" else max(0, height - bar_height)
    return (
        f"drawbox=x=0:y={y}:w={width}:h={bar_height}:color={bg_color}:t=fill,"
        f"drawbox=x=0:y={y}:w='min({width},t/{max(duration, 0.001):.3f}*{width})':"
        f"h={bar_height}:color={color}:t=fill"
    )


TRIGGER_WORDS = {
    "невероятно", "шок", "важно", "внимание", "смотрите", "вау", "огонь",
    "срочно", "главное", "секрет", "incredible", "amazing", "shocking",
    "important", "attention", "wow", "crazy", "secret", "breaking",
}


def load_words_for_clip(transcript: Path | None, clip_start: float, clip_end: float) -> list[dict]:
    if not transcript or not transcript.is_file():
        return []
    data = json.loads(transcript.read_text(encoding="utf-8-sig"))
    words = data.get("words")
    if not isinstance(words, list):
        for seg in data.get("segments", []):
            if isinstance(seg.get("_words"), list):
                words = seg["_words"]
                break
    if not isinstance(words, list):
        return []
    return [
        w for w in words
        if float(w.get("end", 0)) > clip_start and float(w.get("start", 0)) < clip_end
    ]


def detect_first_zoom_time(words: list[dict], clip_start: float) -> float | None:
    for word in words:
        text = str(word.get("word", "")).strip()
        clean = "".join(ch for ch in text.lower() if ch.isalnum() or ch in ("_", "-"))
        if "!" in text or clean in TRIGGER_WORDS or (len(text) > 2 and text.isupper()):
            return max(0.0, float(word.get("start", 0)) - clip_start)
    return None


def get_zoom_filter(start_time: float, width: int, height: int, fps: float = 30.0, intensity: float = 1.12, duration: float = 0.35) -> str:
    start_frame = max(0, int(start_time * fps))
    frames = max(1, int(duration * fps))
    z_expr = f"if(between(on,{start_frame},{start_frame + frames}),1+{intensity - 1:.4f}*sin((on-{start_frame})/{frames}*PI),1)"
    return f"zoompan=z='{z_expr}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*0.4':d=1:s={width}x{height}:fps={fps}"


def apply_video_filter(input_mp4: Path, output_mp4: Path, vf: str) -> bool:
    ffmpeg = find_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-i", str(input_mp4),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and output_mp4.is_file()


def burn_subtitles(input_mp4: Path, sub_path: Path, output_mp4: Path, font_size: int = 42, margin_v: int = 80) -> bool:
    ffmpeg = find_ffmpeg()
    is_ass = sub_path.suffix.lower() == ".ass"
    temp_sub: Path | None = None
    sub_file = sub_path

    if os.name == "nt":
        try:
            fd, tmp = tempfile.mkstemp(prefix="videoshorts_sub_", suffix=sub_path.suffix)
            os.close(fd)
            temp_sub = Path(tmp)
            shutil.copy2(sub_path, temp_sub)
            sub_file = temp_sub
        except Exception:
            sub_file = sub_path

    sub_escaped = _escape_filter_path(sub_file)
    if is_ass:
        vf = f"ass='{sub_escaped}'"
    else:
        style = (
            f"FontName=Arial,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV={margin_v}"
        )
        vf = f"subtitles='{sub_escaped}':force_style='{style}'"

    cmd = [
        ffmpeg, "-y", "-i", str(input_mp4),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if temp_sub and temp_sub.exists():
        temp_sub.unlink(missing_ok=True)
    return result.returncode == 0 and output_mp4.is_file()


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: burn subtitles into clips")
    parser.add_argument("clips_dir", type=Path, help="output/clips/<stem>")
    parser.add_argument("--suffix", default="_cropped", help="input suffix before .mp4 (default _cropped)")
    parser.add_argument("--progress-bar", action="store_true", help="Add post-burn progress bar")
    parser.add_argument("--progress-position", choices=("top", "bottom"), default="bottom")
    parser.add_argument("--progress-color", default="#FF0000")
    parser.add_argument("--progress-bg-color", default="#FFFF00")
    parser.add_argument("--progress-height", type=int, default=12)
    parser.add_argument("--zoom-punch", action="store_true", help="Add one punch-in zoom at first trigger word")
    parser.add_argument("--transcript", type=Path, default=None, help="transcript.json for zoom trigger words")
    parser.add_argument("--moments", type=Path, default=None, help="moments.json for clip start/end")
    parser.add_argument("--workers", type=int, default=1, help="Параллельных рендеров (render_workers)")
    args = parser.parse_args()

    clips_dir = args.clips_dir
    sub_dir = clips_dir / "subtitles"
    if not clips_dir.is_dir():
        print(f"[ERROR] Not a directory: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    moments = {}
    keep_indexes: set[str] | None = None
    if args.moments and args.moments.is_file():
        data = json.loads(args.moments.read_text(encoding="utf-8-sig"))
        for pos, clip in enumerate(data.get("clips", []), 1):
            idx = int(clip.get("index") or pos)
            key = f"{idx:02d}"
            moments[key] = (float(clip.get("start", 0)), float(clip.get("end", 0)))
            if keep_indexes is None:
                keep_indexes = set()
            keep_indexes.add(key)

    # Prefer subtitles-manifest / cutter manifest keep list over glob-all cropped
    sub_manifest = clips_dir / "subtitles-manifest.json"
    if sub_manifest.is_file():
        try:
            sm = json.loads(sub_manifest.read_text(encoding="utf-8-sig"))
            sm_idxs = {
                f"{int(c.get('index')):02d}"
                for c in sm.get("clips", [])
                if isinstance(c, dict) and c.get("index") is not None
            }
            if sm_idxs:
                keep_indexes = sm_idxs
        except Exception:
            pass
    cutter_manifest = clips_dir / "manifest.json"
    if keep_indexes is None and cutter_manifest.is_file():
        try:
            cm = json.loads(cutter_manifest.read_text(encoding="utf-8-sig"))
            cm_idxs = set()
            for c in cm.get("clips", []) if isinstance(cm, dict) else []:
                if not isinstance(c, dict) or c.get("ok") is False:
                    continue
                name = str(c.get("cropped_file") or c.get("file") or "")
                m = re.search(r"clip_(\d+)", name)
                if m:
                    cm_idxs.add(f"{int(m.group(1)):02d}")
                elif c.get("index") is not None:
                    cm_idxs.add(f"{int(c['index']):02d}")
            if cm_idxs:
                keep_indexes = cm_idxs
        except Exception:
            pass

    workers = max(1, args.workers)
    cropped_files = sorted(clips_dir.glob(f"clip_*{args.suffix}.mp4"))
    if keep_indexes is not None:
        filtered = []
        for cropped in cropped_files:
            idx = cropped.stem.replace("clip_", "").replace(args.suffix, "")
            if idx in keep_indexes:
                filtered.append(cropped)
        skipped = len(cropped_files) - len(filtered)
        if skipped:
            print(f"   [info] skip {skipped} stale cropped not in keep/manifest")
        cropped_files = filtered
    print(f"🔥 Burning subtitles into {len(cropped_files)} clip(s) (workers={workers})")

    def burn_one(cropped: Path) -> bool:
        idx = cropped.stem.replace("clip_", "").replace(args.suffix, "")
        broll_source = clips_dir / f"clip_{idx}_broll.mp4"
        source = broll_source if broll_source.is_file() else cropped
        ass = sub_dir / f"clip_{idx}.ass"
        srt = sub_dir / f"clip_{idx}.srt"
        sub = ass if ass.is_file() else srt
        if not sub.is_file():
            print(f"   [WARN] No subtitles for {cropped.name}", file=sys.stderr)
            return False
        out = clips_dir / f"clip_{idx}.mp4"
        print(f"   burn: {source.name} + {sub.name} → {out.name}")
        if not burn_subtitles(source, sub, out):
            print(f"   [WARN] Burn failed: {source.name}", file=sys.stderr)
            return False
        processed = out
        if args.zoom_punch:
            start, end = moments.get(idx, (0.0, probe_duration(processed) or 0.0))
            words = load_words_for_clip(args.transcript, start, end)
            zoom_time = detect_first_zoom_time(words, start)
            res = probe_resolution(processed) or (720, 1280)
            if zoom_time is not None:
                zoom_out = clips_dir / f"clip_{idx}_zoomtmp.mp4"
                if apply_video_filter(processed, zoom_out, get_zoom_filter(zoom_time, res[0], res[1])):
                    shutil.move(str(zoom_out), str(processed))
                elif zoom_out.exists():
                    zoom_out.unlink(missing_ok=True)
        if args.progress_bar:
            duration = probe_duration(processed) or max(0.001, moments.get(idx, (0, 0))[1] - moments.get(idx, (0, 0))[0])
            res = probe_resolution(processed) or (720, 1280)
            progress_out = clips_dir / f"clip_{idx}_progresstmp.mp4"
            vf = get_progress_bar_filter(
                duration,
                res[0],
                res[1],
                args.progress_height,
                args.progress_color,
                args.progress_bg_color,
                args.progress_position,
            )
            if apply_video_filter(processed, progress_out, vf):
                shutil.move(str(progress_out), str(processed))
            elif progress_out.exists():
                progress_out.unlink(missing_ok=True)
        return True

    ok = 0
    if workers == 1:
        for cropped in cropped_files:
            if burn_one(cropped):
                ok += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(burn_one, c): c for c in cropped_files}
            for fut in as_completed(futures):
                if fut.result():
                    ok += 1

    print(f"✅ Burned subtitles into {ok} clip(s)")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
