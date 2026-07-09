#!/usr/bin/env python3
"""
Общая логика VideoShorts — порт из shorts/webinar_cutter/webinar_cutter.py
Транскрипция, выбор моментов, dual-screen рендер 9:16.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent
_PLUGIN_ROOT = _ROOT.parent
_TRANSCRIBE_WORKER = _ROOT / "transcribe_worker.py"


def configure_stdio() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _read_json(path: Path, default: dict | list | None = None) -> dict | list:
    if not path.is_file():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _resolve_existing(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)


def _open_folder_command(path: Path) -> str:
    resolved = _resolve_existing(path)
    if sys.platform == "win32":
        return f'explorer "{resolved}"'
    if sys.platform == "darwin":
        return f'open "{resolved}"'
    return f'xdg-open "{resolved}"'


def _clip_index_from_name(name: str) -> str:
    stem = Path(name).stem
    return (
        stem.replace("clip_", "")
        .replace("_cropped", "")
        .replace("_final", "")
    )


def build_latest_results(
    clips_dir: Path,
    *,
    source_video: Path | None = None,
    settings: dict | None = None,
    status: str | None = None,
    publish_dir: Path | None = None,
    run_command: str | None = None,
) -> dict:
    """Собирает лёгкий индекс результатов без чтения MP4 в память."""
    clips_dir = clips_dir.resolve()
    memory_root = _PLUGIN_ROOT / "videoshorts-memory"
    manifest_path = clips_dir / "manifest.json"
    qa_report_path = clips_dir / "qa-report.json"
    subtitles_manifest_path = clips_dir / "subtitles-manifest.json"
    metadata_manifest_path = clips_dir / "metadata-manifest.json"
    transcript_dir = memory_root / "transcripts" / clips_dir.name
    cleanup_plan_path = transcript_dir / "cleanup-plan.json"
    filler_plan_path = transcript_dir / "filler-removal-plan.json"
    candidate_moments_path = memory_root / "moments" / "candidate-moments.json"
    scores_path = memory_root / "moments" / "clip-scores.json"
    editor_review_path = memory_root / "moments" / "editor-review.json"
    virality_review_path = memory_root / "moments" / "virality-review.json"
    refined_moments_path = memory_root / "moments" / "refined-moments.json"
    dramaturgy_report_path = memory_root / "moments" / "dramaturgy-report.json"
    montage_plan_path = memory_root / "moments" / "montage-plan.json"
    clip_decisions_path = memory_root / "moments" / "clip-decisions.json"
    audio_metrics_path = clips_dir / "audio-metrics.json"
    audio_manifest_path = clips_dir / "audio-polish-manifest.json"
    safe_zone_report_path = clips_dir / "safe-zone-report.json"
    audio_qa_report_path = clips_dir / "audio-qa-report.json"
    post_render_review_path = clips_dir / "post-render-review.json"
    broll_plan_path = clips_dir / "broll-plan.json"
    broll_report_path = clips_dir / "broll-report.json"
    retry_plan_path = clips_dir / "retry-plan.json"
    run_state_path = memory_root / "output" / "run-state.json"
    publish_dir = (publish_dir or (clips_dir.parent / f"{clips_dir.name}-publish")).resolve()
    publish_manifest_path = publish_dir / "publish-manifest.json"

    manifest = _read_json(manifest_path, {"clips": []})
    qa_report = _read_json(qa_report_path, {})
    subtitles_manifest = _read_json(subtitles_manifest_path, {"clips": []})
    metadata_manifest = _read_json(metadata_manifest_path, {"clips": []})
    publish_manifest = _read_json(publish_manifest_path, {"clips": []})
    cleanup_plan = _read_json(cleanup_plan_path, {})
    filler_plan = _read_json(filler_plan_path, {})
    candidate_moments = _read_json(candidate_moments_path, {"candidates": []})
    scores_report = _read_json(scores_path, {"clips": []})
    editor_review = _read_json(editor_review_path, {"clips": []})
    virality_review = _read_json(virality_review_path, {"clips": []})
    dramaturgy_report = _read_json(dramaturgy_report_path, {"clips": []})
    montage_plan = _read_json(montage_plan_path, {"clips": []})
    clip_decisions = _read_json(clip_decisions_path, {"clips": []})
    audio_metrics = _read_json(audio_metrics_path, {"clips": []})
    safe_zone_report = _read_json(safe_zone_report_path, {"clips": []})
    audio_qa_report = _read_json(audio_qa_report_path, {"clips": []})
    post_render_review = _read_json(post_render_review_path, {"clips": []})
    broll_plan = _read_json(broll_plan_path, {"inserts": []})
    broll_report = _read_json(broll_report_path, {"clips": []})
    retry_plan = _read_json(retry_plan_path, {})
    run_state = _read_json(run_state_path, {})

    qa_by_file = {
        str(item.get("file")): item
        for item in qa_report.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(qa_report, dict) else {}
    subtitles_by_index = {
        str(item.get("index")): item
        for item in subtitles_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(subtitles_manifest, dict) else {}
    package_by_file = {
        str(item.get("file")): item
        for item in publish_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(publish_manifest, dict) else {}
    metadata_by_index = {
        str(item.get("index")): item
        for item in metadata_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(metadata_manifest, dict) else {}
    scores_by_index = {
        str(item.get("index")): item
        for item in scores_report.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(scores_report, dict) else {}
    decisions_by_index = {
        str(item.get("index")): item
        for item in clip_decisions.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(clip_decisions, dict) else {}
    candidates_by_id = {
        str(item.get("candidate_id")): item
        for item in candidate_moments.get("candidates", [])
        if isinstance(item, dict) and item.get("candidate_id")
    } if isinstance(candidate_moments, dict) else {}
    editor_by_index = {
        str(item.get("index")): item
        for item in editor_review.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(editor_review, dict) else {}
    virality_by_index = {
        str(item.get("index")): item
        for item in virality_review.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(virality_review, dict) else {}
    dramaturgy_by_index = {
        str(item.get("index")): item
        for item in dramaturgy_report.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(dramaturgy_report, dict) else {}
    montage_by_index = {
        str(item.get("index")): item
        for item in montage_plan.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(montage_plan, dict) else {}
    audio_by_file = {
        str(item.get("file")): item
        for item in audio_metrics.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(audio_metrics, dict) else {}
    safe_zone_by_file = {
        str(item.get("file")): item
        for item in safe_zone_report.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(safe_zone_report, dict) else {}
    audio_qa_by_file = {
        str(item.get("file")): item
        for item in audio_qa_report.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(audio_qa_report, dict) else {}
    post_render_by_index = {
        str(item.get("index")): item
        for item in post_render_review.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(post_render_review, dict) else {}
    retry_by_index = {
        str(item.get("index")): item
        for item in retry_plan.get("failed_clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(retry_plan, dict) else {}
    broll_by_index = {
        str(item.get("clip_index")): item
        for item in broll_plan.get("inserts", [])
        if isinstance(item, dict) and item.get("clip_index") is not None
    } if isinstance(broll_plan, dict) else {}

    clips: list[dict] = []
    manifest_clips = manifest.get("clips", []) if isinstance(manifest, dict) else []
    for i, clip in enumerate(manifest_clips, 1):
        if not isinstance(clip, dict):
            continue
        final_file = str(clip.get("final_file") or "")
        cropped_file = str(clip.get("cropped_file") or clip.get("file") or "")
        file_name = final_file if final_file and (clips_dir / final_file).is_file() else cropped_file
        if not file_name:
            continue

        idx = str(clip.get("index") or _clip_index_from_name(file_name) or i)
        qa = qa_by_file.get(file_name) or qa_by_file.get(cropped_file) or {}
        packaged = package_by_file.get(file_name) or {}
        subtitles = subtitles_by_index.get(idx, {})
        metadata = metadata_by_index.get(idx, {})
        score_item = scores_by_index.get(idx, {})
        decision_item = decisions_by_index.get(idx, {})
        editor_item = editor_by_index.get(idx, {})
        candidate_item = candidates_by_id.get(str(editor_item.get("candidate_id"))) if editor_item else {}
        virality_item = virality_by_index.get(idx, {})
        dramaturgy_item = dramaturgy_by_index.get(idx, {})
        montage_item = montage_by_index.get(idx, {})
        audio_item = audio_by_file.get(file_name) or audio_by_file.get(cropped_file) or {}
        safe_zone_item = safe_zone_by_file.get(file_name) or safe_zone_by_file.get(cropped_file) or {}
        audio_qa_item = audio_qa_by_file.get(file_name) or audio_qa_by_file.get(cropped_file) or {}
        post_render_item = post_render_by_index.get(idx, {})
        retry_item = retry_by_index.get(idx, {})
        broll_item = broll_by_index.get(idx, {})
        ass_name = subtitles.get("ass") or packaged.get("ass")
        srt_name = subtitles.get("srt") or packaged.get("srt")

        clips.append({
            "index": int(idx) if idx.isdigit() else i,
            "file": file_name,
            "path": _resolve_existing(clips_dir / file_name),
            "publish_path": _resolve_existing(publish_dir / file_name) if (publish_dir / file_name).is_file() else None,
            "cropped_file": cropped_file or None,
            "final_file": final_file or None,
            "start": clip.get("start"),
            "end": clip.get("end"),
            "duration": qa.get("duration") or clip.get("duration"),
            "score": score_item.get("quality_score") or clip.get("score"),
            "reason": clip.get("reason"),
            "hook": clip.get("hook"),
            "payoff_ending": clip.get("payoff_ending"),
            "transcript_excerpt": clip.get("transcript_excerpt"),
            "semantic_boundary_evidence": clip.get("semantic_boundary_evidence") if isinstance(clip.get("semantic_boundary_evidence"), dict) else {},
            "scores": score_item or None,
            "candidate": candidate_item or None,
            "editor_review": editor_item or None,
            "virality_review": virality_item or None,
            "dramaturgy": dramaturgy_item or None,
            "montage_plan": montage_item or None,
            "decision": decision_item or None,
            "cleanup": {
                "summary": cleanup_plan.get("summary") if isinstance(cleanup_plan, dict) else None,
                "filler_items": len(filler_plan.get("items", [])) if isinstance(filler_plan, dict) else 0,
                "applied": decision_item.get("cleanup_applied") if decision_item else None,
                "silence_removed": decision_item.get("silence_removed") if decision_item else None,
                "fillers_removed": decision_item.get("fillers_removed") if decision_item else None,
                "glue_or_transition_notes": decision_item.get("glue_or_transition_notes") if decision_item else None,
                "review_items": decision_item.get("cleanup_review_items") if decision_item else None,
            },
            "audio": audio_item or None,
            "audio_qa": audio_qa_item or None,
            "safe_zone": safe_zone_item or None,
            "post_render_review": post_render_item or None,
            "retry": retry_item or None,
            "broll": broll_item or None,
            "metadata": metadata or None,
            "qa_ok": qa.get("ok"),
            "resolution": qa.get("resolution"),
            "has_audio": qa.get("has_audio"),
            "burned": packaged.get("burned") if packaged else bool(final_file and final_file == file_name and final_file != cropped_file),
            "subtitles": {
                "ass": _resolve_existing(clips_dir / "subtitles" / str(ass_name)) if ass_name else None,
                "srt": _resolve_existing(clips_dir / "subtitles" / str(srt_name)) if srt_name else None,
            },
        })

    qa_status = qa_report.get("status") if isinstance(qa_report, dict) else None
    package_ready = publish_manifest_path.is_file() and publish_dir.is_dir()
    effective_status = status or ("PASS" if qa_status == "PASS" and package_ready else qa_status or "PENDING")
    latest = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": effective_status,
        "source_video": _resolve_existing(source_video.resolve()) if source_video else None,
        "settings": settings or {},
        "clips_dir": _resolve_existing(clips_dir),
        "publish_dir": _resolve_existing(publish_dir) if publish_dir.is_dir() else None,
        "manifest_path": _resolve_existing(manifest_path) if manifest_path.is_file() else None,
        "qa_report_path": _resolve_existing(qa_report_path) if qa_report_path.is_file() else None,
        "subtitles_manifest_path": _resolve_existing(subtitles_manifest_path) if subtitles_manifest_path.is_file() else None,
        "metadata_manifest_path": _resolve_existing(metadata_manifest_path) if metadata_manifest_path.is_file() else None,
        "publish_manifest_path": _resolve_existing(publish_manifest_path) if publish_manifest_path.is_file() else None,
        "cleanup_plan_path": _resolve_existing(cleanup_plan_path) if cleanup_plan_path.is_file() else None,
        "filler_plan_path": _resolve_existing(filler_plan_path) if filler_plan_path.is_file() else None,
        "candidate_moments_path": _resolve_existing(candidate_moments_path) if candidate_moments_path.is_file() else None,
        "scores_path": _resolve_existing(scores_path) if scores_path.is_file() else None,
        "editor_review_path": _resolve_existing(editor_review_path) if editor_review_path.is_file() else None,
        "virality_review_path": _resolve_existing(virality_review_path) if virality_review_path.is_file() else None,
        "refined_moments_path": _resolve_existing(refined_moments_path) if refined_moments_path.is_file() else None,
        "dramaturgy_report_path": _resolve_existing(dramaturgy_report_path) if dramaturgy_report_path.is_file() else None,
        "montage_plan_path": _resolve_existing(montage_plan_path) if montage_plan_path.is_file() else None,
        "clip_decisions_path": _resolve_existing(clip_decisions_path) if clip_decisions_path.is_file() else None,
        "audio_metrics_path": _resolve_existing(audio_metrics_path) if audio_metrics_path.is_file() else None,
        "audio_manifest_path": _resolve_existing(audio_manifest_path) if audio_manifest_path.is_file() else None,
        "safe_zone_report_path": _resolve_existing(safe_zone_report_path) if safe_zone_report_path.is_file() else None,
        "audio_qa_report_path": _resolve_existing(audio_qa_report_path) if audio_qa_report_path.is_file() else None,
        "post_render_review_path": _resolve_existing(post_render_review_path) if post_render_review_path.is_file() else None,
        "broll_plan_path": _resolve_existing(broll_plan_path) if broll_plan_path.is_file() else None,
        "broll_report_path": _resolve_existing(broll_report_path) if broll_report_path.is_file() else None,
        "retry_plan_path": _resolve_existing(retry_plan_path) if retry_plan_path.is_file() else None,
        "run_state_path": _resolve_existing(run_state_path) if run_state_path.is_file() else None,
        "totals": {
            "clips": len(clips),
            "qa_passed": qa_report.get("passed") if isinstance(qa_report, dict) else None,
            "qa_total": qa_report.get("total") if isinstance(qa_report, dict) else None,
            "packaged": len(publish_manifest.get("clips", [])) if isinstance(publish_manifest, dict) else 0,
            "metadata": len(metadata_manifest.get("clips", [])) if isinstance(metadata_manifest, dict) else 0,
            "score_passed": scores_report.get("summary", {}).get("passed") if isinstance(scores_report, dict) else None,
            "candidates": candidate_moments.get("summary", {}).get("total") if isinstance(candidate_moments, dict) else None,
            "editor_keep": editor_review.get("summary", {}).get("keep") if isinstance(editor_review, dict) else None,
            "editor_reject": editor_review.get("summary", {}).get("reject") if isinstance(editor_review, dict) else None,
            "virality_passed": virality_review.get("summary", {}).get("passed") if isinstance(virality_review, dict) else None,
            "virality_rejected": virality_review.get("summary", {}).get("rejected") if isinstance(virality_review, dict) else None,
            "dramaturgy_passed": dramaturgy_report.get("summary", {}).get("passed") if isinstance(dramaturgy_report, dict) else None,
            "montage_ready": montage_plan.get("summary", {}).get("ready") if isinstance(montage_plan, dict) else None,
            "post_render_approved": post_render_review.get("summary", {}).get("approved") if isinstance(post_render_review, dict) else None,
            "post_render_rejected": post_render_review.get("summary", {}).get("rejected") if isinstance(post_render_review, dict) else None,
            "cleanup_safe_items": cleanup_plan.get("summary", {}).get("safe_plan_items") if isinstance(cleanup_plan, dict) else None,
            "agent_decisions": clip_decisions.get("summary", {}).get("total") if isinstance(clip_decisions, dict) else None,
            "agent_confirmed": clip_decisions.get("summary", {}).get("selected_by_agent") if isinstance(clip_decisions, dict) else None,
            "agent_confirmation_needed": clip_decisions.get("summary", {}).get("needs_agent_confirmation") if isinstance(clip_decisions, dict) else None,
            "cleanup_applied_clips": len([
                item for item in clips
                if isinstance(item.get("cleanup"), dict)
                and (item.get("montage_plan") or {})
                and (manifest.get("clips", [])[item["index"] - 1].get("cleanup_applied", {}).get("applied") if item.get("index") and item["index"] - 1 < len(manifest.get("clips", [])) else False)
            ]),
            "audio_warn": audio_metrics.get("summary", {}).get("warn") if isinstance(audio_metrics, dict) else None,
            "retry_failed_clips": len(retry_plan.get("failed_clips", [])) if isinstance(retry_plan, dict) else 0,
            "broll_planned": len(broll_plan.get("inserts", [])) if isinstance(broll_plan, dict) else 0,
        },
        "clips": clips,
        "qa": qa_report if isinstance(qa_report, dict) else {},
        "cleanup": cleanup_plan if isinstance(cleanup_plan, dict) else {},
        "candidate_moments": candidate_moments if isinstance(candidate_moments, dict) else {},
        "scores": scores_report if isinstance(scores_report, dict) else {},
        "editor_review": editor_review if isinstance(editor_review, dict) else {},
        "virality_review": virality_review if isinstance(virality_review, dict) else {},
        "dramaturgy_report": dramaturgy_report if isinstance(dramaturgy_report, dict) else {},
        "montage_plan": montage_plan if isinstance(montage_plan, dict) else {},
        "clip_decisions": clip_decisions if isinstance(clip_decisions, dict) else {},
        "audio_metrics": audio_metrics if isinstance(audio_metrics, dict) else {},
        "safe_zone": safe_zone_report if isinstance(safe_zone_report, dict) else {},
        "audio_qa": audio_qa_report if isinstance(audio_qa_report, dict) else {},
        "post_render_review": post_render_review if isinstance(post_render_review, dict) else {},
        "broll_plan": broll_plan if isinstance(broll_plan, dict) else {},
        "broll_report": broll_report if isinstance(broll_report, dict) else {},
        "retry": retry_plan if isinstance(retry_plan, dict) else {},
        "run_state": run_state if isinstance(run_state, dict) else {},
        "commands": {
            "open_clips_dir": _open_folder_command(clips_dir),
            "open_publish_dir": _open_folder_command(publish_dir) if publish_dir.is_dir() else None,
            "run_pipeline": run_command,
        },
        "note": "HTML UI и latest-results.json используют только пути и метаданные. MP4 не кодируются в base64 и не читаются целиком в UI.",
    }
    return latest


def write_latest_results(
    clips_dir: Path,
    *,
    latest_path: Path | None = None,
    **kwargs,
) -> Path:
    memory_root = _PLUGIN_ROOT / "videoshorts-memory"
    target = latest_path or (memory_root / "output" / "latest-results.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_latest_results(clips_dir, **kwargs), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def prepend_nvidia_wheel_bins_to_path() -> None:
    if sys.platform != "win32":
        return
    import site

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
        p = _ROOT / vdir / "Lib" / "site-packages"
        if p.is_dir():
            site_dirs.append(str(p))
    shorts_sp = _PLUGIN_ROOT.parent / "shorts" / "shorts_service" / "backend" / ".venv310" / "Lib" / "site-packages"
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


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Clip:
    start: float
    end: float
    score: float
    reason: str
    hook: str = ""
    payoff_ending: str = ""
    transcript_excerpt: str = ""
    semantic_boundary_evidence: dict = field(default_factory=dict)
    index: int | None = None
    reject_reason: str | None = None


def find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found. Install from https://ffmpeg.org/download.html and add to PATH")
    return ffmpeg


def extract_audio(video_path: Path, output_path: Path) -> bool:
    ffmpeg = find_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        str(output_path),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def whisper_subprocess_python() -> str:
    shorts_backend = _PLUGIN_ROOT.parent / "shorts" / "shorts_service" / "backend"
    for vname in (".venv310", ".venv"):
        exe = shorts_backend / vname / "Scripts" / "python.exe"
        if exe.is_file():
            return str(exe.resolve())
    for vname in (".venv310", ".venv"):
        exe = _ROOT / vname / "Scripts" / "python.exe"
        if exe.is_file():
            return str(exe.resolve())
    return sys.executable


def transcribe(audio_path: Path, model_size: str = "base") -> Tuple[List[Segment], dict]:
    if not _TRANSCRIBE_WORKER.is_file():
        raise RuntimeError(f"Missing {_TRANSCRIBE_WORKER}")

    py = whisper_subprocess_python()
    tmpdir = Path(tempfile.mkdtemp(prefix="vs_whisper_"))
    out_json = tmpdir / "segments.json"
    try:
        cmd = [py, "-u", str(_TRANSCRIBE_WORKER), str(audio_path.resolve()), model_size, str(out_json)]
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        p = subprocess.run(cmd, cwd=str(_ROOT), env=env)
        if p.returncode != 0:
            raise RuntimeError(f"transcribe_worker failed with exit code {p.returncode}")
        if not out_json.is_file():
            raise RuntimeError("transcribe_worker did not write output JSON")
        data = json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not data or "segments" not in data:
        raise RuntimeError("invalid transcription JSON from worker")

    segments = [
        Segment(start=float(s["start"]), end=float(s["end"]), text=str(s.get("text", "")))
        for s in data["segments"]
    ]
    meta = {
        "language": data.get("language"),
        "language_probability": data.get("language_probability"),
        "model": model_size,
        "segment_count": len(segments),
    }
    if isinstance(data.get("words"), list):
        meta["words"] = data["words"]
    return segments, meta


def segments_to_json(segments: List[Segment], meta: dict) -> dict:
    return {
        **meta,
        "segments": [asdict(s) for s in segments],
    }


def segments_from_json(data: dict) -> List[Segment]:
    return [
        Segment(start=float(s["start"]), end=float(s["end"]), text=str(s.get("text", "")))
        for s in data.get("segments", [])
    ]


def words_from_transcript_json(data: dict) -> list[dict]:
    """Word timestamps: top-level `words` или `_words` в первом сегменте (как shorts_service)."""
    if isinstance(data.get("words"), list):
        return data["words"]
    for seg in data.get("segments", []):
        if isinstance(seg.get("_words"), list):
            return seg["_words"]
    return []


def segments_to_selector_dicts(segments: List[Segment], words: list[dict] | None = None) -> list[dict]:
    rows = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
    if words and rows:
        rows[0]["_words"] = words
    return rows


def write_srt(segments: List[Segment], path: Path) -> None:
    def fmt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{fmt_time(seg.start)} --> {fmt_time(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def analyze_hook_quality_2026(text: str, first_3_sec_text: str = "") -> dict:
    _max = 10000
    if len(text) > _max:
        text = text[:_max]
    if first_3_sec_text and len(first_3_sec_text) > 2000:
        first_3_sec_text = first_3_sec_text[:2000]

    analysis_text = (first_3_sec_text or text[:150]).lower()
    full_text_lower = text.lower()

    HOOK_PATTERNS_2026 = {
        "pattern_interrupt": [
            r"^(stop|wait|hold on|не верьте|стоп|погодите)",
            r"^(nobody is talking about|все молчат|никто не говорит)",
            r"^(the truth about|правда про|реальность)",
            r"^(what if|а что если|представьте|imagine)",
            r"^(нет[,.]?\s|не\s|это\sне\s|миф|наоборот)",
        ],
        "curiosity_gap": [
            r"(the reason why|причина почему|вот почему)",
            r"(here's what|вот что|вот в чем|the real reason)",
            r"(most people don't know|мало кто знает|не многие знают)",
            r"(the secret to|секрет|ключ к|формула)",
            r"(дело в том|суть в том|фишка в том|на самом деле)",
        ],
        "value_promise": [
            r"(learn how|научишься|научитесь|покажу как|объясню как)",
            r"(step[- ]by[- ]step|по шагам|пошагово)",
            r"(will change|изменит|трансформирует)",
            r"(разбер(ём|ем)|покажу|объясню|смотри(те)?)",
        ],
        "question_hook": [
            r"\?",
            r"^(что|почему|как|знаете ли|а вы|правда ли|подойд[её]т ли|можно ли|нужен ли)",
            r"(подойд[её]т ли|можно ли|нужен ли|через .+ проще|а если)",
        ],
        "mythbust_contrast": [
            r"(не\s+слизали|наоборот|миф|это не так|только\s+\w+|не\s+нужен|не\s+подойд)",
            r"(vs code|vscode|курсор|cursor|codex|teya|плагин|субагент)",
            r"(оплат|клиент|репозитор|автоматизац)",
        ],
        "urgency_fomo": [r"(сейчас|срочно|успей|тренд|вирусно|ключевое|пока\b)"],
        "number_pattern": [
            r"\b\d+\s*(способов|советов|шагов|ошибок|лайфхаков)",
            r"\b\d+\s*(ways|tips|secrets|steps|mistakes)",
        ],
        "emotion_peak": [
            r"(невероятно|потрясающе|шокирует|взрыв мозга|хайп|хайпанул)",
            r"(amazing|incredible|shocking|mind-blowing)",
            r"(о[,!]?\s*сработало|вс[её]\s+сработало|я\s+вам\s+не\s+врал|сработало)",
            r"(wow|it\s+worked|told\s+you)",
        ],
        "live_proof": [
            r"(о[,!]?\s*сработало|вс[её]\s+сработало|опубликовалось|при\s+вас|"
            r"смотрите[,.]?\s+что\s+получилось|вот\s+результат|live\s*proof)",
            r"(установим|установка|распаковать|extensions?|chrome|яндекс|"
            r"кот\s+в\s+мешке|идём\s+проверять|идем\s+проверять|по\s+шагам)",
        ],
    }
    PATTERN_WEIGHTS = {
        "pattern_interrupt": 3.0,
        "curiosity_gap": 2.5,
        "value_promise": 2.0,
        "mythbust_contrast": 2.2,
        "emotion_peak": 1.8,
        "live_proof": 2.4,
        "question_hook": 1.5,
        "urgency_fomo": 1.5,
        "number_pattern": 1.2,
    }

    score = 0
    triggers: list[str] = []
    for pattern_name, patterns in HOOK_PATTERNS_2026.items():
        for pattern in patterns:
            if re.search(pattern, analysis_text, re.I):
                weight = PATTERN_WEIGHTS.get(pattern_name, 1.0)
                score += 12 * weight
                triggers.append(pattern_name)
                break

    first_sentence = analysis_text.split(".")[0] if "." in analysis_text else analysis_text
    word_count = len(first_sentence.split())
    if 3 <= word_count <= 10:
        score += 15
        triggers.append("optimal_hook_length")

    weak_starts = ["um", "uh", "ну", "эм", "типа", "короче", "итак"]
    if any(analysis_text.startswith(w + " ") or analysis_text == w for w in weak_starts):
        # «ну» alone is weak; «нужен ли Cursor» is a real Q&A hook — skip bare prefix on longer openers
        first_token = analysis_text.split()[0] if analysis_text.split() else ""
        if first_token in weak_starts and len(analysis_text.split()) <= 2:
            score -= 20
            triggers.append("weak_start_penalty")
        elif first_token in {"um", "uh", "эм", "типа"}:
            score -= 20
            triggers.append("weak_start_penalty")

    # RU webinar Q&A / product-name openers often miss classic viral regex — floor boost
    if not triggers or set(triggers) <= {"optimal_hook_length"}:
        webinar_open = re.search(
            r"(курсор|cursor|vscode|vs code|codex|teya|плагин|субагент|"
            r"подойд[её]т|можно ли|нужен ли|миф|наоборот|оплат|"
            r"сработало|опубликова|кот\s+в\s+мешке|триггер|установ)",
            analysis_text,
            re.I,
        )
        if webinar_open:
            score += 28
            triggers.append("webinar_qa_opener")

    # First-3s boring gate: filler/ad/meta openers without interrupt/proof
    boring_first3s = re.search(
        r"^(реклама|с\s+этого\s+сайта|ну\s+вот|итак|короче|типа|"
        r"здесь\s+добавить|опять\s+же|как\s+я\s+уже\s+говорил|"
        r"and\s+then|so\s+yeah|basically)",
        analysis_text,
        re.I,
    )
    strong = {"pattern_interrupt", "emotion_peak", "live_proof", "question_hook", "mythbust_contrast", "curiosity_gap"}
    if boring_first3s and not (strong & set(triggers)):
        score -= 35
        triggers.append("boring_first_3s")

    final_score = max(0, min(100, int(score)))
    return {
        "score": final_score,
        "triggers": list(set(triggers)),
        "passes_threshold": final_score >= 40,
    }


def select_clips(
    segments: List[Segment],
    clip_count: int,
    min_sec: float = 30,
    max_sec: float = 60,
) -> List[Clip]:
    clips: List[Clip] = []
    target_duration = (min_sec + max_sec) / 2
    if not segments:
        return []

    segments = sorted(segments, key=lambda s: s.start)
    video_duration = segments[-1].end
    step = max(3, target_duration / 4)

    word_timeline = []
    for seg in segments:
        words = seg.text.split()
        if words:
            word_duration = (seg.end - seg.start) / len(words)
            for i, word in enumerate(words):
                word_timeline.append({
                    "word": word,
                    "start": seg.start + i * word_duration,
                    "end": seg.start + (i + 1) * word_duration,
                })

    def find_sentence_boundary(time: float, direction: str = "after") -> float:
        boundary_chars = {".", "!", "?", "…"}
        if direction == "after":
            for w in word_timeline:
                if w["start"] >= time and w["word"][-1:] in boundary_chars:
                    return w["end"]
        else:
            for w in reversed(word_timeline):
                if w["end"] <= time and w["word"][-1:] in boundary_chars:
                    return w["start"]
        return time

    t = 0.0
    seg_i = 0
    while t < video_duration - min_sec:
        while seg_i < len(segments) and segments[seg_i].start < t:
            seg_i += 1
        window_segs = []
        j = seg_i
        while j < len(segments) and segments[j].start < t + target_duration:
            window_segs.append(segments[j])
            j += 1
        if not window_segs:
            t += step
            continue

        text = " ".join(s.text for s in window_segs)
        first_3_sec_text = " ".join(text.split()[:20])
        hook_analysis = analyze_hook_quality_2026(text, first_3_sec_text)
        score = hook_analysis["score"]
        triggers = hook_analysis["triggers"]

        raw_end = min(t + target_duration, video_duration)
        clip_start = find_sentence_boundary(t, "after")
        clip_end = find_sentence_boundary(raw_end, "before")
        if clip_end - clip_start < min_sec:
            clip_end = min(clip_start + target_duration, video_duration)

        clips.append(Clip(
            start=clip_start,
            end=clip_end,
            score=score,
            reason=", ".join(triggers[:3]) if triggers else "general",
        ))
        t += step

    clips.sort(key=lambda c: c.score, reverse=True)
    selected: List[Clip] = []
    used_ranges: list[tuple[float, float]] = []
    for clip in clips:
        overlaps = any(clip.start < e and clip.end > s for s, e in used_ranges)
        if not overlaps:
            selected.append(clip)
            used_ranges.append((clip.start, clip.end))
            if len(selected) >= clip_count:
                break

    selected.sort(key=lambda c: c.start)
    return selected


def select_clips_advanced(
    segments: List[Segment],
    clip_count: int,
    min_sec: float = 30,
    max_sec: float = 60,
    scenes: list[tuple[float, float]] | None = None,
    words: list[dict] | None = None,
) -> List[Clip]:
    """Продвинутый селектор из shorts_service/backend/app/clip_selector.py."""
    try:
        from clip_selector import select_best_clips
    except ImportError:
        return select_clips(segments, clip_count, min_sec, max_sec)

    seg_dicts = segments_to_selector_dicts(segments, words=words)
    candidates = select_best_clips(
        segments=seg_dicts,
        scenes=scenes or [],
        clip_count=clip_count,
        min_duration=min_sec,
        max_duration=max_sec,
        logger=lambda msg: print(f"   [ClipSelector] {msg}", flush=True),
    )
    if not candidates:
        return select_clips(segments, clip_count, min_sec, max_sec)

    return [
        Clip(
            start=c.start,
            end=c.end,
            score=c.final_score,
            reason=", ".join(c.hook_triggers[:3]) if c.hook_triggers else "advanced",
            hook=getattr(c, "text", "")[:140],
            transcript_excerpt=getattr(c, "text", "")[:700],
        )
        for c in candidates
    ]


def _collapse_ws(text: str, limit: int | None = None) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if limit and len(clean) > limit:
        return clean[: max(0, limit - 3)].rstrip(" ,.;:") + "..."
    return clean


def _sentence_head(text: str, limit: int = 120) -> str:
    clean = _collapse_ws(text)
    match = re.search(r"^(.{20,}?[.!?…])\s+", clean)
    return _collapse_ws(match.group(1) if match else clean, limit)


def _sentence_tail(text: str, limit: int = 160) -> str:
    clean = _collapse_ws(text)
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", clean) if p.strip()]
    return _collapse_ws(parts[-1] if parts else clean[-limit:], limit)


def _looks_incomplete_ending(text: str) -> bool:
    clean = _collapse_ws(text).lower()
    if not clean:
        return True
    parts = [p.strip(" \t\r\n.,!?…:;—-") for p in re.split(r"(?<=[.!?…])\s+", clean) if p.strip()]
    tail = parts[-1] if parts else clean[-120:]
    dangling_exact = {
        "первое",
        "второе",
        "третье",
        "следующее",
        "дальше",
        "итак",
        "так",
        "сейчас",
        "сейчас объясню",
        "сейчас покажу",
        "я объясню",
        "объясню",
        "начнем",
        "продолжим",
        "one",
        "two",
        "next",
        "first",
        "second",
        "let me explain",
    }
    if tail in dangling_exact:
        return True
    return tail.startswith((
        "первое ",
        "второе ",
        "третье ",
        "следующий пункт",
        "следующая ",
        "сейчас объясню",
        "сейчас покажу",
        "давайте посмотрим",
        "я объясню",
        "let me explain",
        "here is why",
        "next ",
    ))


def _segments_for_range(segments: List[Segment], start: float, end: float) -> list[Segment]:
    return [s for s in segments if s.end > start and s.start < end]


def _clip_text(segments: List[Segment], start: float, end: float) -> str:
    return _collapse_ws(" ".join(s.text for s in _segments_for_range(segments, start, end)))


def _boundary_reason(start_seg: Segment | None, prev_seg: Segment | None, *, is_start: bool) -> str:
    if not start_seg:
        return "Граница оставлена по исходному времени: рядом нет сегмента транскрипта."
    if is_start:
        pause = start_seg.start - prev_seg.end if prev_seg else None
        prefix = "Начало поставлено на начале фразы"
        if pause is not None and pause >= 0.65:
            prefix = f"Начало поставлено после паузы {pause:.1f} сек"
        return f"{prefix}: «{_collapse_ws(start_seg.text, 140)}»"
    suffix = "Конец поставлен на завершении фразы"
    if re.search(r"[.!?…]\s*$", start_seg.text.strip()):
        suffix = "Конец поставлен на явном пунктуационном завершении"
    return f"{suffix}: «{_collapse_ws(start_seg.text, 140)}»"


def enrich_semantic_boundaries(
    segments: List[Segment],
    clips: List[Clip],
    min_sec: float = 30,
    max_sec: float = 60,
) -> List[Clip]:
    """Snap clips to transcript segment edges and attach boundary evidence.

    Скрипт не заменяет агентный выбор смысла, но даёт агенту стабильный инструмент:
    переменная длина, завершённая мысль и объяснимые start/end в moments.json.
    """
    if not segments or not clips:
        return clips

    ordered = sorted(segments, key=lambda s: s.start)
    result: list[Clip] = []
    for clip in clips:
        original_start = clip.start
        original_end = clip.end
        overlapping = _segments_for_range(ordered, clip.start, clip.end)
        if not overlapping:
            result.append(clip)
            continue

        center = (clip.start + clip.end) / 2
        first_idx = ordered.index(overlapping[0])
        best: tuple[float, int, int, float, float, str] | None = None

        start_min = max(0, first_idx - 3)
        start_max = min(len(ordered) - 1, first_idx + 3)
        for s_idx in range(start_min, start_max + 1):
            for e_idx in range(s_idx, len(ordered)):
                start = ordered[s_idx].start
                end = ordered[e_idx].end
                duration = end - start
                if duration > max_sec:
                    break
                if duration < min_sec:
                    continue
                text = _clip_text(ordered, start, end)
                if len(text.split()) < 18:
                    continue
                hook_analysis = analyze_hook_quality_2026(text, _sentence_head(text, 120))
                center_penalty = abs(((start + end) / 2) - center) * 0.45
                end_bonus = 8 if re.search(r"[.!?…]\s*$", ordered[e_idx].text.strip()) else 0
                incomplete_penalty = 28 if _looks_incomplete_ending(text) else 0
                # Keep duration valid but do not pull boundaries back toward the midpoint.
                duration_bonus = 6 if min_sec <= duration <= max_sec else 0
                score = clip.score * 0.45 + hook_analysis["score"] * 0.35 + end_bonus + duration_bonus - center_penalty - incomplete_penalty
                reason = ", ".join(hook_analysis["triggers"][:3]) or clip.reason
                if best is None or score > best[0]:
                    best = (score, s_idx, e_idx, start, end, reason)

        if best is None:
            # Fallback: keep raw clip but still expose the transcript evidence.
            start = overlapping[0].start
            end = overlapping[-1].end
            if end - start > max_sec:
                end = min(clip.end, start + max_sec)
            if end - start < min_sec:
                end = min(ordered[-1].end, start + ((min_sec + max_sec) / 2))
            s_idx = ordered.index(overlapping[0])
            e_idx = ordered.index(overlapping[-1])
            score = clip.score
            reason = clip.reason
        else:
            score, s_idx, e_idx, start, end, reason = best

        text = _clip_text(ordered, start, end)
        first_seg = ordered[s_idx]
        prev_seg = ordered[s_idx - 1] if s_idx > 0 else None
        last_seg = ordered[e_idx]
        hook = _sentence_head(text, 140)
        payoff = _sentence_tail(text, 180)
        clip.start = round(float(start), 3)
        clip.end = round(float(end), 3)
        clip.score = round(float(score), 2)
        clip.reason = reason or clip.reason
        clip.hook = hook
        clip.payoff_ending = payoff
        clip.transcript_excerpt = _collapse_ws(text, 900)
        clip.semantic_boundary_evidence = {
            "why_start": _boundary_reason(first_seg, prev_seg, is_start=True),
            "why_end": _boundary_reason(last_seg, None, is_start=False),
            "hook": hook,
            "payoff_ending": payoff,
            "transcript_excerpt": _collapse_ws(text, 900),
            "variable_duration": round(clip.end - clip.start, 2),
            "snapped_from": {"start": round(original_start, 3), "end": round(original_end, 3)},
            "boundary_type": "transcript_segment_edges",
        }
        result.append(clip)

    result.sort(key=lambda c: c.start)
    return result


def clips_to_json(clips: List[Clip]) -> dict:
    return {
        "clips": [asdict(c) for c in clips],
        "count": len(clips),
    }


def clips_from_json(data: dict) -> List[Clip]:
    clips: List[Clip] = []
    for i, c in enumerate(data.get("clips", []), 1):
        if not isinstance(c, dict):
            continue
        reject = c.get("reject_reason")
        if reject:
            continue
        raw_index = c.get("index")
        try:
            index = int(raw_index) if raw_index is not None else i
        except (TypeError, ValueError):
            index = i
        clips.append(
            Clip(
                start=float(c["start"]),
                end=float(c["end"]),
                score=float(c.get("score", 0)),
                reason=str(c.get("reason", "")),
                hook=str(c.get("hook", "")),
                payoff_ending=str(c.get("payoff_ending", "")),
                transcript_excerpt=str(c.get("transcript_excerpt", "")),
                semantic_boundary_evidence=c.get("semantic_boundary_evidence") if isinstance(c.get("semantic_boundary_evidence"), dict) else {},
                index=index,
                reject_reason=None,
            )
        )
    return clips


def _detect_face_opencv_haar(frame) -> Optional[Tuple[int, int, int, int]]:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        return None
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
    if len(faces) == 0:
        return None
    faces = sorted(faces, key=lambda r: r[2] * r[3], reverse=True)
    x, y, bw, bh = faces[0]
    return (int(x), int(y), int(bw), int(bh))


def detect_face(frame) -> Optional[Tuple[int, int, int, int]]:
    try:
        import mediapipe as mp
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
            mp_face = mp.solutions.face_detection
            with mp_face.FaceDetection(min_detection_confidence=0.5) as detector:
                import cv2
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = detector.process(rgb)
                if results.detections:
                    det = results.detections[0]
                    bbox = det.location_data.relative_bounding_box
                    h, w = frame.shape[:2]
                    return (
                        int(bbox.xmin * w),
                        int(bbox.ymin * h),
                        int(bbox.width * w),
                        int(bbox.height * h),
                    )
    except Exception:
        pass
    return _detect_face_opencv_haar(frame)


def _merge_intervals(intervals: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for raw_start, raw_end in intervals:
        cut_start = max(start, float(raw_start))
        cut_end = min(end, float(raw_end))
        if cut_end - cut_start >= 0.08:
            cleaned.append((cut_start, cut_end))
    cleaned.sort()

    merged: list[tuple[float, float]] = []
    for cut_start, cut_end in cleaned:
        if not merged or cut_start > merged[-1][1] + 0.03:
            merged.append((cut_start, cut_end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], cut_end))
    return merged


def _keep_segments(start: float, end: float, cut_intervals: list[tuple[float, float]] | None) -> list[tuple[float, float]]:
    if not cut_intervals:
        return [(start, end)]

    segments: list[tuple[float, float]] = []
    cursor = start
    for cut_start, cut_end in _merge_intervals(cut_intervals, start, end):
        if cut_start - cursor >= 0.12:
            segments.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if end - cursor >= 0.12:
        segments.append((cursor, end))
    return segments or [(start, end)]


def create_webinar_split(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float,
    top_ratio: float = 0.30,
    output_width: int = 720,
    output_height: int = 1280,
    cut_intervals: list[tuple[float, float]] | None = None,
) -> bool:
    import cv2
    import numpy as np

    ffmpeg = find_ffmpeg()
    segments = _keep_segments(start, end, cut_intervals)
    effective_start = min(s for s, _ in segments)
    effective_end = max(e for _, e in segments)
    cap = cv2.VideoCapture(str(input_path))
    sample_count = 7
    sample_times = [
        effective_start + (i + 1) * max(0.1, effective_end - effective_start) / (sample_count + 1)
        for i in range(sample_count)
    ]
    frame = None
    face_samples: list[tuple[int, int, int, int]] = []
    for sample_time in sample_times:
        cap.set(cv2.CAP_PROP_POS_MSEC, sample_time * 1000)
        ret, sample_frame = cap.read()
        if not ret:
            continue
        if frame is None:
            frame = sample_frame
        sample_face = detect_face(sample_frame)
        if sample_face:
            face_samples.append(sample_face)

    if frame is None:
        cap.release()
        return False

    input_h, input_w = frame.shape[:2]
    cap.release()

    top_h = int(output_height * top_ratio)
    bottom_h = output_height - top_h

    top_filter = (
        f"scale={output_width}:{top_h}:force_original_aspect_ratio=decrease,"
        f"pad={output_width}:{top_h}:(ow-iw)/2:(oh-ih)/2:black"
    )

    face = None
    if face_samples:
        centers_x = [x + w / 2 for x, y, w, h in face_samples]
        centers_y = [y + h / 2 for x, y, w, h in face_samples]
        fw = int(np.median([w for x, y, w, h in face_samples]))
        fh = int(np.median([h for x, y, w, h in face_samples]))
        cx = int(np.median(centers_x))
        cy = int(np.median(centers_y))
        face = (max(0, cx - fw // 2), max(0, cy - fh // 2), max(1, fw), max(1, fh))

    if face:
        fx, fy, fw, fh = face
        crop_h = max(2, input_h // 2)
        crop_w = max(2, int(crop_h * (output_width / bottom_h)))
        crop_w = min(crop_w, input_w)
        crop_h = min(max(2, int(crop_w / (output_width / bottom_h))), input_h)
        cx, cy = fx + fw // 2, fy + fh // 2
        crop_x = max(0, min(cx - crop_w // 2, input_w - crop_w))
        crop_y = max(0, min(cy - crop_h // 2, input_h - crop_h))
    else:
        crop_h = max(2, input_h // 2)
        crop_w = max(2, int(crop_h * (output_width / bottom_h)))
        crop_w = min(crop_w, input_w)
        crop_h = min(max(2, int(crop_w / (output_width / bottom_h))), input_h)
        crop_x = max(0, (input_w - crop_w) // 2)
        crop_y = max(0, (input_h - crop_h) // 2)

    bottom_filter = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={output_width}:{bottom_h}"
    use_simple_trim = len(segments) == 1 and not cut_intervals
    if use_simple_trim:
        filter_complex = (
            f"split[top][bot];"
            f"[top]{top_filter}[t];"
            f"[bot]{bottom_filter}[b];"
            f"[t][b]vstack=inputs=2[v]"
        )
        audio_map = "0:a?"
    else:
        parts: list[str] = []
        concat_inputs: list[str] = []
        for idx, (seg_start, seg_end) in enumerate(segments):
            parts.append(
                f"[0:v]trim=start={seg_start:.3f}:end={seg_end:.3f},"
                f"setpts=PTS-STARTPTS,split=2[vtop{idx}][vbot{idx}]"
            )
            parts.append(f"[vtop{idx}]{top_filter}[t{idx}]")
            parts.append(f"[vbot{idx}]{bottom_filter}[b{idx}]")
            parts.append(f"[t{idx}][b{idx}]vstack=inputs=2[v{idx}]")
            parts.append(
                f"[0:a]atrim=start={seg_start:.3f}:end={seg_end:.3f},"
                f"asetpts=PTS-STARTPTS[a{idx}]"
            )
            concat_inputs.append(f"[v{idx}][a{idx}]")
        parts.append("".join(concat_inputs) + f"concat=n={len(segments)}:v=1:a=1[v][a]")
        filter_complex = ";".join(parts)
        audio_map = "[a]"

    input_args = ["-ss", str(start), "-to", str(end), "-i", str(input_path)] if use_simple_trim else ["-i", str(input_path)]
    cmd = [
        ffmpeg, "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", audio_map,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-movflags", "+faststart",
        "-c:a", "aac",
        str(output_path),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0
