#!/usr/bin/env python3
"""Run a command and keep VideoShorts run-status.json honest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def update_status(path: Path, patch: dict) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:
        data = {}
    data.update(patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run command with status tracking")
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("No command passed to run_with_status.py")

    update_status(args.status, {
        "status": "RUNNING",
        "pid": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "exit_code": None,
        "error": None,
    })

    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("w", encoding="utf-8", errors="replace") as log:
        log.write("VideoShorts pipeline started\n")
        log.write(subprocess.list2cmdline(command) + "\n\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=str(args.cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        update_status(args.status, {"pid": process.pid})
        exit_code = process.wait()

    update_status(args.status, {
        "status": "PASS" if exit_code == 0 else "FAIL",
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "exit_code": exit_code,
    })
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
