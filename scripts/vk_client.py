#!/usr/bin/env python3
"""Playwright-клиент VK Видео (клипы) по живой записи codegen.

Сценарий (записан 2026-07-25):
  1) https://vkvideo.ru/upload
  2) [data-testid=video_upload_placeholder_add_btn] → popup
  3) «Выбрать файл» + [data-testid=video_upload_select_file]
  4) закрыть лишний modalbox (если есть)
  5) [data-testid=clips-upload-description]
  6) обложка: [data-testid=media-attach-input] «Выбрать обложку»
  7) опционально switch
  8) [data-testid=clips-uploadForm-publish-button]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional
    def load_dotenv(*_a, **_k):  # type: ignore[misc]
        return False

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_LOG_DIR = _PLUGIN_ROOT / "videoshorts-memory" / "output"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_SHOT_DIR = _LOG_DIR / "vk-screenshots"
_SHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "vk_autopost.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("vk_client")

for _env_path in (
    _PLUGIN_ROOT / "videoshorts.local.env",
    _PLUGIN_ROOT / ".env",
    Path.cwd() / "videoshorts.local.env",
    Path.cwd() / ".env",
):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
load_dotenv(override=False)

SESSION_COOKIE_NAMES = {"remixsid", "remixnsid", "remixsid_encrypted"}


class VkVideoClient:
    UPLOAD_URL = "https://vkvideo.ru/upload"

    def __init__(self) -> None:
        self.channel = (
            os.getenv("VK_CHANNEL_NAME")
            or os.getenv("VIDEOSHORTS_VK_CHANNEL")
            or "kov4eg_ai"
        ).lstrip("@")
        self.channel_url = (
            os.getenv("VK_CHANNEL_URL")
            or os.getenv("VIDEOSHORTS_VK_CHANNEL_URL")
            or f"https://vkvideo.ru/@{self.channel}"
        )
        default_storage = _PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "vk_storage_state.json"
        self.storage_state_path = os.getenv(
            "VIDEOSHORTS_VK_STORAGE",
            os.getenv("VK_STORAGE_STATE", str(default_storage)),
        )
        self.headless = os.getenv("HEADLESS", "false").lower() == "true"
        self.timeout = int(os.getenv("BROWSER_TIMEOUT", "180000"))
        force_close = os.getenv("VIDEOSHORTS_FORCE_CLOSE_BROWSER", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        self.keep_open = (os.getenv("KEEP_BROWSER_OPEN", "false").lower() == "true") and not force_close
        # «Кнопка действия» (Открыть канал в мессенджере) — по умолчанию ВКЛ
        self.enable_action_button = os.getenv("VK_ACTION_BUTTON", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        # Legacy: VK_TOGGLE_FIRST_SWITCH=1 — клик по первому switch (не рекомендуется)
        self.toggle_first_switch = os.getenv("VK_TOGGLE_FIRST_SWITCH", "0").lower() in {
            "1",
            "true",
            "yes",
        }

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        try:
            from playwright_display import chromium_window_args, describe_placement

            launch_args = [
                "--disable-blink-features=AutomationControlled",
                *chromium_window_args(maximize=True),
            ]
            logger.info("Display: %s", describe_placement())
        except Exception as exc:
            logger.warning("playwright_display unavailable: %s", exc)
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ]
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
        )
        kwargs = {
            "viewport": {"width": 1440, "height": 1100},
            "locale": "ru-RU",
            "timezone_id": "Europe/Moscow",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        }
        if self.storage_state_path and Path(self.storage_state_path).is_file():
            kwargs["storage_state"] = self.storage_state_path
            logger.info("Cookies: %s", self.storage_state_path)
        self.context = await self.browser.new_context(**kwargs)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        logger.info("VK Video browser started · channel=@%s", self.channel)

    async def save_cookies(self) -> None:
        if not self.context:
            return
        path = Path(self.storage_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(path))
        logger.info("Cookies saved → %s", path)

    async def close(self, force: bool = False) -> None:
        if self.keep_open and not force:
            logger.info("KEEP_BROWSER_OPEN — браузер не закрываю")
            return
        try:
            if self.context:
                await self.save_cookies()
        except Exception:
            pass
        for obj in (self.page, self.context, self.browser):
            try:
                if obj:
                    await obj.close()
            except Exception:
                pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def screenshot(self, name: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _SHOT_DIR / f"{name}_{stamp}.png"
        target = self.page
        if target:
            await target.screenshot(path=str(path), full_page=True)
            logger.info("screenshot: %s", path.name)
        return path

    def _is_auth_url(self, url: str) -> bool:
        u = (url or "").lower()
        return any(
            h in u
            for h in (
                "id.vk.com",
                "id.vk.ru",
                "login.vk.com",
                "login.vk.ru",
                "oauth.vk.com",
                "oauth.vk.ru",
            )
        )

    async def _has_session_cookie(self) -> bool:
        if not self.context:
            return False
        try:
            cookies = await self.context.cookies()
            names = {c.get("name") for c in cookies if isinstance(c, dict)}
            return bool(names & SESSION_COOKIE_NAMES)
        except Exception:
            return False

    def _add_video_locators(self):
        """Кнопка старта загрузки: testid мог смениться — держим текстовые fallback."""
        assert self.page
        return (
            self.page.get_by_test_id("video_upload_placeholder_add_btn"),
            self.page.get_by_role("button", name="Добавить ролик"),
            self.page.locator('button:has-text("Добавить ролик")'),
            self.page.get_by_role("link", name="Добавить ролик"),
            self.page.locator('[data-testid*="upload"][data-testid*="add"]'),
            self.page.locator('a:has-text("Добавить ролик")'),
        )

    async def _find_add_video_button(self, *, timeout_ms: int = 30000):
        """Ждёт появления кнопки добавления ролика (не только testid)."""
        assert self.page
        deadline = datetime.now().timestamp() + (timeout_ms / 1000.0)
        while datetime.now().timestamp() < deadline:
            for loc in self._add_video_locators():
                try:
                    count = await loc.count()
                    if count == 0:
                        continue
                    target = loc.first
                    if await target.is_visible():
                        return target
                except Exception:
                    continue
            # скелетон кабинета — подождать дорисовку
            await self.page.wait_for_timeout(500)
        return None

    async def ensure_logged_in(self) -> bool:
        assert self.page
        await self.page.goto(self.UPLOAD_URL, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await self.page.wait_for_timeout(1500)
        if self._is_auth_url(self.page.url or ""):
            logger.error("Нужен повторный вход: открыт auth URL %s", self.page.url)
            return False
        if not await self._has_session_cookie():
            logger.error("Нет session cookies — сначала «Войти в VK Video»")
            return False
        # Раньше падали сразу, если нет data-testid — а на странице уже была
        # видимая кнопка «Добавить ролик» → браузер закрывался «на старте».
        btn = await self._find_add_video_button(timeout_ms=35000)
        if btn is None:
            await self.screenshot("error_no_add_btn")
            logger.error(
                "Не вижу кнопку «Добавить ролик» за 35с (url=%s). "
                "Возможно скелетон/другой аккаунт — перелогиньтесь в Results UI.",
                self.page.url,
            )
            return False
        logger.info("Сессия OK: %s", self.page.url)
        return True

    def _compose_description(self, *, title: str, description: str, tags: str) -> str:
        parts: list[str] = []
        title = (title or "").strip()
        description = (description or "").strip()
        if title and description and title not in description:
            parts.append(title)
            parts.append("")
            parts.append(description)
        elif description:
            parts.append(description)
        elif title:
            parts.append(title)
        tag_list = [t.strip().lstrip("#") for t in (tags or "").replace(";", ",").split(",") if t.strip()]
        if tag_list:
            parts.append("")
            parts.append(" ".join(f"#{t}" for t in tag_list[:10]))
        text = "\n".join(parts).strip()
        # Клипы VK — описание ограниченное; режем мягко
        return text[:2000]

    async def _close_extra_modal(self, page) -> None:
        try:
            modal = page.get_by_test_id("modalbox")
            if await modal.count() == 0:
                return
            close_btn = modal.get_by_role("button", name="Закрыть")
            if await close_btn.count() > 0 and await close_btn.first.is_visible():
                await close_btn.first.click(timeout=3000)
                logger.info("Закрыл modalbox")
                await page.wait_for_timeout(800)
        except Exception as exc:
            logger.debug("modalbox skip: %s", exc)

    async def _click_add_video(self) -> None:
        """Клик по кнопке старта загрузки (testid или видимый текст)."""
        assert self.page
        target = await self._find_add_video_button(timeout_ms=20000)
        if target is None:
            raise RuntimeError("Кнопка «Добавить ролик» не найдена")
        await target.click(timeout=8000)

    async def _open_upload_popup(self):
        """Открывает popup кабинета автора и ждёт готовности."""
        assert self.page
        try:
            async with self.page.expect_popup(timeout=45000) as popup_info:
                await self._click_add_video()
            upload_page = await popup_info.value
            logger.info("Popup upload: %s", upload_page.url)
        except Exception as exc:
            logger.info("Popup не пойман (%s) — текущая вкладка", exc)
            upload_page = self.page
            try:
                await self._click_add_video()
            except Exception:
                pass
            await self.page.wait_for_timeout(1500)
        try:
            await upload_page.wait_for_load_state("domcontentloaded", timeout=60000)
        except Exception:
            pass
        return upload_page

    async def _wait_upload_ui_ready(self, page, *, timeout_sec: int = 90) -> None:
        """Кабинет автора грузится медленно — ждём picker / file input."""
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            try:
                if await page.get_by_test_id("video_upload_select_file").count() > 0:
                    logger.info("Upload UI ready: video_upload_select_file")
                    return
                if await page.locator("span").filter(has_text="Выбрать файл").count() > 0:
                    logger.info("Upload UI ready: «Выбрать файл»")
                    return
                if await page.locator('input[type="file"]').count() > 0:
                    logger.info("Upload UI ready: input[type=file]")
                    return
            except Exception:
                pass
            await page.wait_for_timeout(1500)
        logger.warning("Upload UI не подтвердил готовность за %ss — пробую дальше", timeout_sec)

    async def _set_video_file(self, page, video_path: Path) -> bool:
        """Прикрепляет MP4 без native dialog: set_input_files или expect_file_chooser."""
        # 1) Прямой input (предпочтительно)
        for _ in range(20):
            file_input = page.get_by_test_id("video_upload_select_file")
            if await file_input.count() == 0:
                file_input = page.locator('input[type="file"]').first
            if await file_input.count() > 0:
                try:
                    await file_input.set_input_files(str(video_path.resolve()))
                    return True
                except Exception as exc:
                    logger.debug("set_input_files retry: %s", exc)
            await page.wait_for_timeout(1000)

        # 2) Клик «Выбрать файл» + перехват chooser (не OS dialog)
        choose = page.locator("span").filter(has_text="Выбрать файл").first
        if await choose.count() > 0:
            try:
                async with page.expect_file_chooser(timeout=15000) as fc_info:
                    await choose.click(timeout=8000)
                chooser = await fc_info.value
                await chooser.set_files(str(video_path.resolve()))
                return True
            except Exception as exc:
                logger.warning("file_chooser path failed: %s", exc)

        # 3) После клика input мог появиться
        file_input = page.get_by_test_id("video_upload_select_file")
        if await file_input.count() == 0:
            file_input = page.locator('input[type="file"]').first
        if await file_input.count() > 0:
            await file_input.set_input_files(str(video_path.resolve()))
            return True
        return False

    async def upload_short_video(
        self,
        *,
        video: str,
        title: str,
        description: str = "",
        cover: str | None = None,
        tags: str = "",
        draft: bool = False,
    ) -> bool:
        assert self.page and self.context
        video_path = Path(video)
        if not video_path.is_file():
            raise FileNotFoundError(video)
        cover_path = Path(cover) if cover else None
        if cover_path and not cover_path.is_file():
            logger.warning("Обложка не найдена: %s", cover)
            cover_path = None

        if not await self.ensure_logged_in():
            return False

        await self.screenshot("step1_upload_page")

        # 1) «Добавить ролик» → popup (как в codegen)
        upload_page = await self._open_upload_popup()
        if upload_page is None:
            return False

        upload_page.set_default_timeout(self.timeout)
        await self._wait_upload_ui_ready(upload_page)
        await upload_page.screenshot(
            path=str(_SHOT_DIR / f"step2_picker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        )

        # 2) Файл без native Windows dialog
        if not await self._set_video_file(upload_page, video_path):
            await upload_page.screenshot(
                path=str(_SHOT_DIR / f"error_no_file_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            )
            logger.error("Не удалось прикрепить видео (нет input / filechooser)")
            return False
        logger.info("video set (no file dialog): %s", video_path.name)
        await upload_page.wait_for_timeout(2500)
        await self._close_extra_modal(upload_page)

        # 3) Ждём форму описания клипа
        desc = upload_page.get_by_test_id("clips-upload-description")
        ready = False
        for _ in range(90):
            if await desc.count() > 0:
                try:
                    if await desc.first.is_visible():
                        ready = True
                        break
                except Exception:
                    pass
            await upload_page.wait_for_timeout(2000)
        if not ready:
            await upload_page.screenshot(
                path=str(_SHOT_DIR / f"error_no_description_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            )
            logger.error("Форма clips-upload-description не появилась")
            return False

        text = self._compose_description(title=title, description=description, tags=tags)
        await desc.click()
        await desc.fill(text)
        logger.info("description filled (%s chars)", len(text))
        await upload_page.wait_for_timeout(800)

        # 4) Ждём окончание обработки — иначе обложка недоступна
        #    Текст на форме: «Выбор обложки будет доступен после обработки клипа»
        await self._wait_clip_processed(upload_page)

        # 5) Кастомная обложка — только после обработки, без native file dialog
        if cover_path:
            cover_ok = await self._attach_cover(upload_page, cover_path)
            if cover_ok:
                logger.info("cover set (no file dialog): %s", cover_path.name)
                await upload_page.wait_for_timeout(1500)
            else:
                logger.warning("Обложку не удалось прикрепить — публикую кадр по умолчанию")

        # 6) «Кнопка действия» — включить (Открыть канал в мессенджере)
        if self.enable_action_button:
            ok = await self._enable_action_button(upload_page)
            if not ok and self.toggle_first_switch:
                try:
                    handle = upload_page.locator(".vkuiSwitch__handle").first
                    if await handle.count() > 0 and await handle.is_visible():
                        await handle.click(timeout=3000)
                        logger.info("fallback: toggled first vkuiSwitch")
                        await upload_page.wait_for_timeout(400)
                except Exception as exc:
                    logger.debug("switch fallback skip: %s", exc)

        await upload_page.screenshot(
            path=str(_SHOT_DIR / f"step4_before_publish_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        )

        # 7) Publish — только когда кнопка активна
        if draft:
            clicked = False
            for name in ("Сохранить как черновик", "Черновик", "Сохранить"):
                try:
                    btn = upload_page.get_by_role("button", name=name)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=5000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                logger.error("Режим draft: кнопка не найдена (в codegen её не было)")
                return False
        else:
            pub = upload_page.get_by_test_id("clips-uploadForm-publish-button")
            if await pub.count() == 0:
                await upload_page.screenshot(
                    path=str(_SHOT_DIR / f"error_no_publish_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                )
                logger.error("Нет clips-uploadForm-publish-button")
                return False
            # Ждём enabled
            enabled = False
            for _ in range(60):
                try:
                    if await pub.is_enabled():
                        enabled = True
                        break
                except Exception:
                    pass
                await upload_page.wait_for_timeout(2000)
            if not enabled:
                await upload_page.screenshot(
                    path=str(_SHOT_DIR / f"error_publish_disabled_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                )
                logger.error("Кнопка «Опубликовать» так и не стала активной")
                return False
            await pub.click()
            logger.info("clicked publish")

        await upload_page.wait_for_timeout(12000)
        await upload_page.screenshot(
            path=str(_SHOT_DIR / f"step5_after_publish_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        )
        await self.save_cookies()
        logger.info("VK Video: %s", "draft" if draft else "published")
        return True

    async def _enable_action_button(self, page) -> bool:
        """Включает тогл «Кнопка действия» (Открыть канал в мессенджере), если выключен."""
        try:
            # Строка настройки по тексту заголовка
            row = page.locator("div, label, li, section").filter(has_text="Кнопка действия").first
            if await row.count() == 0:
                row = page.get_by_text("Кнопка действия", exact=False).locator("..").locator("..")
            # Switch внутри строки или рядом
            switch = row.locator(
                '.vkuiSwitch, [role="switch"], input[type="checkbox"], .vkuiSwitch__handle'
            ).first
            if await switch.count() == 0:
                # Иногда тогл — соседний sibling у блока с текстом
                label = page.get_by_text("Кнопка действия", exact=True)
                if await label.count() > 0:
                    switch = label.locator(
                        "xpath=ancestor::*[.//*[@role='switch'] or .//*[contains(@class,'vkuiSwitch')]][1]"
                        "//*[@role='switch' or contains(@class,'vkuiSwitch') or contains(@class,'vkuiSwitch__handle')]"
                    ).first

            if await switch.count() == 0:
                logger.warning("«Кнопка действия»: switch не найден")
                await page.screenshot(
                    path=str(_SHOT_DIR / f"error_action_button_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                )
                return False

            # Уже включён?
            checked = False
            try:
                aria = await switch.get_attribute("aria-checked")
                if aria is not None:
                    checked = aria == "true"
                else:
                    checked = await switch.evaluate(
                        """el => {
                          const input = el.matches('input') ? el : el.querySelector('input[type=checkbox]');
                          if (input) return !!input.checked;
                          const sw = el.closest('[class*=vkuiSwitch]') || el;
                          return sw.className.includes('--checked') || sw.className.includes('checked')
                            || (sw.getAttribute('aria-checked') === 'true');
                        }"""
                    )
            except Exception:
                checked = False

            if checked:
                logger.info("«Кнопка действия» уже включена")
                return True

            # Клик по handle / switch
            target = switch
            handle = row.locator(".vkuiSwitch__handle").first if await row.count() > 0 else page.locator(
                ".vkuiSwitch__handle"
            ).first
            # Предпочитаем handle рядом с текстом «Кнопка действия»
            try:
                near = page.locator("text=Кнопка действия").locator(
                    "xpath=ancestor::*[contains(@class,'vkui') or self::div][1]"
                    "//*[contains(@class,'vkuiSwitch__handle')]"
                ).first
                if await near.count() > 0:
                    handle = near
            except Exception:
                pass

            if await handle.count() > 0:
                target = handle
            await target.click(timeout=5000, force=True)
            await page.wait_for_timeout(600)
            logger.info("Включил «Кнопка действия»")
            return True
        except Exception as exc:
            logger.warning("«Кнопка действия» не включена: %s", exc)
            await page.screenshot(
                path=str(_SHOT_DIR / f"error_action_button_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            )
            return False

    async def _wait_clip_processed(self, page, *, timeout_sec: int = 300) -> None:
        """Ждём, пока пропадёт «обработка» и станет доступен выбор обложки."""
        deadline = asyncio.get_event_loop().time() + timeout_sec
        processing_markers = (
            "Обработка",
            "обработки клипа",
            "Выбор обложки будет доступен",
            "Клип загружен. Обработка",
        )
        while asyncio.get_event_loop().time() < deadline:
            body = ""
            try:
                body = await page.locator("body").inner_text(timeout=3000)
            except Exception:
                pass
            still = any(m.lower() in body.lower() for m in processing_markers)
            # «Выбрать обложку» / media-attach появились?
            attach_ready = False
            try:
                attach = page.get_by_test_id("media-attach-input")
                btn = page.get_by_role("button", name="Выбрать обложку")
                attach_ready = (await attach.count() > 0) or (await btn.count() > 0)
            except Exception:
                pass
            pub = page.get_by_test_id("clips-uploadForm-publish-button")
            pub_on = False
            try:
                pub_on = await pub.count() > 0 and await pub.is_enabled()
            except Exception:
                pass

            if not still and (attach_ready or pub_on):
                logger.info("Обработка клипа завершена (cover/publish ready)")
                await page.wait_for_timeout(1500)
                return
            left = int(deadline - asyncio.get_event_loop().time())
            if left % 20 < 3:
                logger.info("…ждём обработку клипа (%ss) still=%s attach=%s pub=%s", left, still, attach_ready, pub_on)
            await page.wait_for_timeout(2500)
        logger.warning("Таймаут ожидания обработки — пробую обложку как есть")

    async def _attach_cover(self, page, cover_path: Path) -> bool:
        """Ставит JPG-обложку без native file dialog."""
        # Как в codegen: media-attach-input → button «Выбрать обложку» → set_input_files
        try:
            attach = page.get_by_test_id("media-attach-input")
            if await attach.count() > 0:
                inp = attach.locator('input[type="file"]')
                if await inp.count() > 0:
                    await inp.first.set_input_files(str(cover_path.resolve()))
                    await page.wait_for_timeout(2000)
                    return True
                btn = attach.get_by_role("button", name="Выбрать обложку")
                if await btn.count() > 0:
                    try:
                        await btn.first.set_input_files(str(cover_path.resolve()))
                        await page.wait_for_timeout(2000)
                        return True
                    except Exception:
                        async with page.expect_file_chooser(timeout=15000) as fc_info:
                            await btn.first.click(timeout=8000)
                        chooser = await fc_info.value
                        await chooser.set_files(str(cover_path.resolve()))
                        await page.wait_for_timeout(2000)
                        return True
        except Exception as exc:
            logger.warning("media-attach-input: %s", exc)

        try:
            inp = page.locator('input[type="file"][accept*="image"]')
            if await inp.count() > 0:
                await inp.last.set_input_files(str(cover_path.resolve()))
                await page.wait_for_timeout(2000)
                return True
        except Exception as exc:
            logger.warning("cover image input: %s", exc)

        try:
            btn = page.get_by_role("button", name="Выбрать обложку")
            if await btn.count() > 0:
                try:
                    await btn.first.set_input_files(str(cover_path.resolve()))
                    await page.wait_for_timeout(2000)
                    return True
                except Exception:
                    async with page.expect_file_chooser(timeout=15000) as fc_info:
                        await btn.first.click(timeout=8000)
                    chooser = await fc_info.value
                    await chooser.set_files(str(cover_path.resolve()))
                    await page.wait_for_timeout(2000)
                    return True
        except Exception as exc:
            logger.warning("cover button: %s", exc)

        await page.screenshot(
            path=str(_SHOT_DIR / f"error_cover_attach_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        )
        return False


async def amain() -> int:
    parser = argparse.ArgumentParser(description="VK Video clips — по записи codegen")
    parser.add_argument("--video", "-v")
    parser.add_argument("--title", "-t", default="")
    parser.add_argument("--description", "-d", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--cover", "-c")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--login-only", action="store_true")
    args = parser.parse_args()

    client = VkVideoClient()
    try:
        await client.start()
        if args.login_only:
            ok = await client.ensure_logged_in()
            await client.screenshot("login_check_ok" if ok else "login_check_fail")
            return 0 if ok else 1
        if not args.video:
            logger.error("Нужен --video или --login-only")
            return 2
        ok = await client.upload_short_video(
            video=args.video,
            title=args.title or Path(args.video).stem,
            description=args.description or "",
            cover=args.cover,
            tags=args.tags or "",
            draft=args.draft,
        )
        return 0 if ok else 1
    finally:
        await client.close(force=True)


def main() -> None:
    raise SystemExit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
