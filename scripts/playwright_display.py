#!/usr/bin/env python3
"""Playwright window placement on a chosen Windows monitor.

User numbering (Hyperion default for 3 displays):
  1 = rightmost monitor
  2 = primary (main) monitor
  3 = topmost monitor (if present)

Env:
  PLAYWRIGHT_MONITOR=1|2|3|right|left|primary|top
  PLAYWRIGHT_WINDOW_POSITION=X,Y   (overrides monitor pick)
  PLAYWRIGHT_WINDOW_SIZE=W,H      (optional; default = monitor size)
  PLAYWRIGHT_MONITOR_LAYOUT=1:right,2:primary,3:top  (optional remap)
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("playwright_display")

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _ensure_env_loaded() -> None:
    """Load videoshorts.local.env so PLAYWRIGHT_MONITOR works even if caller forgot dotenv."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore
    for path in (
        _PLUGIN_ROOT / "videoshorts.local.env",
        _PLUGIN_ROOT / ".env",
        Path.cwd() / "videoshorts.local.env",
        Path.cwd() / ".env",
    ):
        if not path.is_file():
            continue
        if load_dotenv is not None:
            load_dotenv(path, override=False)
        else:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    # Hard defaults if still unset — user display #1 = rightmost
    os.environ.setdefault("PLAYWRIGHT_MONITOR", "1")
    os.environ.setdefault("PLAYWRIGHT_MONITOR_LAYOUT", "1:right,2:primary,3:top")


_ensure_env_loaded()


@dataclass(frozen=True)
class MonitorInfo:
    index: int
    primary: bool
    x: int
    y: int
    width: int
    height: int
    device: str


_MON_CACHE: list[MonitorInfo] | None = None
_MON_CACHE_AT = 0.0


def list_monitors() -> list[MonitorInfo]:
    """Windows screens via PowerShell WinForms (cached — safe for parallel Chromium launches)."""
    global _MON_CACHE, _MON_CACHE_AT
    import time as _t

    now = _t.time()
    if _MON_CACHE is not None and (now - _MON_CACHE_AT) < 60:
        return list(_MON_CACHE)

    if sys.platform != "win32":
        return []
    ps = r"""
Add-Type -AssemblyName System.Windows.Forms
$screens = [System.Windows.Forms.Screen]::AllScreens
$i = 0
$arr = @()
foreach ($s in $screens) {
  $b = $s.Bounds
  $arr += [pscustomobject]@{
    index=$i; primary=[bool]$s.Primary; x=$b.X; y=$b.Y; width=$b.Width; height=$b.Height; device=[string]$s.DeviceName
  }
  $i++
}
$arr | ConvertTo-Json -Compress
"""
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        mons = [
            MonitorInfo(
                index=int(d["index"]),
                primary=bool(d["primary"]),
                x=int(d["x"]),
                y=int(d["y"]),
                width=int(d["width"]),
                height=int(d["height"]),
                device=str(d.get("device") or ""),
            )
            for d in data
        ]
        _MON_CACHE = mons
        _MON_CACHE_AT = now
        return list(mons)
    except Exception as exc:
        logger.warning("list_monitors failed: %s", exc)
        return list(_MON_CACHE or [])


def _alias_monitor(mons: list[MonitorInfo], alias: str) -> MonitorInfo | None:
    if not mons:
        return None
    a = alias.strip().lower()
    if a in {"primary", "main"}:
        for m in mons:
            if m.primary:
                return m
        return mons[0]
    if a in {"right"}:
        return max(mons, key=lambda m: m.x)
    if a in {"left"}:
        return min(mons, key=lambda m: m.x)
    if a in {"top"}:
        return min(mons, key=lambda m: m.y)
    if a in {"bottom"}:
        return max(mons, key=lambda m: m.y)
    return None


def _parse_layout() -> dict[str, str]:
    """Default: user #1 = right, #2 = primary/main, #3 = top."""
    raw = (os.getenv("PLAYWRIGHT_MONITOR_LAYOUT") or "1:right,2:primary,3:top").strip()
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, _, v = part.partition(":")
        out[k.strip()] = v.strip().lower()
    return out


def resolve_monitor(choice: str | None = None) -> MonitorInfo | None:
    _ensure_env_loaded()
    mons = list_monitors()
    if not mons:
        return None
    raw = (choice if choice is not None else os.getenv("PLAYWRIGHT_MONITOR", "1")).strip()
    if not raw:
        raw = "1"
    layout = _parse_layout()
    if re.fullmatch(r"\d+", raw):
        mapped = layout.get(raw)
        if mapped:
            hit = _alias_monitor(mons, mapped)
            if hit:
                return hit
        idx = int(raw) - 1
        if 0 <= idx < len(mons):
            return mons[idx]
        return mons[0]
    hit = _alias_monitor(mons, raw)
    return hit or mons[0]


def chromium_window_args(*, maximize: bool = True) -> list[str]:
    """Args to place Chromium on the chosen monitor.

    VIDEOSHORTS_WINDOW_SLOT / VIDEOSHORTS_BROWSER_SLOT — сдвиг окна при
    параллельной публикации (Instagram не оказывается под Дзен/VK).
    """
    _ensure_env_loaded()
    pos = (os.getenv("PLAYWRIGHT_WINDOW_POSITION") or "").strip()
    size = (os.getenv("PLAYWRIGHT_WINDOW_SIZE") or "").strip()
    if pos and re.fullmatch(r"-?\d+\s*,\s*-?\d+", pos):
        x_s, y_s = [p.strip() for p in pos.split(",", 1)]
        x, y = int(x_s), int(y_s)
    else:
        mon = resolve_monitor()
        if mon is None:
            return ["--start-maximized"] if maximize else []
        x, y = mon.x, mon.y
        if not size:
            # slight shrink helps Chromium keep the window on that monitor
            size = f"{max(800, mon.width - 16)},{max(600, mon.height - 16)}"

    slot_raw = (
        os.getenv("VIDEOSHORTS_WINDOW_SLOT")
        or os.getenv("VIDEOSHORTS_BROWSER_SLOT")
        or "0"
    ).strip()
    try:
        slot = max(0, int(slot_raw))
    except ValueError:
        slot = 0
    if slot:
        # cascade ~56px so parallel headed browsers stay visible
        x += 56 * slot
        y += 40 * slot

    args = [f"--window-position={x},{y}"]
    if size and re.fullmatch(r"\d+\s*,\s*\d+", size):
        w_s, h_s = [p.strip() for p in size.split(",", 1)]
        args.append(f"--window-size={w_s},{h_s}")
    if maximize:
        args.append("--start-maximized")
    return args


def headed_launch_args(*extra: str, maximize: bool = True) -> list[str]:
    """Standard headed Chromium args with monitor placement + optional extras."""
    _ensure_env_loaded()
    args = list(chromium_window_args(maximize=maximize))
    for item in extra:
        if item and item not in args:
            args.append(item)
    return args


def describe_placement() -> str:
    _ensure_env_loaded()
    mon = resolve_monitor()
    if mon is None:
        return "monitor: unknown (fallback primary)"
    choice = os.getenv("PLAYWRIGHT_MONITOR", "1")
    return (
        f"PLAYWRIGHT_MONITOR={choice} -> {mon.device} "
        f"primary={mon.primary} @ ({mon.x},{mon.y}) {mon.width}x{mon.height}"
    )
