#!/usr/bin/env python3
"""Guard: decision scripts refuse to invent content without --heuristic."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REFUSAL = """\
[AGENT MODE] Скрипт не принимает решений.

Напиши артефакт сам (Write), затем проверь:
  python validate_agent_artifacts.py {kind} "{path}"

Локальная диагностика (только run_pipeline / runMode=local):
  добавь флаг --heuristic

См. shared/agent-decision-contract.md
"""


def stamp_heuristic(data: dict, script_name: str) -> dict:
    """Mark payload as local diagnostic draft (never agent)."""
    payload = dict(data)
    payload["decision_source"] = "local_heuristic_draft"
    payload["authored_by"] = f"heuristic:{script_name}"
    payload["note"] = (
        payload.get("note")
        or "Heuristic draft only. Agent mode must Write artifact with decision_source=agent."
    )
    return payload


def add_decision_mode_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--heuristic",
        action="store_true",
        help="Local diagnostic only. Agents must Write JSON themselves.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate an existing agent-written artifact and exit.",
    )


def enforce_decision_mode(args: argparse.Namespace, *, kind: str, path: Path) -> None:
    """Exit 0 on --validate OK, 2 on validate fail, 3 if agent tried to generate."""
    from validate_agent_artifacts import validate_kind

    path = Path(path)
    if getattr(args, "validate", False):
        ok, errors = validate_kind(kind, path)
        if ok:
            print(f"✅ validate {kind}: {path}")
            raise SystemExit(0)
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        raise SystemExit(2)

    if not getattr(args, "heuristic", False):
        print(REFUSAL.format(kind=kind, path=path), file=sys.stderr)
        raise SystemExit(3)
