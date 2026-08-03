#!/usr/bin/env python3
"""Safe zones вертикальных платформ (YouTube Shorts / Reels / TikTok UI).

Замерено по эталонной карте перекрытий (макет 360x640):
- верх (шапка: аватар, имя канала, подписаться): ~10.5% высоты
- низ (название, описание, прогресс): ~19.5% высоты
- левый край: ~5% ширины
- правая колонка кнопок (лайк/коммент/шаринг): ~18% ширины в нижней части

Всё, что вшиваем в кадр (субтитры, прогресс-бар, стикеры), обязано
остаться внутри safe area, иначе UI платформы перекроет вставку.

Env-ручки:
  VIDEOSHORTS_SAFE_ZONE=0            — отключить принудительные отступы
  VIDEOSHORTS_SAFE_ZONE_TOP_PCT      — переопределить верх, % (default 10.5)
  VIDEOSHORTS_SAFE_ZONE_BOTTOM_PCT   — низ, % (default 19.5)
  VIDEOSHORTS_SAFE_ZONE_LEFT_PCT     — лево, % (default 5.0)
  VIDEOSHORTS_SAFE_ZONE_RIGHT_PCT    — право, % (default 18.0)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

TOP_PCT = 10.5
BOTTOM_PCT = 19.5
LEFT_PCT = 5.0
RIGHT_PCT = 18.0


def _env_pct(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def safe_zone_enabled() -> bool:
    return os.environ.get("VIDEOSHORTS_SAFE_ZONE", "1").strip().lower() not in {"0", "false", "off"}


@dataclass(frozen=True)
class SafeZone:
    width: int
    height: int
    top: int
    bottom: int
    left: int
    right: int

    @property
    def safe_top(self) -> int:
        return self.top

    @property
    def safe_bottom(self) -> int:
        return self.height - self.bottom

    @property
    def safe_left(self) -> int:
        return self.left

    @property
    def safe_right(self) -> int:
        return self.width - self.right


def get_safe_zone(width: int, height: int) -> SafeZone:
    """Пиксельные отступы небезопасных зон для кадра width x height."""
    top = round(height * _env_pct("VIDEOSHORTS_SAFE_ZONE_TOP_PCT", TOP_PCT) / 100)
    bottom = round(height * _env_pct("VIDEOSHORTS_SAFE_ZONE_BOTTOM_PCT", BOTTOM_PCT) / 100)
    left = round(width * _env_pct("VIDEOSHORTS_SAFE_ZONE_LEFT_PCT", LEFT_PCT) / 100)
    right = round(width * _env_pct("VIDEOSHORTS_SAFE_ZONE_RIGHT_PCT", RIGHT_PCT) / 100)
    return SafeZone(width=width, height=height, top=top, bottom=bottom, left=left, right=right)


def subtitle_min_margin_v(height: int) -> int:
    """Минимальный ASS MarginV для субтитров у нижнего края.

    Субтитры по умолчанию стоят у низа кадра (Alignment=2) — ровно там,
    где Shorts/Reels рисуют название и описание. MarginV меньше нижней
    зоны означает, что текст уедет под UI после публикации.
    """
    if not safe_zone_enabled():
        return 0
    return get_safe_zone(1, height).bottom


def subtitle_side_margins(width: int) -> tuple[int, int]:
    """(MarginL, MarginR) минимумы: левый край и правая колонка кнопок."""
    if not safe_zone_enabled():
        return 0, 0
    zone = get_safe_zone(width, 1)
    return zone.left, zone.right
