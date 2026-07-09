#!/usr/bin/env python3
"""Проверка и автоматическая установка зависимостей VideoShorts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
REQUIREMENTS_PATH = SCRIPTS_DIR / "requirements.txt"
MEMORY_ROOT = PLUGIN_ROOT / "videoshorts-memory"
REPORT_PATH = MEMORY_ROOT / "dependencies-report.json"

MIN_PYTHON = (3, 10)

PIP_PACKAGES: list[dict[str, str]] = [
    {"import_name": "cv2", "pip_name": "opencv-python", "label": "OpenCV"},
    {"import_name": "numpy", "pip_name": "numpy", "label": "NumPy"},
    {"import_name": "mediapipe", "pip_name": "mediapipe", "label": "MediaPipe"},
    {"import_name": "faster_whisper", "pip_name": "faster-whisper", "label": "faster-whisper"},
    {"import_name": "tqdm", "pip_name": "tqdm", "label": "tqdm"},
]


def run_command(command: list[str], timeout: int = 600) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(PLUGIN_ROOT),
        )
        output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        return result.returncode, output
    except Exception as exc:
        return 1, str(exc)


def module_available(import_name: str) -> tuple[bool, str | None]:
    spec = importlib.util.find_spec(import_name)
    if spec is None:
        return False, None
    try:
        module = importlib.import_module(import_name)
        version = getattr(module, "__version__", None)
        return True, str(version) if version is not None else "installed"
    except Exception as exc:
        return False, str(exc)


def check_python() -> dict[str, Any]:
    version_info = sys.version_info
    version = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    ok = version_info[:2] >= MIN_PYTHON
    return {
        "id": "python",
        "label": "Python",
        "required": True,
        "available": ok,
        "version": version,
        "detail": sys.executable,
        "installable": False,
        "install_hint": "Установите Python 3.10+ с https://www.python.org/downloads/ и отметьте Add to PATH.",
    }


def check_ffmpeg() -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    available = bool(ffmpeg and ffprobe)
    version = None
    if ffmpeg:
        code, output = run_command([ffmpeg, "-version"], timeout=10)
        if code == 0 and output:
            version = output.splitlines()[0]
    return {
        "id": "ffmpeg",
        "label": "FFmpeg + ffprobe",
        "required": True,
        "available": available,
        "version": version,
        "detail": {"ffmpeg": ffmpeg, "ffprobe": ffprobe},
        "installable": True,
        "install_hint": "Windows: winget install Gyan.FFmpeg | macOS: brew install ffmpeg | Linux: sudo apt install ffmpeg",
    }


def check_pip_package(import_name: str, pip_name: str, label: str) -> dict[str, Any]:
    available, version = module_available(import_name)
    return {
        "id": pip_name,
        "label": label,
        "required": True,
        "available": available,
        "version": version if available else None,
        "detail": {"import": import_name, "pip": pip_name},
        "installable": True,
        "install_hint": f"pip install {pip_name}",
    }


def check_nvidia_optional() -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {
            "id": "nvidia-smi",
            "label": "NVIDIA GPU (опционально)",
            "required": False,
            "available": False,
            "version": None,
            "detail": "nvidia-smi не найден — Whisper будет на CPU.",
            "installable": False,
            "install_hint": "Для GPU установите драйвер NVIDIA и CUDA toolkit.",
        }
    code, output = run_command([nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], timeout=10)
    return {
        "id": "nvidia-smi",
        "label": "NVIDIA GPU (опционально)",
        "required": False,
        "available": code == 0,
        "version": output.splitlines()[0].strip() if code == 0 and output else None,
        "detail": nvidia_smi,
        "installable": False,
        "install_hint": "Опционально: драйвер NVIDIA.",
    }


def collect_checks() -> list[dict[str, Any]]:
    checks = [check_python(), check_ffmpeg()]
    checks.extend(
        check_pip_package(item["import_name"], item["pip_name"], item["label"])
        for item in PIP_PACKAGES
    )
    checks.append(check_nvidia_optional())
    return checks


def summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    missing_required = [item for item in checks if item["required"] and not item["available"]]
    missing_installable = [item for item in missing_required if item.get("installable")]
    return {
        "ready": not missing_required,
        "missing_required": [item["id"] for item in missing_required],
        "missing_installable": [item["id"] for item in missing_installable],
        "checks": checks,
    }


def install_pip_packages(targets: list[str] | None = None) -> dict[str, Any]:
    if not REQUIREMENTS_PATH.is_file():
        return {"ok": False, "error": f"requirements.txt не найден: {REQUIREMENTS_PATH}"}

    command = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)]
    if targets:
        command = [sys.executable, "-m", "pip", "install", *targets]
    code, output = run_command(command, timeout=1800)
    return {"ok": code == 0, "command": command, "output": output}


def install_ffmpeg() -> dict[str, Any]:
    system = platform.system()
    if system == "Windows":
        winget = shutil.which("winget")
        if winget:
            command = [
                winget,
                "install",
                "-e",
                "--id",
                "Gyan.FFmpeg",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
            code, output = run_command(command, timeout=1800)
            if code == 0:
                return {"ok": True, "method": "winget", "command": command, "output": output}
        choco = shutil.which("choco")
        if choco:
            command = [choco, "install", "ffmpeg", "-y"]
            code, output = run_command(command, timeout=1800)
            if code == 0:
                return {"ok": True, "method": "choco", "command": command, "output": output}
        return {
            "ok": False,
            "error": "Не удалось установить FFmpeg автоматически. Установите вручную: winget install Gyan.FFmpeg",
        }

    if system == "Darwin":
        brew = shutil.which("brew")
        if not brew:
            return {"ok": False, "error": "Homebrew не найден. Установите brew и выполните: brew install ffmpeg"}
        command = [brew, "install", "ffmpeg"]
        code, output = run_command(command, timeout=1800)
        return {"ok": code == 0, "method": "brew", "command": command, "output": output}

    for manager, command in (
        ("apt", ["sudo", "apt-get", "install", "-y", "ffmpeg"]),
        ("dnf", ["sudo", "dnf", "install", "-y", "ffmpeg"]),
        ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"]),
    ):
        binary = shutil.which(command[0]) or shutil.which(command[1] if command[0] == "sudo" else command[0])
        if command[0] == "sudo" and not shutil.which("sudo"):
            continue
        code, output = run_command(command, timeout=1800)
        if code == 0:
            return {"ok": code == 0, "method": manager, "command": command, "output": output}

    return {
        "ok": False,
        "error": "Автоустановка FFmpeg на Linux не удалась. Установите пакет ffmpeg через менеджер пакетов ОС.",
    }


def ensure_dependencies(install: bool = False) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    before = summarize(collect_checks())

    if install and not before["ready"]:
        pip_targets = [
            item["pip_name"]
            for item in PIP_PACKAGES
            if item["pip_name"] in before["missing_installable"]
        ]
        if pip_targets or "python" not in before["missing_required"]:
            pip_result = install_pip_packages()
            actions.append({"step": "pip", **pip_result})

        after_pip = summarize(collect_checks())
        if "ffmpeg" in after_pip["missing_installable"]:
            ffmpeg_result = install_ffmpeg()
            actions.append({"step": "ffmpeg", **ffmpeg_result})

    after = summarize(collect_checks())
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "ready": after["ready"],
        "missing_required": after["missing_required"],
        "checks": after["checks"],
        "install_requested": install,
        "install_actions": actions,
    }
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка и установка зависимостей VideoShorts")
    parser.add_argument("--install", action="store_true", help="Установить недостающие зависимости, если возможно")
    parser.add_argument("-o", "--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    report = ensure_dependencies(install=args.install)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if not report["ready"]:
        missing = ", ".join(report["missing_required"]) or "unknown"
        raise SystemExit(f"Зависимости не готовы: {missing}")


if __name__ == "__main__":
    main()
