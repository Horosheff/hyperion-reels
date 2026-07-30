#!/usr/bin/env python3
"""Playwright-клиент RuTube Shorts по живой записи codegen (2026-07-25).

Сценарий:
  1) studio.rutube.ru/?popup=upload_video
  2) «Выбрать файлы» → set_input_files (без native dialog click)
  3) Название / Описание
  4) Категория: «Технологии и интернет» (env RUTUBE_CATEGORY)
  5) Обложка: иконка upload → label «Shorts» → файл → Готово
  6) Плейлист: выбрать «Вайбкодинг для бизнеса» (НЕ создавать новый)
  7) Дождаться Загрузка 100% + Обработка 100% (не закрывать модалку Escape!)
  8) Опубликовать → дождаться снятия «Не закрывайте страницу»
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
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
_SHOT_DIR = _LOG_DIR / "rutube-screenshots"
_SHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "rutube_autopost.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("rutube_client")

for _env_path in (
    _PLUGIN_ROOT / "videoshorts.local.env",
    _PLUGIN_ROOT / ".env",
    Path.cwd() / "videoshorts.local.env",
    Path.cwd() / ".env",
):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
load_dotenv(override=False)


class RutubeClient:
    STUDIO_UPLOAD = "https://studio.rutube.ru/?popup=upload_video&period=7_days&tab=main"

    def __init__(self) -> None:
        self.channel_id = os.getenv("RUTUBE_CHANNEL_ID", "33566314")
        self.channel_url = os.getenv(
            "RUTUBE_CHANNEL_URL",
            f"https://rutube.ru/channel/{self.channel_id}/",
        )
        default_storage = (
            _PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "rutube_storage_state.json"
        )
        self.storage_state_path = os.getenv(
            "VIDEOSHORTS_RUTUBE_STORAGE",
            os.getenv("RUTUBE_STORAGE_STATE", str(default_storage)),
        )
        self.category = os.getenv("RUTUBE_CATEGORY", "Технологии и интернет")
        self.playlist = os.getenv("RUTUBE_PLAYLIST", "Вайбкодинг для бизнеса")
        self.headless = os.getenv("HEADLESS", "false").lower() == "true"
        self.timeout = int(os.getenv("BROWSER_TIMEOUT", "180000"))
        force_close = os.getenv("VIDEOSHORTS_FORCE_CLOSE_BROWSER", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        self.keep_open = (os.getenv("KEEP_BROWSER_OPEN", "false").lower() == "true") and not force_close
        from browser_humanize import make_humanize

        self.hz = make_humanize(lambda: self.page, "RUTUBE_HUMANIZE", "HUMANIZE", name="rutube")

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def _hclick(self, locator, *, timeout: int = 8000, force: bool = False) -> None:
        await self.hz.click(locator, timeout=timeout, force=force)

    async def _htype(self, locator, text: str) -> None:
        await self.hz.type_text(locator, text)

    async def _hpause(self, lo: float = 0.45, hi: float = 1.2) -> None:
        await self.hz.pause(lo, hi)

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        storage = Path(self.storage_state_path)
        try:
            from playwright_display import chromium_window_args, describe_placement

            launch_args = chromium_window_args(maximize=True)
            logger.info("Display: %s", describe_placement())
        except Exception as exc:
            logger.warning("playwright_display unavailable: %s", exc)
            launch_args = ["--start-maximized"]
        kwargs: dict = {"headless": self.headless, "args": launch_args}
        self.browser = await self.playwright.chromium.launch(**kwargs)
        ctx_kwargs: dict = {"viewport": None}
        if storage.is_file() and storage.stat().st_size > 100:
            ctx_kwargs["storage_state"] = str(storage)
            logger.info("Cookies: %s", storage)
        else:
            logger.warning("Нет cookies RuTube — сначала rutube_login_save.py")
        self.context = await self.browser.new_context(**ctx_kwargs)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        # Chromium/RuTube: «Сохранить часть изменений?» / beforeunload при раннем закрытии
        self.page.on("dialog", self._on_js_dialog)
        logger.info("RuTube browser started · channel=%s · humanize=%s", self.channel_id, self.hz.enabled)

    async def _on_js_dialog(self, dialog) -> None:
        """Не бросать вкладку на mid-upload: Stay/Cancel на leave-site и «часть изменений»."""
        try:
            msg = (dialog.message or "").strip()
            dtype = dialog.type
            low = msg.lower()
            logger.warning("JS dialog (%s): %s", dtype, msg[:200])
            if dtype == "beforeunload" or any(
                s in low
                for s in (
                    "часть изменений",
                    "не сохранятся",
                    "не сохран",
                    "leave",
                    "unsaved",
                    "покинуть",
                    "закрыть сайт",
                )
            ):
                await dialog.dismiss()
                return
            await dialog.accept()
        except Exception as exc:
            logger.debug("dialog handler: %s", exc)

    async def close(self) -> None:
        try:
            if self.page and not self.page.is_closed():
                # Не закрывать, пока висит «Загрузка N%» / «Не закрывайте страницу»
                await self._wait_safe_to_leave(timeout_sec=90)
        except Exception as exc:
            logger.debug("safe leave wait: %s", exc)
        try:
            if self.context:
                await self.save_cookies()
        except Exception:
            pass
        if self.keep_open:
            logger.info("KEEP_BROWSER_OPEN — не закрываю")
            return
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def save_cookies(self) -> None:
        if not self.context:
            return
        path = Path(self.storage_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(path))
        logger.info("Cookies saved → %s", path)

    async def screenshot(self, name: str) -> Path:
        path = _SHOT_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        assert self.page
        await self.page.screenshot(path=str(path), full_page=False)
        logger.info("screenshot: %s", path.name)
        return path

    async def ensure_logged_in(self) -> bool:
        assert self.page
        await self.page.goto(self.STUDIO_UPLOAD, wait_until="domcontentloaded", timeout=120000)
        await self.page.wait_for_timeout(2000)
        url = (self.page.url or "").lower()
        if "multipass/login" in url or "login" in url and "studio" not in url:
            logger.error("Не авторизован (redirect на login). Запустите rutube_login_save.py")
            await self.screenshot("error_not_logged_in")
            return False
        logger.info("Сессия OK: %s", self.page.url)
        return True

    def _compose_description(self, *, title: str, description: str, tags: str) -> str:
        parts: list[str] = []
        desc = (description or "").strip()
        if desc:
            parts.append(desc)
        elif title:
            parts.append(title)
        tag_list = [t.strip().lstrip("#") for t in (tags or "").replace(";", ",").split(",") if t.strip()]
        if tag_list:
            parts.append("")
            parts.append(" ".join(f"#{t}" for t in tag_list[:15]))
        return "\n".join(parts).strip()[:4000]

    async def _set_video_file(self, video_path: Path) -> bool:
        assert self.page
        btn = self.page.get_by_role("button", name="Выбрать файлы")
        # Как в codegen: set_input_files на кнопку (без OS dialog)
        for _ in range(30):
            if await btn.count() > 0:
                try:
                    await btn.first.set_input_files(str(video_path.resolve()))
                    return True
                except Exception as exc:
                    logger.debug("set_input_files on button: %s", exc)
            inp = self.page.locator('input[type="file"]').first
            if await inp.count() > 0:
                try:
                    await inp.set_input_files(str(video_path.resolve()))
                    return True
                except Exception as exc:
                    logger.debug("set_input_files on input: %s", exc)
            # filechooser fallback
            try:
                if await btn.count() > 0:
                    async with self.page.expect_file_chooser(timeout=8000) as fc_info:
                        await self._hclick(btn.first, timeout=5000)
                    chooser = await fc_info.value
                    await chooser.set_files(str(video_path.resolve()))
                    return True
            except Exception as exc:
                logger.debug("filechooser: %s", exc)
            await self.page.wait_for_timeout(1000)
        return False

    async def _wait_form_ready(self, *, timeout_sec: int = 120) -> bool:
        assert self.page
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            title = self.page.get_by_role("textbox", name="Название")
            if await title.count() > 0:
                try:
                    if await title.first.is_visible():
                        return True
                except Exception:
                    pass
            await self.page.wait_for_timeout(1500)
        return False

    async def _select_category(self) -> bool:
        assert self.page
        try:
            # НЕ Escape — закрывает всю модалку upload → виджет «Загрузка видео»
            # и диалог «Сохранить часть изменений» при уходе.
            await self._dismiss_overlays()
            if not await self._upload_form_open():
                logger.error("Форма upload закрыта перед выбором категории")
                await self.screenshot("error_category_form_closed")
                return False

            # Поле категории — чаще combobox / текст текущего значения
            for opener in (
                self.page.get_by_role("combobox").first,
                self.page.locator("label:has-text('Категория')").locator("..").locator("[class*='select'], [role='combobox'], button").first,
                self.page.locator(".svg-icon--IconDsArrowsChevronDown").first,
            ):
                try:
                    if await opener.count() == 0:
                        continue
                    await self._hclick(opener, timeout=5000, force=True)
                    await self.page.wait_for_timeout(400)
                    break
                except Exception:
                    continue

            opt = self.page.get_by_role("option", name=self.category)
            if await opt.count() == 0:
                opt = self.page.get_by_text(self.category, exact=True)
            await self._hclick(opt.first, timeout=8000, force=True)
            logger.info("category: %s", self.category)
            return True
        except Exception as exc:
            logger.warning("Категория не выбрана (%s): %s", self.category, exc)
            await self.screenshot("error_category")
            return False

    async def _upload_form_open(self) -> bool:
        """Модалка редактирования ролика ещё открыта (не схлопнулась в виджет)."""
        assert self.page
        title = self.page.get_by_role("textbox", name="Название")
        if await title.count() == 0:
            return False
        try:
            return bool(await title.first.is_visible())
        except Exception:
            return False

    async def _page_transfer_status(self) -> dict:
        """Статус загрузки/обработки со страницы Studio.

        Важно: «Загрузка N%» ≠ «Обработка N%». Раньше парсили только Обработку,
        а pct=None считали ready → ранний Publish / закрытие вкладки.
        """
        assert self.page
        out: dict = {
            "body": "",
            "upload_pct": None,
            "process_pct": None,
            "dont_close": False,
            "preview_pending": False,
            "link_pending": False,
            "busy": False,
        }
        try:
            body = await self.page.locator("body").inner_text(timeout=3000)
        except Exception:
            return out
        out["body"] = body
        low = body.lower()
        m_up = re.search(r"Загрузка\s+(\d+)\s*%", body, flags=re.I)
        m_pr = re.search(r"Обработка\s+(\d+)\s*%", body, flags=re.I)
        if m_up:
            out["upload_pct"] = int(m_up.group(1))
        if m_pr:
            out["process_pct"] = int(m_pr.group(1))
        out["dont_close"] = "не закрывайте страницу" in low
        out["preview_pending"] = "видео появится после обработки" in low
        out["link_pending"] = "появится после загрузки" in low
        # Виджет «Загрузка видео» на главной без полной формы — тоже busy
        widget_busy = bool(
            re.search(r"Загрузка видео", body, flags=re.I) and not await self._upload_form_open()
        )
        up = out["upload_pct"]
        pr = out["process_pct"]
        out["busy"] = bool(
            out["dont_close"]
            or out["preview_pending"]
            or out["link_pending"]
            or widget_busy
            or (up is not None and up < 100)
            or (pr is not None and pr < 100)
        )
        return out

    async def _processing_percent(self) -> int | None:
        """Совместимость: процент обработки, иначе загрузки."""
        st = await self._page_transfer_status()
        if st["process_pct"] is not None:
            return int(st["process_pct"])
        if st["upload_pct"] is not None:
            return int(st["upload_pct"])
        return None

    async def _dismiss_overlays(self) -> None:
        """Закрыть тултип со ссылкой/copy, не сбрасывая форму через Escape на модалке."""
        assert self.page
        try:
            # Клик по заголовку формы — безопаснее Escape (Escape мог сбрасывать настройки)
            title = self.page.get_by_role("textbox", name="Название")
            if await title.count() > 0:
                await self._hclick(title.first, timeout=2000)
                return
        except Exception:
            pass
        try:
            await self.page.mouse.click(40, 40)
        except Exception:
            pass

    async def _apply_text_fields(self, *, title: str, description: str) -> None:
        assert self.page
        title_box = self.page.get_by_role("textbox", name="Название")
        await self._hclick(title_box)
        await self._htype(title_box, title[:100])
        desc_box = self.page.get_by_role("textbox", name="Описание")
        if await desc_box.count() > 0:
            await self._hclick(desc_box)
            await self._htype(desc_box, description)

    async def _settings_ok(self, *, title: str, playlist: str) -> bool:
        """Проверка, что после ожидания форма не сбросилась."""
        assert self.page
        try:
            title_box = self.page.get_by_role("textbox", name="Название")
            cur = (await title_box.input_value()).strip() if await title_box.count() else ""
            if not cur or cur[:20] != title[:20]:
                logger.warning("Название сброшено: %r", cur[:80])
                return False
        except Exception as exc:
            logger.warning("title check: %s", exc)
            return False
        try:
            body = await self.page.locator("body").inner_text(timeout=3000)
            if playlist and playlist not in body:
                logger.warning("Плейлист не виден на форме: %s", playlist)
                return False
        except Exception:
            pass
        return True

    async def _wait_processing_ready(self, *, timeout_sec: int = 900) -> bool:
        """Ждём ПОЛНУЮ загрузку + обработку. Нельзя считать pct=None = ready.

        Ready только если:
          - форма upload ещё открыта
          - нет «Не закрывайте страницу» / preview pending
          - уже видели upload≥100 или process≥100 (не «процент просто пропал»)
          - кнопка «Опубликовать» enabled
          - 2 стабильных тика подряд
        """
        assert self.page
        deadline = asyncio.get_event_loop().time() + timeout_sec
        saw_upload_100 = False
        saw_process_100 = False
        saw_any_pct = False
        stable_ready = 0
        while asyncio.get_event_loop().time() < deadline:
            if not await self._upload_form_open():
                logger.error(
                    "Модалка upload закрылась во время ожидания "
                    "(Escape/клик снаружи) — виджет «Загрузка видео» не подходит для Publish"
                )
                await self.screenshot("error_upload_modal_closed")
                return False

            st = await self._page_transfer_status()
            up = st["upload_pct"]
            pr = st["process_pct"]
            if up is not None:
                saw_any_pct = True
                if up >= 100:
                    saw_upload_100 = True
            if pr is not None:
                saw_any_pct = True
                if pr >= 100:
                    saw_process_100 = True

            pub = self.page.get_by_role("button", name="Опубликовать")
            enabled = False
            try:
                enabled = await pub.count() > 0 and await pub.first.is_enabled()
            except Exception:
                pass

            # Короткий ролик иногда показывает только «Обработка 100%»
            reached_100 = saw_upload_100 or saw_process_100
            still_transferring = (
                st["dont_close"]
                or st["preview_pending"]
                or (up is not None and up < 100)
                or (pr is not None and pr < 100)
            )
            # pct пропал после 100% — ок; pct пропал на 11% — НЕ ок
            pct_ok = reached_100 and (
                (up is None or up >= 100) and (pr is None or pr >= 100)
            )

            if enabled and pct_ok and not still_transferring and saw_any_pct:
                stable_ready += 1
                if stable_ready >= 2:
                    logger.info(
                        "Обработка ready (upload=%s process=%s saw100_up=%s saw100_pr=%s)",
                        up,
                        pr,
                        saw_upload_100,
                        saw_process_100,
                    )
                    return True
            else:
                stable_ready = 0

            left = int(deadline - asyncio.get_event_loop().time())
            if left % 15 < 3:
                logger.info(
                    "…ждём RuTube upload/process (%ss) upload=%s process=%s "
                    "enabled=%s dont_close=%s preview=%s saw100=%s",
                    left,
                    up,
                    pr,
                    enabled,
                    st["dont_close"],
                    st["preview_pending"],
                    reached_100,
                )
            await self.page.wait_for_timeout(2500)
        logger.error("Таймаут загрузки/обработки — НЕ публикую (чтобы не сбросить настройки)")
        await self.screenshot("error_processing_timeout")
        return False

    async def _wait_safe_to_leave(self, *, timeout_sec: int = 90) -> None:
        """Перед закрытием браузера — дождаться конца «Загрузка N%» / «Не закрывайте»."""
        assert self.page
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            st = await self._page_transfer_status()
            if not st["dont_close"] and not (
                st["upload_pct"] is not None and st["upload_pct"] < 100
            ):
                # виджет «Загрузка видео» без % — подождать ещё чуть-чуть если только что публиковали
                if "загрузка" in st["body"].lower() and "%" in st["body"]:
                    await self.page.wait_for_timeout(2000)
                    continue
                return
            await self.page.wait_for_timeout(2000)
        logger.warning("safe-to-leave: таймаут, закрываю всё равно")

    async def _wait_after_publish(self, *, timeout_sec: int = 120) -> bool:
        """После клика «Опубликовать» — дождаться ухода с формы / снятия «Не закрывайте»."""
        assert self.page
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            st = await self._page_transfer_status()
            form_open = await self._upload_form_open()
            low = st["body"].lower()
            success = any(
                s in low
                for s in (
                    "опубликовано",
                    "видео опубликовано",
                    "успешно",
                    "на модерации",
                )
            )
            if success and not st["dont_close"]:
                logger.info("Publish confirmed by success text")
                return True
            # Форма закрылась и нет «не закрывайте» — обычно ок
            if not form_open and not st["dont_close"]:
                if st["upload_pct"] is None or st["upload_pct"] >= 100:
                    logger.info("Publish: форма закрыта, загрузка не активна")
                    return True
            left = int(deadline - asyncio.get_event_loop().time())
            if left % 15 < 3:
                logger.info(
                    "…после Publish (%ss) form=%s upload=%s dont_close=%s",
                    left,
                    form_open,
                    st["upload_pct"],
                    st["dont_close"],
                )
            await self.page.wait_for_timeout(2500)
        logger.warning("После Publish не дождались явного success — проверяю скрин")
        await self.screenshot("warn_after_publish_timeout")
        # Не фейлим жёстко, если хотя бы нет «Не закрывайте»
        st = await self._page_transfer_status()
        return not st["dont_close"]

    async def _cover_shorts_locator(self):
        """Таб/label Shorts в модалке кадрирования обложки."""
        assert self.page
        shorts = self.page.locator("label").filter(has_text=re.compile(r"^\s*Shorts\s*$"))
        if await shorts.count() == 0:
            shorts = self.page.get_by_role("tab", name="Shorts")
        if await shorts.count() == 0:
            shorts = self.page.get_by_text("Shorts", exact=True)
        return shorts

    async def _cover_shorts_is_active(self) -> bool:
        """Проверка, что в модалке выбран Shorts, а не «Видео»."""
        assert self.page
        try:
            return bool(
                await self.page.evaluate(
                    """() => {
                      const labels = Array.from(document.querySelectorAll('label'));
                      const shorts = labels.find(l => (l.textContent || '').trim() === 'Shorts');
                      const video = labels.find(l => (l.textContent || '').trim() === 'Видео');
                      if (!shorts) return false;
                      const looksOn = (el) => {
                        if (!el) return false;
                        const aria = (el.getAttribute('aria-checked')
                          || el.getAttribute('aria-selected')
                          || el.getAttribute('aria-pressed') || '').toLowerCase();
                        if (aria === 'true' || aria === '1') return true;
                        const input = el.querySelector('input[type="radio"], input[type="checkbox"]');
                        if (input && input.checked) return true;
                        const cls = (el.className || '').toString().toLowerCase();
                        if (/(^|\\s)(active|checked|selected|pressed)(\\s|$)/.test(cls)) return true;
                        const cs = getComputedStyle(el);
                        const bg = cs.backgroundColor || '';
                        const m = bg.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
                        if (m) {
                          const bright = (+m[1] + +m[2] + +m[3]) / 3;
                          return bright > 230;
                        }
                        return false;
                      };
                      const brightOf = (el) => {
                        if (!el) return 0;
                        const cs = getComputedStyle(el);
                        const bg = cs.backgroundColor || '';
                        const m = bg.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
                        if (!m) return 0;
                        return (+m[1] + +m[2] + +m[3]) / 3;
                      };
                      const sOn = looksOn(shorts);
                      const vOn = looksOn(video);
                      if (sOn && !vOn) return true;
                      if (sOn) return true;
                      // Studio: активный сегмент светлее неактивного
                      const sb = brightOf(shorts);
                      const vb = brightOf(video);
                      if (sb > 0 && vb > 0 && sb > vb + 15) return true;
                      return false;
                    }"""
                )
            )
        except Exception:
            return False

    async def _select_cover_shorts_tab(self) -> bool:
        """Кликает Shorts даже когда img[alt=Crop me] перехватывает pointer events.

        Важно: детект «активности» в Studio нестабилен (классы без active).
        Если force-click прошёл без исключения — считаем Shorts выбранным и
        подтверждаем скрином; иначе ложно abort'им уже выбранный Shorts.
        """
        assert self.page
        shorts = await self._cover_shorts_locator()
        if await shorts.count() == 0:
            logger.warning("Shorts label не найден в модалке обложки")
            return False
        target = shorts.first
        clicked = False
        for attempt in range(1, 4):
            try:
                await self._hclick(target, timeout=5000, force=True)
                clicked = True
            except Exception as exc:
                logger.warning("Shorts force-click attempt %s: %s", attempt, exc)
                try:
                    await target.evaluate("el => el.click()")
                    clicked = True
                except Exception as exc2:
                    logger.warning("Shorts JS-click attempt %s: %s", attempt, exc2)
            try:
                await self.page.evaluate(
                    """() => {
                      const labels = Array.from(document.querySelectorAll('label'));
                      const shorts = labels.find(l => (l.textContent || '').trim() === 'Shorts');
                      if (!shorts) return false;
                      shorts.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
                      const input = shorts.querySelector('input');
                      if (input) {
                        input.checked = true;
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                      }
                      return true;
                    }"""
                )
            except Exception:
                pass
            await self.page.wait_for_timeout(500)
            if await self._cover_shorts_is_active():
                logger.info("cover format: Shorts (detected, attempt %s)", attempt)
                await self.screenshot(f"cover_shorts_selected_{attempt}")
                return True
        if clicked:
            # Studio UI: на скринах Shorts уже белый, а CSS-детект врёт → не abort
            logger.warning(
                "CSS-детект Shorts не подтвердил, но force-click выполнен — продолжаю (см. screenshot)"
            )
            await self.screenshot("cover_shorts_force_assumed")
            return True
        await self.screenshot("error_cover_shorts_not_active")
        return False

    async def _attach_cover(self, cover_path: Path) -> bool:
        """Обложка как в первом рабочем прогоне: «Загрузить свою» → Shorts → файл → Готово.

        НЕ трогаем IconDsMainUpload на странице — это главный upload видео и сбрасывает форму.
        """
        assert self.page
        try:
            # Снять фокус с тултипов
            await self._dismiss_overlays()
            await self.page.wait_for_timeout(300)

            # 1) Только «Загрузить свою» в блоке обложки (как в первой записи)
            upload_own = self.page.locator("div").filter(has_text=re.compile(r"^Загрузить свою$"))
            if await upload_own.count() == 0:
                upload_own = self.page.get_by_text("Загрузить свою", exact=True)
            # В codegen был nth(1) — если один элемент, берём first
            target = upload_own.nth(1) if await upload_own.count() > 1 else upload_own.first
            if await target.count() == 0:
                logger.error("Нет «Загрузить свою» для обложки")
                await self.screenshot("error_cover_no_upload_own")
                return False

            file_set = False
            try:
                async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                    await self._hclick(target, timeout=8000)
                chooser = await fc_info.value
                await chooser.set_files(str(cover_path.resolve()))
                file_set = True
                logger.info("cover file via «Загрузить свою»")
            except Exception:
                await self._hclick(target, timeout=8000)
                logger.info("«Загрузить свою» clicked (chooser later)")

            await self.page.wait_for_timeout(700)

            # 2) Shorts — внутри модалки «Кадрирование обложки».
            # После выбора файла кроп (img[alt="Crop me"]) перехватывает обычный click —
            # нужен force / JS. Без Shorts RuTube ставит горизонтальную «Видео»-обложку.
            shorts_ok = await self._select_cover_shorts_tab()
            if not shorts_ok:
                logger.error("Не удалось выбрать таб Shorts для обложки")
                await self.screenshot("error_cover_shorts_not_selected")
                return False

            # 3) Если файл ещё не ушёл — input[type=file] в модалке (accept image)
            if not file_set:
                inp = self.page.locator(
                    'input[type="file"][accept*="image"], input[type="file"][accept*="jpg"], input[type="file"]'
                )
                if await inp.count() > 0:
                    await inp.last.set_input_files(str(cover_path.resolve()))
                    file_set = True
                    logger.info("cover set_input_files (modal)")
                else:
                    try:
                        async with self.page.expect_file_chooser(timeout=8000) as fc_info:
                            # повторный клик по Загрузить свою внутри модалки
                            again = self.page.get_by_text("Загрузить свою", exact=True)
                            await self._hclick(again.last, timeout=5000)
                        chooser = await fc_info.value
                        await chooser.set_files(str(cover_path.resolve()))
                        file_set = True
                        logger.info("cover file via second chooser")
                    except Exception as exc:
                        logger.warning("cover file not set: %s", exc)
                # После поздней загрузки файла снова убедиться, что Shorts активен
                if not await self._select_cover_shorts_tab():
                    logger.error("Shorts сбросился после загрузки файла")
                    await self.screenshot("error_cover_shorts_lost")
                    return False

            # 4) Готово — Shorts уже выбран через _select_cover_shorts_tab (force-click)
            done = self.page.get_by_role("button", name="Готово")
            if await done.count() == 0:
                logger.error("Нет кнопки «Готово» в модалке обложки")
                await self.screenshot("error_cover_no_done")
                return False
            await self._hclick(done.first, timeout=8000)
            logger.info(
                "cover set (Загрузить свою + Shorts): %s file=%s shorts=True",
                cover_path.name,
                file_set,
            )

            # Проверка: название не должно сброситься
            await self.page.wait_for_timeout(800)
            return True
        except Exception as exc:
            logger.warning("Обложка не прикреплена: %s", exc)
            await self.screenshot("error_cover")
            return False

    async def _select_playlist(self) -> bool:
        """Выбрать существующий плейлист. НЕ создавать новый."""
        assert self.page
        try:
            await self._hclick(self.page.get_by_text("Выберите плейлист"), timeout=8000)
            await self.page.wait_for_timeout(600)
            opt = self.page.get_by_role("option", name=self.playlist)
            if await opt.count() == 0:
                opt = self.page.get_by_text(self.playlist, exact=True)
            if await opt.count() == 0:
                logger.error("Плейлист не найден: %s (создание новых запрещено)", self.playlist)
                await self.screenshot("error_playlist_missing")
                return False
            await self._hclick(opt.first, timeout=8000)
            logger.info("playlist: %s", self.playlist)
            return True
        except Exception as exc:
            logger.warning("Плейлист не выбран: %s", exc)
            await self.screenshot("error_playlist")
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

        await self.screenshot("step1_upload_popup")

        if not await self._set_video_file(video_path):
            await self.screenshot("error_no_file_input")
            logger.error("Не удалось прикрепить видео")
            return False
        logger.info("video set: %s", video_path.name)
        await self._hpause(1.2, 2.4)

        if not await self._wait_form_ready():
            await self.screenshot("error_no_form")
            logger.error("Форма названия/описания не появилась")
            return False

        final_title = (title or video_path.stem)[:100]
        desc_text = self._compose_description(title=title, description=description, tags=tags)
        await self._hpause(0.5, 1.1)
        await self._apply_text_fields(title=final_title, description=desc_text)
        logger.info("title/description filled")

        await self._dismiss_overlays()
        await self._hpause(0.4, 0.9)
        if not await self._upload_form_open():
            logger.error("Форма upload закрылась до категории — стоп")
            await self.screenshot("error_form_closed_before_category")
            return False
        await self._select_category()

        if cover_path:
            await self._hpause(0.5, 1.0)
            if not await self._upload_form_open():
                logger.error("Форма upload закрылась до обложки — стоп")
                await self.screenshot("error_form_closed_before_cover")
                return False
            cover_ok = await self._attach_cover(cover_path)
            if not cover_ok:
                logger.error("Обложка Shorts не установлена — публикацию останавливаю")
                await self.screenshot("error_cover_abort_publish")
                return False
            # Не кликаем главный Upload повторно. Категорию после обложки только если сбилась.
            try:
                body = await self.page.locator("body").inner_text(timeout=2000)
                if self.category not in body:
                    await self._select_category()
            except Exception:
                pass

        await self._hpause(0.4, 0.9)
        if not await self._upload_form_open():
            logger.error("Форма upload закрылась до плейлиста — стоп")
            await self.screenshot("error_form_closed_before_playlist")
            return False
        playlist_ok = await self._select_playlist()
        if not playlist_ok:
            logger.warning("Публикую без плейлиста (создание новых отключено)")

        await self._dismiss_overlays()

        # Ждём ПОЛНУЮ загрузку+обработку — ранний Publish / закрытие → «Сохранить часть изменений»
        ready = await self._wait_processing_ready()
        if not ready:
            return False

        # Перед Publish — если форма сбилась, восстановить текст/категорию/плейлист
        # (обложку НЕ ставим повторно — повторный upload сбрасывает форму)
        if not await self._settings_ok(title=final_title, playlist=self.playlist):
            logger.warning("Настройки сбились после обработки — восстанавливаю текст/категорию/плейлист")
            await self._apply_text_fields(title=final_title, description=desc_text)
            await self._select_category()
            await self._select_playlist()
            await self._dismiss_overlays()

        await self.screenshot("step4_before_publish")
        await self._hpause(0.6, 1.4)

        if draft:
            for name in ("Сохранить как черновик", "Черновик", "Сохранить"):
                btn = self.page.get_by_role("button", name=name)
                if await btn.count() > 0:
                    await self._hclick(btn.first, timeout=8000)
                    logger.info("draft: %s", name)
                    break
            else:
                logger.error("Кнопка черновика не найдена")
                return False
        else:
            pub = self.page.get_by_role("button", name="Опубликовать")
            if await pub.count() == 0:
                await self.screenshot("error_no_publish")
                logger.error("Нет кнопки Опубликовать")
                return False
            # Только если реально enabled — без force
            for _ in range(30):
                try:
                    if await pub.first.is_enabled():
                        break
                except Exception:
                    pass
                await self.page.wait_for_timeout(2000)
            else:
                await self.screenshot("error_publish_disabled")
                logger.error("Опубликовать так и не стала активной — стоп (настройки не трогаем)")
                return False

            # Финальная проверка перед кликом
            if not await self._settings_ok(title=final_title, playlist=self.playlist):
                await self.screenshot("error_settings_lost_before_publish")
                logger.error("Настройки пропали прямо перед Publish — стоп")
                return False

            # Надёжный клик «Опубликовать»: обычный → force → JS.
            # Ранее один human click иногда «не нажимался» (INC: не нажата кнопка публикации).
            publish_clicked = False
            try:
                await self._hclick(pub.first, timeout=8000)
                publish_clicked = True
                logger.info("clicked publish (human click)")
            except Exception as exc:
                logger.warning("human publish click failed: %s — пробую force/JS", exc)
                for attempt in range(2):
                    try:
                        await self._hclick(pub.first, timeout=5000, force=True)
                        publish_clicked = True
                        logger.info("clicked publish (force click %s)", attempt + 1)
                        break
                    except Exception as fexc:
                        logger.warning("force publish click %s failed: %s", attempt + 1, fexc)
                        try:
                            await pub.first.evaluate("el => el.click()")
                            publish_clicked = True
                            logger.info("clicked publish (JS click %s)", attempt + 1)
                            break
                        except Exception as jexc:
                            logger.warning("JS publish click %s failed: %s", attempt + 1, jexc)
                            await self.page.wait_for_timeout(800)
            if not publish_clicked:
                await self.screenshot("error_publish_click")
                logger.error("Не удалось кликнуть «Опубликовать» ни одним способом")
                return False
            logger.info("clicked publish (after full upload+processing + settings check)")

        ok_after = await self._wait_after_publish()
        await self.screenshot("step5_after_publish")
        await self.save_cookies()
        if not ok_after:
            logger.error("После Publish страница всё ещё в состоянии загрузки")
            return False
        logger.info("RuTube: %s", "draft" if draft else "published")
        return True


async def amain() -> int:
    parser = argparse.ArgumentParser(description="RuTube Shorts — по записи codegen")
    parser.add_argument("--video", "-v")
    parser.add_argument("--title", "-t", default="")
    parser.add_argument("--description", "-d", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--cover", "-c")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--login-only", action="store_true")
    args = parser.parse_args()

    client = RutubeClient()
    try:
        await client.start()
        if args.login_only:
            ok = await client.ensure_logged_in()
            await client.screenshot("login_check_ok" if ok else "login_check_fail")
            return 0 if ok else 1
        if not args.video:
            logger.error("Нужен --video")
            return 2
        ok = await client.upload_short_video(
            video=args.video,
            title=args.title or Path(args.video).stem,
            description=args.description,
            cover=args.cover,
            tags=args.tags,
            draft=args.draft,
        )
        return 0 if ok else 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
