#!/usr/bin/env python3
"""VideoShorts — аудио-метрики и безопасная loudness-полировка."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
from pathlib import Path

from videoshorts_core import configure_stdio

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
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
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


def safe_audio_status(metrics: dict) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not metrics.get("stream", {}).get("has_audio"):
        issues.append("no_audio_stream")
    mean_volume = metrics.get("volumedetect", {}).get("mean_volume_db")
    max_volume = metrics.get("volumedetect", {}).get("max_volume_db")
    if mean_volume is not None and mean_volume < -32:
        issues.append("audio_too_quiet")
    if max_volume is not None and max_volume > -0.2:
        issues.append("possible_clipping")
    return ("PASS" if not issues else "WARN", issues)


def polish_copy(src: Path, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "copy",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "aac",
        str(dest),
    ]
    return _run(cmd).returncode == 0 and dest.is_file() and dest.stat().st_size > 0


def _candidate_clips(clips_dir: Path) -> list[Path]:
    """Prefer keep clips from manifest (cropped), then newer cropped, else finals.

    After cutter, folder often has stale clip_NN.mp4 from a previous full run
    alongside fresh clip_NN_cropped.mp4 — measuring stale finals is wrong.
    """
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
        if "_cropped" not in p.name and "_polished" not in p.name
    )
    if cropped and finals:
        newest_cropped = max(p.stat().st_mtime for p in cropped)
        newest_final = max(p.stat().st_mtime for p in finals)
        if newest_cropped >= newest_final:
            return cropped
    return finals or cropped


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: audio metrics and optional loudnorm copies")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--write-polished", action="store_true", help="Создать *_polished.mp4 копии через loudnorm")
    parser.add_argument("-o", "--metrics", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()

    if not args.clips_dir.is_dir():
        print(f"[ERROR] clips_dir not found: {args.clips_dir}", file=sys.stderr)
        sys.exit(1)

    clips = _candidate_clips(args.clips_dir)
    entries: list[dict] = []
    polished: list[dict] = []
    for clip in clips:
        metric = {
            "file": clip.name,
            "stream": probe_audio_stream(clip),
            "volumedetect": volumedetect(clip),
            "loudnorm_first_pass": loudnorm_measure(clip),
        }
        status, issues = safe_audio_status(metric)
        metric["status"] = status
        metric["issues"] = issues
        if args.write_polished and metric["stream"].get("has_audio"):
            dest = args.clips_dir / f"{clip.stem}_polished.mp4"
            ok = polish_copy(clip, dest)
            polished.append({"source": clip.name, "file": dest.name, "ok": ok})
            metric["polished_file"] = dest.name if ok else None
        entries.append(metric)

    failed = [item for item in entries if item.get("status") != "PASS"]
    payload = {
        "schema_version": 1,
        "clips_dir": str(args.clips_dir.resolve()),
        "status": "PASS" if not failed else "WARN",
        "clips": entries,
        "summary": {
            "total": len(entries),
            "pass": len(entries) - len(failed),
            "warn": len(failed),
        },
    }
    manifest = {
        "schema_version": 1,
        "mode": "metrics_only" if not args.write_polished else "metrics_and_polished_copies",
        "clips_dir": str(args.clips_dir.resolve()),
        "polished": polished,
        "audio_metrics": args.metrics.name if args.metrics else "audio-metrics.json",
        "note": "По умолчанию оригинальные клипы не заменяются. *_polished.mp4 создаются только с --write-polished.",
    }
    metrics_path = args.metrics or (args.clips_dir / "audio-metrics.json")
    manifest_path = args.manifest or (args.clips_dir / "audio-polish-manifest.json")
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Audio metrics: {metrics_path}")
    print(f"✅ Audio manifest: {manifest_path}")
    print(f"   status={payload['status']} pass={payload['summary']['pass']}/{payload['summary']['total']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
