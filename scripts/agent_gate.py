#!/usr/bin/env python3
"""Agent-mode gate: блокирует алгоритмические draft-решения."""
from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import pstdev
from typing import Any


REQUIRED_DECISION_FIELDS = (
    "why_this_moment",
    "hook_assessment",
    "viral_hypothesis",
    "thought_start_evidence",
    "thought_end_evidence",
    "cleanup_applied",
    "cut_instruction",
    "reject_if",
    "confidence",
)


def memory_root(plugin_root: Path | None = None) -> Path:
    root = plugin_root or Path(__file__).resolve().parents[1]
    return root / "videoshorts-memory"


def decisions_path(plugin_root: Path | None = None) -> Path:
    return memory_root(plugin_root) / "moments" / "clip-decisions.json"


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def agent_mode_enabled(flag: bool | None = None) -> bool:
    if flag is not None:
        return bool(flag)
    env = os.environ.get("VIDEOSHORTS_AGENT_MODE", "").strip().lower()
    return env in {"1", "true", "yes", "agent"}


def evaluate_agent_decisions(plugin_root: Path | None = None, *, require_agent: bool = False) -> dict[str, Any]:
    path = decisions_path(plugin_root)
    data = read_json(path)
    clips = data.get("clips") if isinstance(data.get("clips"), list) else []
    selected = [c for c in clips if isinstance(c, dict) and c.get("selected_by_agent")]
    missing_fields: list[str] = []
    for item in clips:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        for field in REQUIRED_DECISION_FIELDS:
            if field not in item or item.get(field) in (None, "", []):
                missing_fields.append(f"clip_{idx}:{field}")

    decision_source = data.get("decision_source")
    is_draft = decision_source == "local_heuristic_draft"
    needs_confirmation = bool(data.get("summary", {}).get("needs_agent_confirmation"))
    issues: list[str] = []

    if require_agent:
        if not path.is_file():
            issues.append("clip_decisions_missing")
        if is_draft:
            issues.append("decision_source_local_heuristic_draft")
        if not selected:
            issues.append("no_selected_by_agent")
        if needs_confirmation:
            issues.append("needs_agent_confirmation")
        if missing_fields:
            issues.append(f"missing_decision_fields:{len(missing_fields)}")

    return {
        "path": str(path),
        "exists": path.is_file(),
        "decision_source": decision_source,
        "total": len(clips),
        "selected_by_agent": len(selected),
        "needs_agent_confirmation": needs_confirmation,
        "missing_fields": missing_fields[:40],
        "require_agent": require_agent,
        "ok": not issues,
        "issues": issues,
    }


def evaluate_uniform_durations(clips: list[dict[str, Any]], *, min_count: int = 5, tolerance: float = 2.0) -> dict[str, Any]:
    durations = []
    for item in clips:
        if not isinstance(item, dict):
            continue
        try:
            durations.append(float(item.get("duration") or 0))
        except (TypeError, ValueError):
            continue
    if len(durations) < min_count:
        return {"ok": True, "uniform": False, "durations": durations, "stddev": None}
    spread = pstdev(durations) if len(durations) > 1 else 0.0
    uniform = spread < tolerance
    return {
        "ok": not uniform,
        "uniform": uniform,
        "durations": durations,
        "stddev": round(spread, 3),
        "issue": "uniform_algorithmic_durations" if uniform else None,
    }


def gate_message(report: dict[str, Any]) -> str:
    issues = ", ".join(report.get("issues") or []) or "unknown"
    return (
        "Agent gate FAIL: запрещён запуск cutter/packager на draft-решениях. "
        f"issues=[{issues}]. Подтвердите clip-decisions.json субагентами "
        "(selected_by_agent=true, decision_source!=local_heuristic_draft)."
    )
