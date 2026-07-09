#!/usr/bin/env python3
"""Profile local machine and recommend VideoShorts settings."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = PLUGIN_ROOT / "videoshorts-memory"
PROFILE_PATH = MEMORY_ROOT / "system-profile.json"

try:
    from ensure_dependencies import ensure_dependencies
except ImportError:
    ensure_dependencies = None  # type: ignore[assignment]


def run_capture(command: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.returncode, (result.stdout or result.stderr or "").strip()
    except Exception as exc:
        return 1, str(exc)


def total_ram_gb() -> float | None:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullTotalPhys / (1024 ** 3), 1)
    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return round((pages * page_size) / (1024 ** 3), 1)
        except Exception:
            pass
    return None


def detect_nvidia() -> dict:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"available": False, "gpus": [], "reason": "nvidia-smi not found"}
    code, output = run_capture([
        nvidia_smi,
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ])
    if code != 0:
        return {"available": False, "gpus": [], "reason": output}
    gpus = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            try:
                vram_mb = int(float(parts[1]))
            except ValueError:
                vram_mb = 0
            gpus.append({
                "name": parts[0],
                "vram_mb": vram_mb,
                "vram_gb": round(vram_mb / 1024, 1),
                "driver": parts[2],
            })
    return {"available": bool(gpus), "gpus": gpus}


def detect_video_controllers() -> list[dict]:
    if os.name != "nt":
        return []
    code, output = run_capture([
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
    ])
    if code != 0 or not output:
        return []
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            data = [data]
        return data if isinstance(data, list) else []
    except Exception:
        return []


def detect_ffmpeg() -> dict:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        return {"available": False, "ffmpeg": None, "ffprobe": ffprobe}
    code, output = run_capture([ffmpeg, "-version"], timeout=5)
    first_line = output.splitlines()[0] if output else ""
    return {"available": code == 0, "ffmpeg": ffmpeg, "ffprobe": ffprobe, "version": first_line}


def detect_faster_whisper() -> dict:
    code, output = run_capture([sys.executable, "-c", "import faster_whisper; print(getattr(faster_whisper, '__version__', 'installed'))"], timeout=10)
    return {"available": code == 0, "version": output if code == 0 else None, "error": None if code == 0 else output}


def recommend(cpu_count: int, ram_gb: float | None, nvidia: dict) -> dict:
    gpus = nvidia.get("gpus") or []
    best_vram = max((gpu.get("vram_gb") or 0 for gpu in gpus), default=0)
    has_cuda = bool(nvidia.get("available") and best_vram >= 3)

    settings = {
        "device": "gpu" if has_cuda else "cpu",
        "force_cpu": not has_cuda,
        "model": "base",
        "word_timestamps": True,
        "beam_size": 1,
        "compute_type": "float16" if has_cuda else "int8",
        "clips": 10,
        "min_sec": 30,
        "max_sec": 60,
        "render_workers": max(1, min(4, cpu_count or 2)),
        "subtitle_format": "both",
        "progress_bar": False,
        "zoom_punch": False,
        "b_roll": False,
        "reason": [],
    }

    if has_cuda:
        if best_vram >= 12:
            settings["model"] = "turbo"
            settings["reason"].append("NVIDIA GPU с VRAM 12GB+ — можно использовать Whisper turbo.")
        elif best_vram >= 8:
            settings["model"] = "small"
            settings["reason"].append("NVIDIA GPU с VRAM 8GB+ — баланс качества и скорости: small.")
        else:
            settings["model"] = "base"
            settings["reason"].append("NVIDIA GPU найдена, но VRAM ограничена — безопасно использовать base.")
    else:
        if ram_gb is not None and ram_gb < 8:
            settings["model"] = "tiny"
            settings["clips"] = 5
            settings["reason"].append("Мало RAM и нет CUDA — выбран tiny и меньше клипов.")
        else:
            settings["model"] = "base"
            settings["reason"].append("CUDA не найдена — CPU/int8, модель base.")

    if ram_gb is not None and ram_gb < 12:
        settings["render_workers"] = min(settings["render_workers"], 2)
        settings["reason"].append("RAM меньше 12GB — ограничены render workers.")

    if cpu_count <= 4:
        settings["render_workers"] = min(settings["render_workers"], 2)
        settings["reason"].append("CPU до 4 потоков — снижена параллельность рендера.")

    return settings


def build_profile() -> dict:
    cpu_count = os.cpu_count() or 1
    ram = total_ram_gb()
    nvidia = detect_nvidia()
    profile = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
        },
        "cpu": {
            "logical_cores": cpu_count,
            "processor": platform.processor(),
        },
        "memory": {
            "total_gb": ram,
        },
        "gpu": {
            "nvidia": nvidia,
            "controllers": detect_video_controllers(),
        },
        "ffmpeg": detect_ffmpeg(),
        "faster_whisper": detect_faster_whisper(),
    }
    if ensure_dependencies is not None:
        dep_report = ensure_dependencies(install=False)
        profile["dependencies"] = {
            "ready": dep_report.get("ready", False),
            "missing_required": dep_report.get("missing_required", []),
            "checks": dep_report.get("checks", []),
            "report_path": str(MEMORY_ROOT / "dependencies-report.json"),
        }
    else:
        profile["dependencies"] = {
            "ready": profile["ffmpeg"]["available"] and profile["faster_whisper"]["available"],
            "missing_required": [],
            "checks": [],
            "report_path": None,
        }
    profile["recommendations"] = recommend(cpu_count, ram, nvidia)
    return profile


def write_profile(path: Path = PROFILE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_profile(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile system and recommend VideoShorts settings")
    parser.add_argument("-o", "--output", type=Path, default=PROFILE_PATH)
    args = parser.parse_args()
    path = write_profile(args.output)
    print(path)


if __name__ == "__main__":
    main()
