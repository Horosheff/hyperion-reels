#!/usr/bin/env python3
"""VideoShorts — общее логирование в файл.

Даёт каждому скрипту logger, который:
  - пишет в videoshorts-memory/logs/<name>.log (ротация 3×2 МБ);
  - дублирует WARNING+ в stderr (print/UX агентов не трогаем);
  - уровень задаётся VIDEOSHORTS_LOG_LEVEL (default INFO);
  - каталог логов переопределяется VIDEOSHORTS_LOG_DIR.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED: set[str] = set()


def _log_dir() -> Path:
    override = os.getenv("VIDEOSHORTS_LOG_DIR")
    if override:
        path = Path(override)
    else:
        root = Path(__file__).resolve().parents[1]
        path = root / "videoshorts-memory" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logger(name: str) -> logging.Logger:
    """Идемпотентный logger: повторный вызов не добавляет handlers."""
    logger = logging.getLogger(f"videoshorts.{name}")
    if logger.name in _CONFIGURED:
        return logger

    try:
        level = getattr(logging, os.getenv("VIDEOSHORTS_LOG_LEVEL", "INFO").upper(), logging.INFO)
    except Exception:
        level = logging.INFO
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = RotatingFileHandler(
            _log_dir() / f"{name}.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # Нет прав/места на диске — логируем хотя бы в stderr
        pass

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    logger.addHandler(console)

    _CONFIGURED.add(logger.name)
    return logger
