#!/usr/bin/env python3
"""Compatibility wrapper for cleanup_plan.py.

P0 реализует безопасный smart-trim как план действий, а не как destructive edit.
"""
from __future__ import annotations

from cleanup_plan import main


if __name__ == "__main__":
    main()
