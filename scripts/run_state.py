#!/usr/bin/env python3
"""VideoShorts — минимальный run-state/retry каркас для local fallback."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"schema_version": 1, "status": "PENDING", "stages": {}, "failed_clips": [], "updated_at": utc_now()}


def save_state(path: Path, state: dict) -> None:
    state["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def update_stage(path: Path, stage: str, status: str, **extra) -> dict:
    state = load_state(path)
    stages = state.setdefault("stages", {})
    current = stages.get(stage, {})
    current.update({
        "status": status,
        "updated_at": utc_now(),
        **{k: v for k, v in extra.items() if v is not None},
    })
    if status == "RUNNING" and "started_at" not in current:
        current["started_at"] = utc_now()
    if status in {"PASS", "FAIL", "SKIPPED"}:
        current["finished_at"] = utc_now()
    stages[stage] = current
    if status == "FAIL":
        state["status"] = "FAIL"
    elif all(item.get("status") in {"PASS", "SKIPPED"} for item in stages.values()):
        state["status"] = "PASS"
    else:
        state["status"] = "RUNNING"
    save_state(path, state)
    return state


def init_state(path: Path, *, source_video: str | None = None, settings: dict | None = None) -> dict:
    state = {
        "schema_version": 1,
        "status": "RUNNING",
        "source_video": source_video,
        "settings": settings or {},
        "stages": {},
        "failed_clips": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    save_state(path, state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: update run-state.json")
    parser.add_argument("state", type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--source-video", default=None)
    p_stage = sub.add_parser("stage")
    p_stage.add_argument("stage")
    p_stage.add_argument("status", choices=["RUNNING", "PASS", "FAIL", "SKIPPED"])
    p_stage.add_argument("--artifact", default=None)
    p_stage.add_argument("--message", default=None)
    args = parser.parse_args()

    if args.cmd == "init":
        state = init_state(args.state, source_video=args.source_video)
    else:
        state = update_stage(args.state, args.stage, args.status, artifact=args.artifact, message=args.message)
    print(json.dumps({"status": state.get("status"), "state": str(args.state)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
