#!/usr/bin/env python3
"""Validate agent-written decision artifacts (no generation)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from agent_gate import REQUIRED_DECISION_FIELDS
from videoshorts_core import configure_stdio

configure_stdio()


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"__error__": str(exc)}


def _require_agent_source(data: dict, errors: list[str], *, label: str) -> None:
    source = data.get("decision_source")
    if source != "agent":
        errors.append(f"{label}: decision_source must be 'agent' (got {source!r})")
    authored = data.get("authored_by")
    if not authored or not str(authored).startswith("videoshorts-"):
        errors.append(f"{label}: authored_by must be videoshorts-<role> (got {authored!r})")


def _clips_list(data: dict) -> list:
    clips = data.get("clips")
    return clips if isinstance(clips, list) else []


def validate_cleanup_plan(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="cleanup-plan")
    if "safe_removal_plan" not in data and "items" not in data and "summary" not in data:
        errors.append("cleanup-plan: need safe_removal_plan or summary")
    return not errors, errors


def validate_candidates(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="candidates")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 10:
        errors.append(f"candidates: need at least 10 items (got {0 if not isinstance(candidates, list) else len(candidates)})")
    for i, item in enumerate((candidates or [])[:5]):
        if not isinstance(item, dict):
            errors.append(f"candidates[{i}]: not object")
            continue
        for field in ("candidate_reason", "hook_type", "possible_title", "why_not_cut_yet"):
            if not item.get(field):
                errors.append(f"candidates[{i}]: missing {field}")
        if item.get("start") is None or item.get("end") is None:
            errors.append(f"candidates[{i}]: missing start/end")
    return not errors, errors


def validate_moments(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="moments")
    clips = _clips_list(data)
    if not clips:
        errors.append("moments: clips[] empty")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            errors.append(f"clips[{i}]: not object")
            continue
        for field in ("start", "end", "hook", "payoff_ending", "transcript_excerpt", "editorial_rationale"):
            if clip.get(field) in (None, ""):
                errors.append(f"clips[{i}]: missing {field}")
        evidence = clip.get("semantic_boundary_evidence")
        if not isinstance(evidence, dict):
            errors.append(f"clips[{i}]: missing semantic_boundary_evidence")
        else:
            for field in ("why_start", "why_end"):
                if not evidence.get(field):
                    errors.append(f"clips[{i}].evidence missing {field}")
    return not errors, errors


def validate_clip_scores(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="clip-scores")
    clips = _clips_list(data)
    if not clips:
        errors.append("clip-scores: clips[] empty")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        for field in ("hook_score", "virality_score", "quality_score", "pacing_score", "completeness_score"):
            if clip.get(field) is None:
                errors.append(f"clips[{i}]: missing {field}")
        # weak clips must explain reject
        try:
            quality = float(clip.get("quality_score") or 0)
        except (TypeError, ValueError):
            quality = 0
        if quality < 40 and not clip.get("reject_reason"):
            errors.append(f"clips[{i}]: low quality requires reject_reason")
    return not errors, errors


def validate_editor_review(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="editor-review")
    clips = _clips_list(data)
    if not clips:
        errors.append("editor-review: clips[] empty")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        if "keep" not in clip and "status" not in clip:
            errors.append(f"clips[{i}]: need keep or status")
        if not clip.get("editor_notes"):
            errors.append(f"clips[{i}]: missing editor_notes")
    return not errors, errors


def validate_virality_review(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="virality-review")
    clips = _clips_list(data)
    if not clips:
        errors.append("virality-review: clips[] empty")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        for field in ("shareability", "comment_trigger", "curiosity_gap", "save_value", "virality_score"):
            if clip.get(field) is None:
                errors.append(f"clips[{i}]: missing {field}")
        status = str(clip.get("status") or "").upper()
        if status == "REJECT" and not clip.get("reject_reason") and not clip.get("critic_notes"):
            errors.append(f"clips[{i}]: REJECT needs reject_reason or critic_notes")
    return not errors, errors


def validate_refined_moments(path: Path) -> tuple[bool, list[str]]:
    ok, errors = validate_moments(path)
    data = _load(path)
    if not isinstance(data, dict):
        return ok, errors
    # override label was moments — re-check source already done
    for i, clip in enumerate(_clips_list(data)):
        if not isinstance(clip, dict):
            continue
        evidence = clip.get("semantic_boundary_evidence") if isinstance(clip.get("semantic_boundary_evidence"), dict) else {}
        gate = evidence.get("finished_thought_gate") or clip.get("finished_thought_gate")
        if str(gate).lower() not in {"pass", "true", "1", "ok"}:
            errors.append(f"clips[{i}]: finished_thought_gate must pass")
    return not errors, errors


def validate_clip_decisions(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="clip-decisions")
    clips = _clips_list(data)
    if not clips:
        errors.append("clip-decisions: clips[] empty")
    selected = 0
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        for field in REQUIRED_DECISION_FIELDS:
            if clip.get(field) in (None, "", []):
                errors.append(f"clips[{i}]: missing {field}")
        if clip.get("selected_by_agent"):
            selected += 1
            if clip.get("decision_source") not in (None, "agent"):
                # per-clip source optional if top-level is agent
                pass
        if clip.get("agent_confirmation_required"):
            errors.append(f"clips[{i}]: agent_confirmation_required must be false for agent artifacts")
    if selected < 1:
        errors.append("clip-decisions: need at least one selected_by_agent=true")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    if summary.get("needs_agent_confirmation"):
        errors.append("clip-decisions: summary.needs_agent_confirmation must be 0")
    return not errors, errors


def validate_dramaturgy_report(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="dramaturgy-report")
    clips = _clips_list(data)
    if not clips:
        errors.append("dramaturgy-report: clips[] empty")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        for field in ("setup", "tension", "insight_or_result", "clean_ending", "status"):
            if clip.get(field) in (None, ""):
                errors.append(f"clips[{i}]: missing {field}")
    return not errors, errors


def validate_montage_plan(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="montage-plan")
    clips = _clips_list(data)
    if not clips:
        errors.append("montage-plan: clips[] empty")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        if "jump_cuts" not in clip and "silence_remove" not in clip:
            errors.append(f"clips[{i}]: need jump_cuts or silence_remove")
        if not clip.get("glue_notes") and clip.get("glue_notes") != "":
            # glue_notes recommended
            pass
        if "do_not_cut_before" not in clip and "do_not_cut_after" not in clip:
            errors.append(f"clips[{i}]: need do_not_cut_before/after guidance")
    return not errors, errors


def validate_post_render_review(path: Path) -> tuple[bool, list[str]]:
    data = _load(path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="post-render-review")
    clips = _clips_list(data)
    if not clips:
        errors.append("post-render-review: clips[] empty")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        if "approve" not in clip:
            errors.append(f"clips[{i}]: missing approve")
        if clip.get("approve") is False and not clip.get("rerender_reason"):
            errors.append(f"clips[{i}]: approve=false needs rerender_reason")
    return not errors, errors


def validate_metadata(path: Path) -> tuple[bool, list[str]]:
    """path = metadata-manifest.json or clips_dir."""
    manifest_path = path
    if path.is_dir():
        manifest_path = path / "metadata-manifest.json"
    data = _load(manifest_path)
    errors: list[str] = []
    if data is None:
        return False, [f"missing: {manifest_path}"]
    if isinstance(data, dict) and data.get("__error__"):
        return False, [f"invalid json: {data['__error__']}"]
    if not isinstance(data, dict):
        return False, ["root must be object"]
    _require_agent_source(data, errors, label="metadata")
    clips = _clips_list(data)
    if not clips:
        errors.append("metadata: clips[] empty")
    platforms_needed = ("youtube", "instagram", "tiktok", "telegram")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        if not clip.get("title") or not clip.get("description"):
            errors.append(f"clips[{i}]: missing title/description")
        platforms = clip.get("platforms")
        if not isinstance(platforms, dict):
            errors.append(f"clips[{i}]: missing platforms")
            continue
        for name in platforms_needed:
            pack = platforms.get(name)
            if not isinstance(pack, dict):
                errors.append(f"clips[{i}].platforms.{name} missing")
                continue
            if not (pack.get("title") or pack.get("caption")):
                errors.append(f"clips[{i}].platforms.{name}: title/caption required")
            if name == "youtube" and not pack.get("description"):
                errors.append(f"clips[{i}].platforms.youtube: description required")
            if name == "instagram" and not (pack.get("caption") or pack.get("description")):
                errors.append(f"clips[{i}].platforms.instagram: caption required")
        if not clip.get("cover_prompt"):
            errors.append(f"clips[{i}]: cover_prompt required")
        # per-file exists if clips_dir known
        clips_dir = manifest_path.parent
        pad = int(clip.get("index") or i + 1)
        json_name = clip.get("json") or f"clip_{pad:02d}.metadata.json"
        md_name = clip.get("markdown")
        if not md_name:
            errors.append(
                f"clips[{i}]: markdown path required (e.g. clip_{pad:02d}.metadata.md); null/absent breaks packager"
            )
            md_name = f"clip_{pad:02d}.metadata.md"
        meta_file = clips_dir / "metadata" / str(json_name)
        if not meta_file.is_file():
            errors.append(f"clips[{i}]: missing file {meta_file.name}")
        md_file = clips_dir / "metadata" / str(md_name)
        if not md_file.is_file():
            errors.append(f"clips[{i}]: missing file {md_file.name}")
    return not errors, errors


VALIDATORS: dict[str, Callable[[Path], tuple[bool, list[str]]]] = {
    "cleanup-plan": validate_cleanup_plan,
    "candidates": validate_candidates,
    "candidate-moments": validate_candidates,
    "moments": validate_moments,
    "clip-scores": validate_clip_scores,
    "scores": validate_clip_scores,
    "editor-review": validate_editor_review,
    "virality-review": validate_virality_review,
    "refined-moments": validate_refined_moments,
    "clip-decisions": validate_clip_decisions,
    "dramaturgy-report": validate_dramaturgy_report,
    "montage-plan": validate_montage_plan,
    "post-render-review": validate_post_render_review,
    "metadata": validate_metadata,
}


def validate_kind(kind: str, path: Path) -> tuple[bool, list[str]]:
    key = kind.strip().lower()
    fn = VALIDATORS.get(key)
    if not fn:
        return False, [f"unknown kind: {kind}. known: {', '.join(sorted(set(VALIDATORS)))}"]
    return fn(Path(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate agent-written VideoShorts artifacts")
    parser.add_argument("kind", help="artifact kind, e.g. metadata, clip-decisions, moments")
    parser.add_argument("path", type=Path, help="path to JSON file or clips_dir for metadata")
    args = parser.parse_args()
    ok, errors = validate_kind(args.kind, args.path)
    if ok:
        print(f"✅ {args.kind}: {args.path}")
        raise SystemExit(0)
    for err in errors:
        print(f"[ERROR] {err}", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
