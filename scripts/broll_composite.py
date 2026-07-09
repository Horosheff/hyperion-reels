#!/usr/bin/env python3
"""Встраивает подготовленные 9:16 B-roll assets на весь кадр webinar-клипа."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from videoshorts_core import configure_stdio, find_ffmpeg

configure_stdio()


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default
    except (OSError, json.JSONDecodeError):
        return default


def build_overlay_command(source: Path, asset: Path, output: Path, start: float, duration: float) -> list[str]:
    """Возвращает команду без shell: звук и длительность базового ролика не меняются."""
    end = start + duration
    vf = (
        "[1:v]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,setsar=1[broll];"
        f"[0:v][broll]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v]"
    )
    return [
        find_ffmpeg(), "-y", "-i", str(source), "-stream_loop", "-1", "-i", str(asset),
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
        "-preset", "fast", "-crf", "23", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(output),
    ]


def composite(clips_dir: Path, plan: dict, *, dry_run: bool = False) -> dict:
    assets_dir = clips_dir / "broll-assets"
    report = {"schema_version": 1, "artifact": "broll-report", "status": "PASS", "clips": [], "dry_run": dry_run}
    for insert in plan.get("inserts", []):
        if not isinstance(insert, dict) or insert.get("status") != "READY":
            continue
        idx = int(insert["clip_index"])
        source = clips_dir / f"clip_{idx:02d}_cropped.mp4"
        asset = assets_dir / str(insert["asset_file"])
        output = clips_dir / f"clip_{idx:02d}_broll.mp4"
        entry = {
            "clip_index": idx,
            "source": str(source),
            "asset": str(asset),
            "output": str(output),
            "placement": str(insert.get("placement") or "fullscreen_9_16"),
        }
        start = float(insert.get("at_sec", 0))
        duration = float(insert.get("duration_sec", 0))
        entry["timing_sec"] = {"start": start, "end": start + duration, "duration": duration}
        if not source.is_file() or not asset.is_file() or not (0 <= start and 1.0 <= duration <= 3.0):
            entry.update({"status": "FAIL", "reason": "missing_source_or_asset_or_invalid_timing"})
            report["status"] = "PARTIAL"
        elif dry_run:
            entry.update({"status": "DRY_RUN", "command": build_overlay_command(source, asset, output, start, duration)})
        else:
            result = subprocess.run(build_overlay_command(source, asset, output, start, duration), capture_output=True)
            if result.returncode == 0 and output.is_file() and output.stat().st_size > 0:
                entry["status"] = "PASS"
            else:
                entry.update({"status": "FAIL", "reason": "ffmpeg_composite_failed"})
                report["status"] = "PARTIAL"
        report["clips"].append(entry)
    if not report["clips"]:
        report.update({"status": "SKIPPED", "reason": "no_ready_broll_inserts"})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: B-roll compositor")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = composite(args.clips_dir, read_json(args.plan, {"inserts": []}), dry_run=args.dry_run)
    target = args.clips_dir / "broll-report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"B-roll: {report['status']} ({len(report['clips'])} inserts) → {target}")
    sys.exit(0 if report["status"] in {"PASS", "SKIPPED"} else 1)


if __name__ == "__main__":
    main()
