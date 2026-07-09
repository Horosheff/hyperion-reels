#!/usr/bin/env python3
"""VideoShorts — безопасная проверка open incidents для Fixic."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Whole-line field only (avoid prose / durable_fix mentions).
_STATUS_OPEN = re.compile(r"(?m)^(?:\s*[-*]\s*)?status:\s*open\s*$")
_INCIDENT_REPORT = re.compile(r"(?m)^(?:\s*[-*]\s*)?incident_report:\s*(\S+)")


def _fragment_reports_open_incident(text: str) -> bool:
    """True if a fragment field incident_report is set and not none/fixed."""
    for match in _INCIDENT_REPORT.finditer(text):
        value = match.group(1).strip().lower().rstrip(".,;")
        if value in {"none", "fixed", "wontfix", "n/a", "-", "—"}:
            continue
        # Historical fragment pointers to queue INC are OK once queue status!=open.
        # Only treat as open if the value itself says open or is a bare non-none token
        # without a queue file (legacy). Prefer queue file as source of truth.
        if value.startswith("open"):
            return True
    return False


def has_open_incidents(root: Path) -> bool:
    memory = root / "videoshorts-memory"
    queue = memory / "pipeline-fix-queue.md"
    if queue.is_file():
        text = queue.read_text(encoding="utf-8", errors="replace")
        if _STATUS_OPEN.search(text):
            return True
    # Fragments: only explicit status: open (not historical incident_report links)
    fragments = memory / "fragments"
    if fragments.is_dir():
        for path in sorted(fragments.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            if _STATUS_OPEN.search(text):
                return True
            if _fragment_reports_open_incident(text):
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Check VideoShorts open incidents")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    open_found = has_open_incidents(args.project_root.resolve())
    print("OPEN_INCIDENTS=1" if open_found else "OPEN_INCIDENTS=0")
    sys.exit(2 if open_found else 0)


if __name__ == "__main__":
    main()
