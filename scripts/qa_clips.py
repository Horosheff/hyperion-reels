#!/usr/bin/env python3
"""VideoShorts — QA готовых клипов."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from videoshorts_core import configure_stdio, write_latest_results
from agent_gate import agent_mode_enabled, evaluate_agent_decisions, evaluate_uniform_durations, gate_message
from safe_zones import get_safe_zone, safe_zone_enabled
import json_store
import re
import vs_logging

configure_stdio()

_log = vs_logging.get_logger("qa_clips")


def append_open_incident(clips_dir: Path, issues: list[str]) -> Path:
    root = Path(__file__).resolve().parents[1]
    queue = root / "videoshorts-memory" / "pipeline-fix-queue.md"
    queue.parent.mkdir(parents=True, exist_ok=True)
    incident_id = f"INC-{datetime.now().strftime('%Y%m%d-%H%M')}-guardian-qa-fail"
    with json_store.file_lock(queue):
        existing = queue.read_text(encoding="utf-8") if queue.is_file() else "# VideoShorts pipeline fix queue\n"
        if incident_id in existing:
            return queue
        block = [
            "",
            f"## {incident_id}",
            "- status: open",
            "- step: guardian",
            f"- clips_dir: {clips_dir}",
            f"- summary: QA failed for {len(issues)} issue(s)",
            "- issues:",
            *[f"  - {issue}" for issue in issues[:20]],
            "",
        ]
        json_store.write_text_atomic(queue, existing.rstrip() + "\n" + "\n".join(block))
    return queue


def probe_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return float(r.stdout.strip())
    except Exception:
        pass
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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and "x" in r.stdout:
            w, h = r.stdout.strip().split("x")
            return int(w), int(h)
    except Exception:
        pass
    return None


def probe_audio(path: Path) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and "audio" in r.stdout
    except Exception:
        return False


def read_json(path: Path, default):
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def decision_evidence_status(clips_dir: Path) -> dict:
    return evaluate_agent_decisions(require_agent=agent_mode_enabled())


def audio_metrics_by_file(clips_dir: Path) -> dict[str, dict]:
    data = read_json(clips_dir / "audio-metrics.json", {"clips": []})
    return {
        str(item.get("file")): item
        for item in data.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(data, dict) else {}


_ASS_STYLE_RE = re.compile(r"^Style:\s*Default,.*$", re.M)


def subtitle_safe_zone_violations(ass_path: Path, width: int, height: int) -> list[str]:
    """Проверяет MarginV/L/R в ASS против safe zone платформенного UI.

    MarginV меньше нижней небезопасной зоны → субтитры уедут под
    название/описание после публикации (лайки справа — MarginR).
    """
    if not safe_zone_enabled() or not ass_path.is_file():
        return []
    try:
        text = ass_path.read_text(encoding="utf-8-sig")
    except Exception:
        return []
    style = _ASS_STYLE_RE.search(text or "")
    if not style:
        return []
    fields = style.group(0).split(",")
    if len(fields) < 22:
        return []
    warnings: list[str] = []
    try:
        play_res_y = int(re.search(r"^PlayResY:\s*(\d+)", text, re.M).group(1)) if re.search(r"^PlayResY:\s*(\d+)", text, re.M) else height
        scale = height / play_res_y if play_res_y else 1.0
        margin_l = int(fields[19]) * scale
        margin_r = int(fields[20]) * scale
        margin_v = int(fields[21]) * scale
        alignment = int(fields[18])
    except (ValueError, IndexError):
        return ["subtitle_style_unparsed"]
    zone = get_safe_zone(width, height)
    if alignment in (1, 2, 3) and margin_v < zone.bottom:
        warnings.append(f"subtitle_margin_v_in_unsafe_zone({int(margin_v)}<{zone.bottom})")
    if alignment in (4, 5, 6) and margin_v < zone.top:
        warnings.append(f"subtitle_margin_v_in_top_zone({int(margin_v)}<{zone.top})")
    if margin_l < zone.left:
        warnings.append(f"subtitle_margin_l_in_unsafe_zone({int(margin_l)}<{zone.left})")
    if margin_r < zone.right:
        warnings.append(f"subtitle_margin_r_in_unsafe_zone({int(margin_r)}<{zone.right})")
    return warnings


def safe_zone_check(clip_name: str, resolution: tuple[int, int] | None, has_subtitles: bool, ass_path: Path | None = None) -> dict:
    warnings: list[str] = []
    if resolution:
        width, height = resolution
        if height <= width:
            warnings.append("not_vertical_canvas")
        elif ass_path is not None:
            warnings.extend(subtitle_safe_zone_violations(ass_path, width, height))
        if width < 540 or height < 960:
            warnings.append("low_resolution_for_readability")
    else:
        warnings.append("resolution_unknown")
    if not has_subtitles:
        warnings.append("subtitles_missing_or_not_detected")
    return {
        "file": clip_name,
        "status": "PASS" if not warnings else "WARN",
        "warnings": warnings,
        "heuristics": {
            "safe_zone_bottom_pct": 19.5,
            "safe_zone_top_pct": 10.5,
            "safe_zone_left_pct": 5.0,
            "safe_zone_right_pct": 18.0,
            "readability_min_width": 540,
            "note": "ASS MarginV/L/R сверяются с safe zone UI платформ (scripts/safe_zones.py).",
        },
    }


def write_aux_reports(clips_dir: Path, results: list[dict], audio_by_file: dict[str, dict]) -> tuple[dict, dict]:
    safe_zone = {"schema_version": 1, "clips": [], "status": "PASS"}
    audio_qa = {"schema_version": 1, "clips": [], "status": "PASS"}
    subtitles_dir = clips_dir / "subtitles"
    for item in results:
        file_name = str(item.get("file"))
        idx = file_name.replace("clip_", "").replace("_cropped.mp4", "").replace(".mp4", "")
        ass_path = subtitles_dir / f"clip_{idx}.ass"
        has_subtitles = ass_path.is_file() or (subtitles_dir / f"clip_{idx}.srt").is_file()
        safe_item = safe_zone_check(
            file_name,
            tuple(item["resolution"]) if isinstance(item.get("resolution"), list) else item.get("resolution"),
            has_subtitles,
            ass_path=ass_path,
        )
        safe_zone["clips"].append(safe_item)
        if safe_item["status"] != "PASS":
            safe_zone["status"] = "WARN"

        metric = audio_by_file.get(file_name) or {}
        audio_warnings = list(metric.get("issues") or [])
        if not item.get("has_audio"):
            audio_warnings.append("no_audio_stream")
        audio_item = {
            "file": file_name,
            "status": "PASS" if not audio_warnings else "WARN",
            "warnings": sorted(set(audio_warnings)),
            "metrics": metric,
        }
        audio_qa["clips"].append(audio_item)
        if audio_item["status"] != "PASS":
            audio_qa["status"] = "WARN"

    (clips_dir / "safe-zone-report.json").write_text(json.dumps(safe_zone, ensure_ascii=False, indent=2), encoding="utf-8")
    (clips_dir / "audio-qa-report.json").write_text(json.dumps(audio_qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return safe_zone, audio_qa


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: QA клипов")
    parser.add_argument("clips_dir", type=Path, help="Папка с clip_XX.mp4")
    parser.add_argument("--min", type=float, default=30)
    parser.add_argument("--max", type=float, default=60)
    parser.add_argument("-o", "--report", type=Path, default=None)
    parser.add_argument(
        "--require-agent-decisions",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="FAIL если decisions = local_heuristic_draft (default: on in Agent mode)",
    )
    args = parser.parse_args()

    # Keep generated composites as internal intermediates: only publishable finals
    # participate in Guardian counts and safe-zone checks.
    clips = sorted(
        p for p in args.clips_dir.glob("clip_*.mp4")
        if "_cropped" not in p.name and "_broll" not in p.name
    )
    if not clips:
        clips = sorted(args.clips_dir.glob("clip_*_cropped.mp4"))
    if not clips:
        print(f"[ERROR] No clips in {args.clips_dir}", file=sys.stderr)
        sys.exit(1)

    issues = []
    results = []
    audio_by_file = audio_metrics_by_file(args.clips_dir)
    broll_report = read_json(args.clips_dir / "broll-report.json", {})
    require_agent = agent_mode_enabled(args.require_agent_decisions)
    decision_evidence = evaluate_agent_decisions(require_agent=require_agent)
    if require_agent and not decision_evidence.get("ok"):
        issues.append(gate_message(decision_evidence))
    elif not decision_evidence.get("exists") or not decision_evidence.get("total"):
        issues.append("clip decision evidence missing: videoshorts-memory/moments/clip-decisions.json")
    elif decision_evidence.get("missing_fields"):
        issues.append("clip decision evidence incomplete: " + ", ".join(decision_evidence["missing_fields"][:8]))
    if broll_report.get("status") == "PARTIAL":
        issues.append("b-roll composite is partial; inspect broll-report.json")
    for clip in clips:
        dur = probe_duration(clip)
        res = probe_resolution(clip)
        has_audio = probe_audio(clip)
        item_issues: list[str] = []
        item = {"file": clip.name, "duration": dur, "resolution": res, "has_audio": has_audio, "issues": item_issues}
        if dur is None:
            issue = f"{clip.name}: cannot read duration"
            issues.append(issue)
            item_issues.append(issue)
            item["ok"] = False
        elif dur < args.min - 2 or dur > args.max + 5:
            issue = f"{clip.name}: duration {dur:.1f}s out of range"
            issues.append(issue)
            item_issues.append(issue)
            item["ok"] = False
        elif res and (res[1] <= res[0]):
            issue = f"{clip.name}: not vertical {res[0]}x{res[1]}"
            issues.append(issue)
            item_issues.append(issue)
            item["ok"] = False
        elif not has_audio:
            issue = f"{clip.name}: no audio stream"
            issues.append(issue)
            item_issues.append(issue)
            item["ok"] = False
        else:
            item["ok"] = True
        metric = audio_by_file.get(clip.name) or {}
        if metric.get("loudnorm_applied") is False and any(
            x in (metric.get("issues") or []) for x in ("audio_too_quiet",)
        ):
            issue = f"{clip.name}: loudnorm not applied and audio too quiet"
            issues.append(issue)
            item_issues.append(issue)
            item["ok"] = False
        results.append(item)

    uniform = evaluate_uniform_durations(results, min_count=5, tolerance=2.0)
    if require_agent and uniform.get("uniform"):
        issues.append(
            f"uniform_algorithmic_durations: stddev={uniform.get('stddev')} "
            f"(все клипы почти одинаковой длины; похоже на draft 45s, не agent selection)"
        )

    safe_zone, audio_qa = write_aux_reports(args.clips_dir, results, audio_by_file)
    for safe_item in safe_zone.get("clips", []):
        for warning in safe_item.get("warnings", []):
            if warning in {"not_vertical_canvas", "low_resolution_for_readability"} or warning.startswith("subtitle_margin"):
                issues.append(f"{safe_item.get('file')}: safe-zone warning {warning}")
    for audio_item in audio_qa.get("clips", []):
        for warning in audio_item.get("warnings", []):
            if warning in {"no_audio_stream", "possible_clipping", "audio_too_quiet", "loudnorm_apply_failed"}:
                issues.append(f"{audio_item.get('file')}: audio warning {warning}")

    passed = sum(1 for r in results if r.get("ok"))
    status = "PASS" if passed == len(results) and not issues else "FAIL"
    report = {
        "schema_version": 3,
        "guardian": "v2",
        "status": status,
        "passed": passed,
        "total": len(results),
        "issues": issues,
        "clips": results,
        "decision_evidence": decision_evidence,
        "uniform_durations": uniform,
        "require_agent_decisions": require_agent,
        "safe_zone_report": str((args.clips_dir / "safe-zone-report.json").resolve()),
        "audio_qa_report": str((args.clips_dir / "audio-qa-report.json").resolve()),
        "broll_report": broll_report if isinstance(broll_report, dict) else {},
    }
    if status == "FAIL":
        report["incident_queue"] = str(append_open_incident(args.clips_dir, issues))

    report_path = args.report or (args.clips_dir / "qa-report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"QA: {status} ({passed}/{len(results)})")
    for issue in issues:
        print(f"   ❌ {issue}")
    print(f"   Report: {report_path}")
    latest_path = write_latest_results(args.clips_dir, status=status)
    print(f"   Latest results: {latest_path}")
    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    _log.info("start: %s", " ".join(sys.argv))
    try:
        main()
        _log.info("done")
    except SystemExit as exc:
        if exc.code not in (0, None):
            _log.error("exit code %s", exc.code)
        raise
    except Exception:
        _log.exception("fatal error")
        raise
