"""Общий humanize для Playwright-клиентов публикации (VK / Дзен / TikTok / RuTube).

Цель — меньше «робот-паттерна»: случайные паузы, hover перед кликом, печать
с задержкой вместо мгновенного fill.

Глобально: HUMANIZE=1 (по умолчанию вкл.) / HUMANIZE=0 выключает везде.
Платформенно: VK_HUMANIZE, DZEN_HUMANIZE, TIKTOK_HUMANIZE, RUTUBE_HUMANIZE
(если не заданы — следуют за HUMANIZE).
"""
from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Callable, Optional


def env_flag(*keys: str, default: bool = True) -> bool:
    """Первый найденный ключ из env; иначе default. HUMANIZE=0 глушит всё."""
    global_raw = os.getenv("HUMANIZE")
    if global_raw is not None and global_raw.strip() != "":
        if global_raw.lower() in {"0", "false", "no", "off"}:
            return False
        if global_raw.lower() in {"1", "true", "yes", "on"}:
            # платформенный ключ может ещё выключить
            pass
        else:
            return False
    for key in keys:
        raw = os.getenv(key)
        if raw is None or raw.strip() == "":
            continue
        return raw.lower() not in {"0", "false", "no", "off"}
    if global_raw is not None and global_raw.strip() != "":
        return global_raw.lower() not in {"0", "false", "no", "off"}
    return default


class PageHumanize:
    """Привязка к page через getter — page может появиться после start()."""

    def __init__(
        self,
        page_getter: Callable[[], Any],
        *,
        enabled: bool = True,
        name: str = "humanize",
    ) -> None:
        self._page_getter = page_getter
        self.enabled = enabled
        self.name = name

    @property
    def page(self) -> Any:
        return self._page_getter()

    async def pause(self, lo: float = 0.45, hi: float = 1.35) -> None:
        """Пауза в секундах. При disabled — короткая техническая."""
        if not self.enabled:
            await asyncio.sleep(0.08)
            return
        await asyncio.sleep(random.uniform(lo, hi))

    async def pause_ms(self, lo_ms: int = 250, hi_ms: int = 900) -> None:
        await self.pause(lo_ms / 1000.0, hi_ms / 1000.0)

    async def micro_move(self) -> None:
        """Лёгкое движение мыши — не целиться в UI-элементы."""
        page = self.page
        if not self.enabled or page is None:
            return
        try:
            vp = page.viewport_size or {"width": 1280, "height": 720}
            x = random.randint(80, max(120, int(vp["width"] * 0.7)))
            y = random.randint(80, max(120, int(vp["height"] * 0.6)))
            await page.mouse.move(x, y, steps=random.randint(4, 12))
        except Exception:
            pass

    async def click(
        self,
        locator: Any,
        *,
        timeout: int = 8000,
        force: bool = False,
        button: str = "left",
        click_count: int = 1,
    ) -> None:
        target = locator.first if hasattr(locator, "first") else locator
        try:
            await target.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass
        await self.pause(0.28, 0.85)
        await self.micro_move()
        if self.enabled:
            try:
                await target.hover(timeout=min(timeout, 4000))
                await self.pause(0.15, 0.5)
            except Exception:
                pass
        kwargs: dict[str, Any] = {"timeout": timeout}
        if force:
            kwargs["force"] = True
        if button != "left":
            kwargs["button"] = button
        if click_count != 1:
            kwargs["click_count"] = click_count
        await target.click(**kwargs)
        await self.pause(0.2, 0.65)

    async def type_text(
        self,
        locator: Any,
        text: str,
        *,
        clear: bool = True,
        timeout: int = 8000,
        delay_lo: int = 22,
        delay_hi: int = 55,
    ) -> None:
        """Печать посимвольно. Длинный текст (>280) — fill + короткая «допечатка»."""
        target = locator.first if hasattr(locator, "first") else locator
        await self.click(target, timeout=timeout)
        await self.pause(0.2, 0.55)
        if clear:
            try:
                await target.fill("")
            except Exception:
                try:
                    await target.press("Control+A")
                    await target.press("Backspace")
                except Exception:
                    pass
        value = text or ""
        if not self.enabled:
            await target.fill(value)
            return
        if len(value) > 280:
            await target.fill(value)
            await self.pause(0.25, 0.6)
            return
        delay = random.randint(delay_lo, delay_hi)
        await target.type(value, delay=delay)
        await self.pause(0.25, 0.7)

    async def fill_fast_ok(self, locator: Any, text: str, *, timeout: int = 8000) -> None:
        """Для очень длинных полей: click → fill, но с паузами вокруг."""
        target = locator.first if hasattr(locator, "first") else locator
        await self.click(target, timeout=timeout)
        await self.pause(0.2, 0.5)
        await target.fill(text or "")
        await self.pause(0.3, 0.8)


def make_humanize(
    page_getter: Callable[[], Any],
    *env_keys: str,
    name: str = "humanize",
) -> PageHumanize:
    return PageHumanize(page_getter, enabled=env_flag(*env_keys), name=name)
