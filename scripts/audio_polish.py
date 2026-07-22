#!/usr/bin/env python3
"""VideoShorts — аудио-метрики и loudnorm в финальные/cropped клипы."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
from pathlib import Path

from quality_presets import LOUDNORM_I, LOUDNORM_LRA, LOUDNORM_TP, audio_encode_args, loudnorm_filter
from videoshorts_core import configure_stdio, find_ffmpeg

configure_stdio()


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe_audio_stream(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,channels,sample_rate:format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        r = _run(cmd)
        if r.returncode != 0:
            return {"has_audio": False, "error": r.stderr.strip()}
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams") or []
        fmt = data.get("format") or {}
        return {
            "has_audio": bool(streams),
            "codec": streams[0].get("codec_name") if streams else None,
            "channels": int(streams[0].get("channels", 0)) if streams else None,
            "sample_rate": int(streams[0].get("sample_rate", 0)) if streams and str(streams[0].get("sample_rate", "")).isdigit() else None,
            "duration": float(fmt.get("duration", 0) or 0),
        }
    except Exception as error:
        return {"has_audio": False, "error": str(error)}


def volumedetect(path: Path) -> dict:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"]
    r = _run(cmd)
    text = "\n".join([r.stdout or "", r.stderr or ""])
    mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", text)
    maxv = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", text)
    return {
        "returncode": r.returncode,
        "mean_volume_db": float(mean.group(1)) if mean else None,
        "max_volume_db": float(maxv.group(1)) if maxv else None,
        "raw_tail": "\n".join(text.splitlines()[-12:]),
    }


def loudnorm_measure(path: Path) -> dict:
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json",
        "-f", "null", "-",
    ]
    r = _run(cmd)
    text = "\n".join([r.stdout or "", r.stderr or ""])
    start = text.rfind("{")
    end = text.rfind("}")
    payload = {}
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start:end + 1])
        except Exception:
            payload = {}
    payload["returncode"] = r.returncode
    return payload


def safe_audio_status(metrics: dict, *, after_loudnorm: bool = False) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not metrics.get("stream", {}).get("has_audio"):
        issues.append("no_audio_stream")
    mean_volume = metrics.get("volumedetect", {}).get("mean_volume_db")
    max_volume = metrics.get("volumedetect", {}).get("max_volume_db")
    quiet_threshold = -28 if after_loudnorm else -24
    if mean_volume is not None and mean_volume < quiet_threshold:
        issues.append("audio_too_quiet")
    if max_volume is not None and max_volume > -1.0:
        issues.append("possible_clipping")
    return ("PASS" if not issues else "WARN", issues)


def apply_loudnorm_inplace(src: Path, measured: dict | None = None, quality_preset: str = "release") -> bool:
    """Rewrite video with two-pass loudnorm audio; video stream copied."""
    ffmpeg = find_ffmpeg()
    tmp = src.with_name(f"{src.stem}.loudnorm_tmp{src.suffix}")
    af = loudnorm_filter(measured)
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-c:v", "copy",
        "-af", af,
        *audio_encode_args(quality_preset),
        str(tmp),
    ]
    ok = _run(cmd).returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0
    if not ok:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(src)
    return True


def _candidate_clips(clips_dir: Path) -> list[Path]:
    manifest_path = clips_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            names: list[str] = []
            for item in data.get("clips") or []:
                if item.get("ok") is False:
                    continue
                for key in ("cropped_file", "file", "final_file"):
                    name = item.get(key)
                    if name and (clips_dir / name).is_file():
                        names.append(name)
                        break
            if names:
                return [clips_dir / name for name in names]
        except Exception:
            pass

    cropped = sorted(clips_dir.glob("clip_*_cropped.mp4"))
    finals = sorted(
        p for p in clips_dir.glob("clip_*.mp4")
        if "_cropped" not in p.name and "_polished" not in p.name and "_broll" not in p.name
    )
    if cropped and finals:
        newest_cropped = max(p.stat().st_mtime for p in cropped)
        newest_final = max(p.stat().st_mtime for p in finals)
        if newest_cropped >= newest_final:
            return cropped
    return cropped or finals


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: audio metrics and loudnorm")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument(
        "--apply-loudnorm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Применить two-pass loudnorm к cropped/final клипам (default: on)",
    )
    parser.add_argument("--write-polished", action="store_true", help="Alias: --apply-loudnorm")
    parser.add_argument("--metrics-only", action="store_true", help="Только метрики, без изменения MP4")
    parser.add_argument("--quality-preset", default="release", choices=["draft", "release"])
    parser.add_argument("-o", "--metrics", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()

    apply = args.apply_loudnorm or args.write_polished
    if args.metrics_only:
        apply = False

    if not args.clips_dir.is_dir():
        print(f"[ERROR] clips_dir not found: {args.clips_dir}", file=sys.stderr)
        sys.exit(1)

    clips = _candidate_clips(args.clips_dir)
    entries: list[dict] = []
    applied: list[dict] = []
    for clip in clips:
        measured = loudnorm_measure(clip) if clip.stat().st_size > 0 else {}
        applied_ok = False
        if apply and probe_audio_stream(clip).get("has_audio"):
            applied_ok = apply_loudnorm_inplace(clip, measured, quality_preset=args.quality_preset)
            applied.append({"file": clip.name, "ok": applied_ok, "two_pass": bool(measured.get("input_i"))})

        metric = {
            "file": clip.name,
            "stream": probe_audio_stream(clip),
            "volumedetect": volumedetect(clip),
            "loudnorm_first_pass": measured,
            "loudnorm_applied": applied_ok if apply else False,
            "loudnorm_target": {"I": LOUDNORM_I, "TP": LOUDNORM_TP, "LRA": LOUDNORM_LRA},
        }
        status, issues = safe_audio_status(metric, after_loudnorm=bool(apply and applied_ok))
        if apply and not applied_ok and metric["stream"].get("has_audio"):
            issues.append("loudnorm_apply_failed")
            status = "WARN"
        metric["status"] = status
        metric["issues"] = issues
        entries.append(metric)

    failed = [item for item in entries if item.get("status") != "PASS"]
    payload = {
        "schema_version": 2,
        "clips_dir": str(args.clips_dir.resolve()),
        "status": "PASS" if not failed else "WARN",
        "clips": entries,
        "summary": {
            "total": len(entries),
            "pass": len(entries) - len(failed),
            "warn": len(failed),
            "loudnorm_applied": sum(1 for item in applied if item.get("ok")),
        },
    }
    manifest = {
        "schema_version": 2,
        "mode": "metrics_only" if not apply else "loudnorm_applied_inplace",
        "clips_dir": str(args.clips_dir.resolve()),
        "quality_preset": args.quality_preset,
        "applied": applied,
        "audio_metrics": args.metrics.name if args.metrics else "audio-metrics.json",
        "note": "По умолчанию two-pass loudnorm применяется к cropped/final клипам (I=-14 LUFS).",
    }
    metrics_path = args.metrics or (args.clips_dir / "audio-metrics.json")
    manifest_path = args.manifest or (args.clips_dir / "audio-polish-manifest.json")
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Audio metrics: {metrics_path}")
    print(f"✅ Audio manifest: {manifest_path}")
    print(
        f"   status={payload['status']} pass={payload['summary']['pass']}/{payload['summary']['total']} "
        f"loudnorm={payload['summary']['loudnorm_applied']}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
