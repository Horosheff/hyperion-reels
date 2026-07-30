#!/usr/bin/env python3
"""Playwright-клиент YouTube Studio Shorts по живой записи codegen (2026-07-28).

Сценарий (youtube_publish_codegen.py):
  1) studio.youtube.com (/channel/…)
  2) «Создать» → «Добавить видео»
  3) «Выбрать файлы» → set_input_files (без OS dialog)
  4) Название / Описание
  5) Обложка: «Загрузить файл»
  6) Плейлист (env YOUTUBE_PLAYLIST) — опционально
  7) Доп. настройки: «Нет, ИИ не использовался» + теги + категория
  8) Далее → проверки → «Открытый доступ» → «Опубликовать»
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
_SHOT_DIR = _LOG_DIR / "youtube-screenshots"
_SHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "youtube_autopost.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("youtube_client")

for _env_path in (
    _PLUGIN_ROOT / "videoshorts.local.env",
    _PLUGIN_ROOT / ".env",
    Path.cwd() / "videoshorts.local.env",
    Path.cwd() / ".env",
):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
load_dotenv(override=False)


class YoutubeClient:
    STUDIO_URL = "https://studio.youtube.com/"

    def __init__(self) -> None:
        self.channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
        self.channel_url = os.getenv("YOUTUBE_CHANNEL_URL", "").strip()
        if not self.channel_url and self.channel_id:
            self.channel_url = f"https://studio.youtube.com/channel/{self.channel_id}"
        default_storage = (
            _PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "youtube_storage_state.json"
        )
        self.storage_state_path = os.getenv(
            "VIDEOSHORTS_YOUTUBE_STORAGE",
            os.getenv("YOUTUBE_STORAGE_STATE", str(default_storage)),
        )
        self.category = os.getenv("YOUTUBE_CATEGORY", "Наука и техника")
        # Несколько плейлистов: "Cursor,Туториал" или "Cursor|Tutorial"
        raw_pl = os.getenv("YOUTUBE_PLAYLIST", "").strip()
        self.playlists = [
            p.strip()
            for p in re.split(r"[,|;]+", raw_pl)
            if p.strip()
        ]
        self.playlist = ", ".join(self.playlists)  # для логов / совместимости
        self.title_hashtag_limit = int(os.getenv("YOUTUBE_TITLE_HASHTAGS", "3") or "3")
        # Фиксированный CTA в описании всех роликов
        self.description_cta = os.getenv(
            "YOUTUBE_DESCRIPTION_CTA",
            "Ковчег — автоматизация с AI-агентами:\nhttps://t.me/maya_pro",
        ).strip()
        self.made_for_kids = os.getenv("YOUTUBE_MADE_FOR_KIDS", "no").strip().lower() in {
            "1",
            "true",
            "yes",
            "да",
        }
        self.ai_used = os.getenv("YOUTUBE_AI_USED", "no").strip().lower() in {
            "1",
            "true",
            "yes",
            "да",
        }
        # Шаг «Подходит ли видео для рекламы» (self-certification): none / some / sensitive
        self.ad_suitability = os.getenv("YOUTUBE_AD_SUITABILITY", "none").strip().lower()
        self.headless = os.getenv("HEADLESS", "false").lower() == "true"
        self.timeout = int(os.getenv("BROWSER_TIMEOUT", "180000"))
        force_close = os.getenv("VIDEOSHORTS_FORCE_CLOSE_BROWSER", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        self.keep_open = (os.getenv("KEEP_BROWSER_OPEN", "false").lower() == "true") and not force_close
        from browser_humanize import make_humanize

        self.hz = make_humanize(lambda: self.page, "YOUTUBE_HUMANIZE", "HUMANIZE", name="youtube")

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.last_video_id: str | None = None

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

            launch_args = chromium_window_args(maximize=True) + [
                "--disable-blink-features=AutomationControlled"
            ]
            logger.info("Display: %s", describe_placement())
        except Exception as exc:
            logger.warning("playwright_display unavailable: %s", exc)
            launch_args = [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ]
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless, args=launch_args
        )
        ctx_kwargs: dict = {
            "viewport": None,
            "locale": os.getenv("YOUTUBE_LOCALE", "ru-RU"),
            "timezone_id": os.getenv("YOUTUBE_TZ", "Europe/Moscow"),
        }
        if storage.is_file() and storage.stat().st_size > 100:
            ctx_kwargs["storage_state"] = str(storage)
            logger.info("Cookies: %s", storage)
        else:
            logger.warning("Нет cookies YouTube — сначала youtube_login_save.py")
        self.context = await self.browser.new_context(**ctx_kwargs)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        logger.info(
            "YouTube browser started · channel=%s · humanize=%s · slot=%s",
            self.channel_id or "(auto)",
            self.hz.enabled,
            os.getenv("VIDEOSHORTS_WINDOW_SLOT") or "0",
        )

    async def close(self) -> None:
        try:
            if self.context:
                await self.save_cookies()
        except Exception:
            pass
        if self.keep_open:
            logger.info("KEEP_BROWSER_OPEN — не закрываю")
            return
        for obj in (self.context, self.browser):
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

    async def save_cookies(self) -> None:
        if not self.context:
            return
        try:
            path = Path(self.storage_state_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            await self.context.storage_state(path=str(path))
            logger.info("Cookies saved → %s", path)
        except Exception as exc:
            logger.warning("save_cookies skipped: %s", exc)

    async def screenshot(self, name: str) -> Path | None:
        path = _SHOT_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if not self.page:
            return None
        try:
            await self.page.screenshot(path=str(path), full_page=False)
            logger.info("screenshot: %s", path.name)
            return path
        except Exception as exc:
            logger.warning("screenshot %s skipped: %s", name, exc)
            return None

    async def _dismiss_autocomplete(self) -> None:
        """Снять фокус с dropdown хештегов/тегов.

        Запрещено:
        - Escape — закрывает всю модалку загрузки → черновик;
        - клик по #dialog-title / шапке / «Информация» — легко попасть в ✕ или увести UI.
        Безопасно: клик в поле описания или названия внутри формы.
        """
        assert self.page
        safe = [
            self.page.locator("ytcp-uploads-dialog #description-textarea #textbox"),
            self.page.locator("ytcp-uploads-dialog #description-wrapper #textbox"),
            self.page.get_by_role(
                "textbox",
                name=re.compile(r"Расскажите, о чем|Tell viewers about your video", re.I),
            ),
            self.page.locator("ytcp-uploads-dialog #textbox").nth(0),
            self.page.get_by_role(
                "textbox",
                name=re.compile(r"Укажите название|Add a title", re.I),
            ),
        ]
        for loc in safe:
            try:
                if await loc.count() == 0:
                    continue
                el = loc.first
                if not await el.is_visible():
                    continue
                await el.click(timeout=1500, force=True)
                await self.page.wait_for_timeout(120)
                return
            except Exception:
                continue
        # последний шанс: Tab уводит фокус с option, не закрывая модалку
        try:
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(80)
        except Exception:
            pass

    async def _uploads_dialog_open(self) -> bool:
        """Есть ли ещё форма загрузки (не дашборд Studio)."""
        assert self.page
        # Кастомный тег ytcp-uploads-dialog часто count>0, но is_visible()=False
        # (host нулевого размера). Смотрим count и дочерние поля.
        for _ in range(3):
            try:
                host = self.page.locator("ytcp-uploads-dialog")
                if await host.count() > 0:
                    return True
            except Exception:
                pass
            probes = [
                self.page.locator("ytcp-uploads-dialog #textbox"),
                self.page.locator("#title-textarea #textbox"),
                self.page.get_by_role(
                    "textbox",
                    name=re.compile(r"название|Add a title|title", re.I),
                ),
                self.page.get_by_role(
                    "button",
                    name=re.compile(r"^Далее$|^Next$", re.I),
                ),
                self.page.get_by_text(re.compile(r"Загрузка видео|Upload videos", re.I)),
            ]
            for loc in probes:
                try:
                    if await loc.count() == 0:
                        continue
                    try:
                        if await loc.first.is_visible():
                            return True
                    except Exception:
                        return True
                except Exception:
                    continue
            await self.page.wait_for_timeout(250)
        return False

    def _studio_home(self) -> str:
        if self.channel_url:
            return self.channel_url
        return self.STUDIO_URL

    async def ensure_logged_in(self) -> bool:
        assert self.page
        await self.page.goto(self._studio_home(), wait_until="domcontentloaded", timeout=120000)
        await self.page.wait_for_timeout(2000)
        url = (self.page.url or "").lower()
        if "accounts.google.com" in url or "servicelogin" in url:
            logger.error("Не авторизован (Google login). Запустите youtube_login_save.py")
            await self.screenshot("error_not_logged_in")
            return False
        if "studio.youtube.com" not in url and "youtube.com" not in url:
            logger.error("Неожиданный URL после входа: %s", self.page.url)
            await self.screenshot("error_unexpected_url")
            return False
        logger.info("Сессия OK: %s", self.page.url)
        return True

    @staticmethod
    def _normalize_tag_list(raw: str | list[str] | None, *, limit: int = 30) -> list[str]:
        if isinstance(raw, list):
            items = [str(t) for t in raw]
        elif isinstance(raw, str):
            items = re.split(r"[\s,;]+", raw)
        else:
            items = []
        out: list[str] = []
        seen: set[str] = set()
        for t in items:
            t = t.strip().lstrip("#")
            if not t:
                continue
            key = t.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
            if len(out) >= limit:
                break
        return out

    @classmethod
    def _extract_hashtags(cls, text: str) -> list[str]:
        found = re.findall(r"#([\w\u0400-\u04FF]+)", text or "", flags=re.UNICODE)
        return cls._normalize_tag_list(found)

    @staticmethod
    def _strip_hashtags(text: str) -> str:
        """Убрать #теги из текста (в т.ч. хвост из одних хештегов), без дублей в описании."""
        if not text:
            return ""
        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append("")
                continue
            # строка только из хештегов / ключей «Ключи: …»
            tokens = stripped.split()
            if tokens and all(t.startswith("#") for t in tokens):
                continue
            if re.match(r"^ключ(и|евые слова)?\s*:", stripped, flags=re.I):
                continue
            cleaned = re.sub(r"(?<!\w)#[\w\u0400-\u04FF]+\b", "", line)
            cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).rstrip()
            if cleaned.strip():
                lines.append(cleaned)
            elif not cleaned.strip() and lines and lines[-1] != "":
                lines.append("")
        # схлопнуть лишние пустые строки
        out: list[str] = []
        for line in lines:
            if line == "" and (not out or out[-1] == ""):
                continue
            out.append(line)
        return "\n".join(out).strip()

    def _build_title_with_hashtags(self, *, title: str, tags: str) -> tuple[str, list[str]]:
        """Название + до N хештегов (лимит YouTube в title = 3). Возвращает (title, tag_list)."""
        raw_title = (title or "").strip()
        from_title = self._extract_hashtags(raw_title)
        clean_title = self._strip_hashtags(raw_title) or raw_title
        # убрать висячие пробелы/двоеточия после strip
        clean_title = re.sub(r"\s{2,}", " ", clean_title).strip(" -–—|")
        tag_list = self._normalize_tag_list(tags) or from_title
        # приоритет: явные tags, затем из title
        merged = self._normalize_tag_list([*tag_list, *from_title])
        limit = max(0, min(self.title_hashtag_limit, 3))
        title_tags = merged[:limit]
        # влезаем в 100 символов Studio
        base = clean_title[:100]
        if title_tags:
            suffix = " " + " ".join(f"#{t}" for t in title_tags)
            # если не влезает — укорачиваем base
            max_base = 100 - len(suffix)
            if max_base < 10:
                # слишком длинные теги — режем число тегов
                while title_tags and max_base < 10:
                    title_tags = title_tags[:-1]
                    suffix = (" " + " ".join(f"#{t}" for t in title_tags)) if title_tags else ""
                    max_base = 100 - len(suffix) if suffix else 100
            base = (clean_title[:max_base]).rstrip()
            final = (base + suffix).strip()[:100]
        else:
            final = base[:100]
        return final, merged

    def _compose_description(self, *, title: str, description: str, tags: str) -> str:
        """Описание без хештегов + CTA Telegram (Ковчег). 3 тега — в title, остальное — в «Теги»."""
        desc = self._strip_hashtags((description or "").strip())
        if not desc:
            desc = self._strip_hashtags((title or "").strip())
        cta = (self.description_cta or "").strip()
        if cta and "t.me/maya_pro" not in desc.casefold():
            desc = f"{desc}\n\n{cta}".strip() if desc else cta
        return desc[:5000]

    async def _open_upload_dialog(self) -> bool:
        assert self.page
        create = self.page.get_by_role("button", name="Создать", exact=True)
        if await create.count() == 0:
            create = self.page.get_by_role("button", name="Create", exact=True)
        if await create.count() == 0:
            create = self.page.locator("#create-icon")
        if await create.count() == 0:
            logger.error("Нет кнопки «Создать»")
            return False
        await self._hclick(create.first, timeout=10000)
        await self._hpause(0.4, 0.9)

        add = self.page.get_by_text("Добавить видео", exact=True)
        if await add.count() == 0:
            add = self.page.get_by_text("Upload videos", exact=True)
        if await add.count() == 0:
            add = self.page.get_by_text("Upload video", exact=False)
        if await add.count() == 0:
            logger.error("Нет пункта «Добавить видео»")
            return False
        await self._hclick(add.first, timeout=8000)
        await self._hpause(0.6, 1.2)
        return True

    async def _set_video_file(self, video_path: Path) -> bool:
        assert self.page
        btn = self.page.get_by_role("button", name="Выбрать файлы")
        if await btn.count() == 0:
            btn = self.page.get_by_role("button", name="Select files")
        for _ in range(40):
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

    async def _wait_details_form(self, *, timeout_sec: int = 180) -> bool:
        assert self.page
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            title = self.page.get_by_role(
                "textbox",
                name=re.compile(r"Укажите название|Add a title|title", re.I),
            )
            if await title.count() > 0:
                try:
                    if await title.first.is_visible():
                        return True
                except Exception:
                    pass
            await self.page.wait_for_timeout(1500)
        return False

    async def _fill_title_description(
        self,
        *,
        title: str,
        description: str,
        preferred_hashtags: list[str] | None = None,
    ) -> list[str]:
        """Название без #; до 3 хештегов — клик по «Рекомендуемые хештеги»; потом описание."""
        assert self.page
        clean_title = self._strip_hashtags(title or "").strip() or (title or "")[:100]
        clean_title = re.sub(r"\s{2,}", " ", clean_title).strip(" -–—|")[:100]

        title_box = self.page.get_by_role(
            "textbox",
            name=re.compile(r"Укажите название|Add a title", re.I),
        )
        await title_box.first.click(timeout=5000, force=True)
        await title_box.first.fill("")
        await self._htype(title_box.first, clean_title)
        await self._hpause(0.4, 0.8)

        picked = await self._pick_title_hashtags_from_suggestions(
            preferred_hashtags or [],
            limit=self.title_hashtag_limit,
        )

        await self._fill_description_field(description or "")

        logger.info(
            "title/description filled · title_hashtags_from_recommended=%s",
            " ".join(f"#{t}" for t in picked) or "(none)",
        )
        return picked

    async def _list_recommended_hashtag_buttons(self):
        """Чипы блока «Рекомендуемые хештеги» под названием (как в codegen)."""
        assert self.page
        header = self.page.get_by_text(
            re.compile(r"Рекомендуемые хештеги|Suggested hashtags", re.I)
        )
        for _ in range(24):
            try:
                if await header.count() > 0 and await header.first.is_visible():
                    try:
                        await header.first.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    break
            except Exception:
                pass
            await self._scroll_uploads_dialog(delta=220)
            await self.page.wait_for_timeout(400)

        # как в codegen — клик по заголовку блока (фокус/раскрытие)
        try:
            if await header.count() > 0 and await header.first.is_visible():
                await header.first.click(timeout=2000, force=True)
                await self.page.wait_for_timeout(200)
        except Exception:
            pass

        buttons = self.page.get_by_role("button").filter(
            has_text=re.compile(r"#[\w\u0400-\u04FF]", re.UNICODE)
        )
        aria_btns = self.page.locator(
            "button[aria-label*='#'], ytcp-button[aria-label*='#'], "
            "[role='button'][aria-label*='#']"
        )
        out: list[tuple[str, object]] = []
        seen: set[str] = set()
        for loc in (buttons, aria_btns):
            try:
                n = await loc.count()
            except Exception:
                continue
            for i in range(min(n, 40)):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    label = (
                        (await el.get_attribute("aria-label"))
                        or (await el.inner_text())
                        or ""
                    )
                    low = label.casefold()
                    if any(
                        s in low
                        for s in (
                            "загрузить",
                            "upload",
                            "далее",
                            "next",
                            "опубликовать",
                            "publish",
                        )
                    ):
                        continue
                    m = re.search(r"#([\w\u0400-\u04FF]+)", label, flags=re.UNICODE)
                    if not m:
                        continue
                    tag = m.group(1)
                    key = tag.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((tag, el))
                except Exception:
                    continue
        return out

    async def _pick_title_hashtags_from_suggestions(
        self,
        preferred: list[str],
        *,
        limit: int = 3,
    ) -> list[str]:
        """До N хештегов — только клики по recommended chips (без набора # в title)."""
        assert self.page
        limit = max(0, min(int(limit or 3), 3))
        if limit == 0:
            return []

        preferred_cf = [
            t.strip().lstrip("#").casefold()
            for t in preferred
            if t and str(t).strip()
        ]

        chips = await self._list_recommended_hashtag_buttons()
        if not chips:
            logger.warning("Нет «Рекомендуемые хештеги» — title без #")
            await self.screenshot("warn_no_title_hashtag_chips")
            return []

        logger.info(
            "recommended hashtag chips: %s",
            ", ".join(f"#{t}" for t, _ in chips[:12]),
        )

        picked: list[str] = []
        picked_cf: set[str] = set()

        async def click_chip(tag: str, el) -> bool:
            try:
                await el.scroll_into_view_if_needed(timeout=3000)
                await el.click(timeout=4000, force=True)
                await self.page.wait_for_timeout(280)
                return True
            except Exception as exc:
                logger.debug("chip click #%s: %s", tag, exc)
                return False

        # 1) если наш тег есть среди recommended — кликаем его
        for want in preferred_cf:
            if len(picked) >= limit:
                break
            for tag, el in chips:
                if tag.casefold() == want or tag.casefold().startswith(want):
                    if tag.casefold() in picked_cf:
                        continue
                    if await click_chip(tag, el):
                        picked.append(tag)
                        picked_cf.add(tag.casefold())
                        logger.info("title hashtag recommended: #%s", tag)
                    break

        # 2) добить до limit первыми доступными чипами YouTube
        if len(picked) < limit:
            chips = await self._list_recommended_hashtag_buttons()
            for tag, el in chips:
                if len(picked) >= limit:
                    break
                if tag.casefold() in picked_cf:
                    continue
                if await click_chip(tag, el):
                    picked.append(tag)
                    picked_cf.add(tag.casefold())
                    logger.info("title hashtag recommended (any): #%s", tag)

        if not picked:
            logger.warning("Не кликнули ни один recommended hashtag")
            await self.screenshot("error_title_hashtags")
        else:
            logger.info(
                "title hashtags ok %s/%s: %s",
                len(picked),
                limit,
                " ".join(f"#{t}" for t in picked),
            )
        return picked

    async def _fill_description_field(self, description: str) -> bool:
        """Заполнить описание без падения пайплайна."""
        assert self.page
        text = (description or "")[:5000]
        if not text:
            return True

        locators = [
            self.page.get_by_role(
                "textbox",
                name=re.compile(r"Расскажите, о чем|Tell viewers about your video", re.I),
            ),
            self.page.locator("#description-textarea #textbox"),
            self.page.locator("#description-wrapper #textbox"),
            self.page.locator(
                "ytcp-social-suggestions-textbox#description-textarea div#textbox"
            ),
            self.page.locator("div#textbox[contenteditable='true']").nth(1),
        ]

        # Tab из названия часто попадает в описание
        try:
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(150)
        except Exception:
            pass

        for loc in locators:
            try:
                if await loc.count() == 0:
                    continue
                el = loc.first
                try:
                    if not await el.is_visible():
                        continue
                except Exception:
                    pass
                try:
                    await el.click(timeout=2500, force=True)
                except Exception:
                    try:
                        await el.evaluate("node => node.focus()")
                    except Exception:
                        continue
                try:
                    await el.fill(text)
                except Exception:
                    # contenteditable
                    await el.evaluate(
                        """(node, value) => {
                          node.focus();
                          node.innerHTML = '';
                          node.textContent = value;
                          node.dispatchEvent(new InputEvent('input', { bubbles: true }));
                        }""",
                        text,
                    )
                logger.info("description filled (%s chars)", len(text))
                return True
            except Exception as exc:
                logger.debug("description locator try: %s", exc)
                continue

        # JS fallback по контейнеру описания
        try:
            ok = await self.page.evaluate(
                """(value) => {
                  const nodes = [
                    ...document.querySelectorAll('#description-textarea #textbox, #description-wrapper #textbox, ytcp-social-suggestions-textbox#description-textarea [contenteditable=\"true\"]'),
                  ];
                  const el = nodes.find(n => n && n.offsetParent !== null) || nodes[0];
                  if (!el) return false;
                  el.focus();
                  el.innerHTML = '';
                  el.textContent = value;
                  el.dispatchEvent(new InputEvent('input', { bubbles: true }));
                  return true;
                }""",
                text,
            )
            if ok:
                logger.info("description filled via JS (%s chars)", len(text))
                return True
        except Exception as exc:
            logger.warning("description JS fill: %s", exc)

        logger.warning("описание не заполнилось — продолжаю публикацию без него")
        await self.screenshot("warn_description_skip")
        return False

    async def _add_title_hashtags_via_dropdown(
        self,
        title_box,
        preferred: list[str],
        *,
        limit: int = 3,
    ) -> list[str]:
        """В конце названия: ` #tag` → option из dropdown.

        Нет в списке → Backspace и сразу следующий тег.
        Escape запрещён: закрывает окно загрузки Studio.
        """
        assert self.page
        limit = max(0, min(int(limit or 3), 3))
        candidates = self._normalize_tag_list(preferred, limit=20)
        # сначала более «ютубные» теги — меньше шансов застрять на брендовых (#гиперион)
        priority = (
            "shorts",
            "reels",
            "ai",
            "cursor",
            "coding",
            "нейросети",
            "автоматизация",
            "вайбкодинг",
            "вебинар",
        )
        pri = {t: i for i, t in enumerate(priority)}
        candidates = [
            t
            for _, t in sorted(
                enumerate(candidates),
                key=lambda it: (pri.get(it[1].casefold(), 100), it[0]),
            )
        ]
        if not candidates:
            return []

        picked: list[str] = []
        # фокус один раз; дальше только клавиатура
        try:
            await title_box.click(timeout=3000, force=True)
            await self.page.keyboard.press("End")
        except Exception as exc:
            logger.warning("title focus for hashtags: %s", exc)

        for tag in candidates:
            if len(picked) >= limit:
                break
            typed = f" #{tag}"
            try:
                await self.page.keyboard.press("End")
                await self.page.keyboard.type(typed, delay=30)
                await self.page.wait_for_timeout(400)
                ok = await self._pick_hashtag_dropdown_option(tag, timeout_sec=1.8)
                if ok:
                    picked.append(tag)
                    logger.info("title hashtag from dropdown: #%s", tag)
                    await self.page.wait_for_timeout(200)
                    continue
                logger.info("title hashtag absent → next: #%s", tag)
                await self._cancel_partial_hashtag_input(typed_len=len(typed))
            except Exception as exc:
                logger.warning("title hashtag #%s error → next: %s", tag, exc)
                await self._cancel_partial_hashtag_input(typed_len=len(typed))

        await self._dismiss_autocomplete()

        if not picked:
            logger.warning("ни один title-hashtag не выбран из dropdown — едем дальше без #")
            await self.screenshot("warn_title_hashtags_none")
        else:
            logger.info(
                "title hashtags ok %s/%s: %s",
                len(picked),
                limit,
                " ".join(f"#{t}" for t in picked),
            )
        return picked

    async def _cancel_partial_hashtag_input(self, *, typed_len: int) -> None:
        """Стереть незавершённый #tag. Escape НЕ использовать — убивает модалку загрузки."""
        assert self.page
        try:
            for _ in range(max(1, typed_len)):
                await self.page.keyboard.press("Backspace")
        except Exception:
            pass
        await self.page.wait_for_timeout(100)
        await self._dismiss_autocomplete()

    async def _pick_hashtag_dropdown_option(self, typed: str, *, timeout_sec: float = 1.8) -> bool:
        """Только пункты autocomplete (option/mention), не get_by_text по всей странице."""
        assert self.page
        want = typed.strip().lstrip("#")
        if not want:
            return False
        deadline = asyncio.get_event_loop().time() + max(0.6, float(timeout_sec))
        # узкие селекторы — иначе цепляем текст в title / recommended chips
        roots = [
            self.page.locator("ytcp-mention-option"),
            self.page.locator("[id^='text-dropdown'] [role='option']"),
            self.page.locator("tp-yt-paper-listbox [role='option']"),
            self.page.get_by_role("listbox").get_by_role("option"),
            self.page.get_by_role("option"),
        ]
        while asyncio.get_event_loop().time() < deadline:
            for root in roots:
                try:
                    n = await root.count()
                except Exception:
                    continue
                for i in range(min(n, 12)):
                    el = root.nth(i)
                    try:
                        if not await el.is_visible():
                            continue
                        txt = ((await el.inner_text()) or "").strip()
                    except Exception:
                        continue
                    low = txt.casefold()
                    if any(s in low for s in ("рекомендуем", "suggested", "загрузить", "upload")):
                        continue
                    # первая строка / первый токен с #
                    m = re.search(r"#?([\w\u0400-\u04FF]+)", txt, flags=re.UNICODE)
                    if not m:
                        continue
                    norm = m.group(1)
                    if norm.casefold() != want.casefold() and not norm.casefold().startswith(
                        want.casefold()
                    ):
                        continue
                    try:
                        await el.click(timeout=2000, force=True)
                        await self.page.wait_for_timeout(200)
                        return True
                    except Exception:
                        continue
            await self.page.wait_for_timeout(120)
        return False

    async def _pick_from_dropdown(
        self,
        typed: str,
        *,
        also_hash: bool = False,
        timeout_sec: float = 5.0,
    ) -> bool:
        """Dropdown для поля «Теги» (не title)."""
        assert self.page
        want = typed.strip().lstrip("#")
        if not want:
            return False
        # title-path переиспользует hashtag picker
        if also_hash:
            return await self._pick_hashtag_dropdown_option(want, timeout_sec=timeout_sec)
        deadline = asyncio.get_event_loop().time() + max(0.8, float(timeout_sec))
        while asyncio.get_event_loop().time() < deadline:
            locs = [
                self.page.get_by_role("option").filter(
                    has_text=re.compile(rf"^#?{re.escape(want)}$", re.I)
                ),
                self.page.locator("tp-yt-paper-item, [role='option']").filter(
                    has_text=re.compile(rf"^#?{re.escape(want)}$", re.I)
                ),
                self.page.get_by_role("option").filter(
                    has_text=re.compile(rf"#?{re.escape(want)}", re.I)
                ),
            ]
            for loc in locs:
                try:
                    if await loc.count() == 0:
                        continue
                    for i in range(min(await loc.count(), 8)):
                        el = loc.nth(i)
                        if not await el.is_visible():
                            continue
                        txt = ((await el.inner_text()) or "").strip().lstrip("#")
                        if (
                            txt.casefold() == want.casefold()
                            or txt.casefold().startswith(want.casefold())
                        ):
                            await el.click(timeout=2000, force=True)
                            await self.page.wait_for_timeout(200)
                            return True
                except Exception:
                    continue
            await self.page.wait_for_timeout(120)
        return False

    async def _fill_tags(self, tags: str) -> None:
        """Поле «Теги» (не хештеги в названии): type → Shift+Enter.

        Как раньше и в youtube_publish_codegen — без dropdown и без стирания.
        """
        assert self.page
        tag_list = [
            t.strip().lstrip("#")
            for t in (tags or "").replace(";", ",").split(",")
            if t.strip()
        ]
        # убрать дубли, сохранив порядок
        seen: set[str] = set()
        uniq: list[str] = []
        for t in tag_list:
            key = t.casefold()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(t)
        tag_list = uniq[:15]
        if not tag_list:
            return
        box = self.page.get_by_role("textbox", name=re.compile(r"^Теги$|^Tags$", re.I))
        if await box.count() == 0:
            logger.warning("Поле «Теги» не найдено")
            return
        try:
            await self._hclick(box.first, timeout=5000)
            for tag in tag_list:
                await box.first.type(tag, delay=30)
                await self.page.keyboard.press("Shift+Enter")
                await self.page.wait_for_timeout(150)
            logger.info("tags: %s", ", ".join(tag_list))
            await self.screenshot("step_tags_filled")
        except Exception as exc:
            logger.warning("tags: %s", exc)
            await self.screenshot("error_tags")

    async def _scroll_uploads_dialog(self, *, delta: int = 450) -> None:
        """Скролл внутри модалки загрузки (не window)."""
        assert self.page
        try:
            await self.page.evaluate(
                """(dy) => {
                  const roots = [
                    document.querySelector('ytcp-uploads-dialog #scrollable-content'),
                    document.querySelector('ytcp-uploads-dialog #scrollable-content .style-scope'),
                    document.querySelector('ytcp-uploads-dialog [id*="scroll"]'),
                    document.querySelector('ytcp-video-metadata-editor'),
                    document.querySelector('#scrollable-content'),
                  ].filter(Boolean);
                  for (const el of roots) {
                    if (el.scrollHeight > el.clientHeight + 20) {
                      el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + dy);
                      return el.scrollTop;
                    }
                  }
                  const dialog = document.querySelector('ytcp-uploads-dialog');
                  if (dialog) {
                    const all = dialog.querySelectorAll('*');
                    for (const el of all) {
                      if (el.scrollHeight > el.clientHeight + 80) {
                        el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + dy);
                        return el.scrollTop;
                      }
                    }
                  }
                  return -1;
                }""",
                delta,
            )
        except Exception:
            pass

    async def _scroll_details_to(self, *texts: str) -> None:
        """Прокрутить форму загрузки к секции по подписи (вниз по модалке)."""
        assert self.page
        for _ in range(10):
            for text in texts:
                loc = self.page.get_by_text(re.compile(text, re.I))
                try:
                    n = await loc.count()
                    for i in range(min(n, 5)):
                        el = loc.nth(i)
                        if await el.is_visible():
                            await el.scroll_into_view_if_needed(timeout=4000)
                            await self.page.wait_for_timeout(250)
                            return
                except Exception:
                    continue
            # текста ещё нет / вне вьюпорта — крутим модалку вниз
            await self._scroll_uploads_dialog(delta=420)
            await self.page.wait_for_timeout(200)

    def _prepare_cover_for_youtube(self, cover_path: Path) -> Path:
        """YouTube: JPG/PNG ≤2MB, лучше 1080×1920. Наши covers часто PNG под именем .jpg."""
        out_dir = _LOG_DIR / "youtube-covers"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{cover_path.stem}_yt.jpg"
        try:
            from PIL import Image

            im = Image.open(cover_path)
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")
            # вписать в 1080x1920 без обрезки по длинной стороне
            target_w, target_h = 1080, 1920
            im.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
            x = (target_w - im.width) // 2
            y = (target_h - im.height) // 2
            canvas.paste(im, (x, y))
            quality = 90
            while quality >= 50:
                canvas.save(out, format="JPEG", quality=quality, optimize=True)
                if out.stat().st_size <= 1_900_000:
                    break
                quality -= 10
            logger.info(
                "cover prepared: %s → %s (%sx%s, %s bytes)",
                cover_path.name,
                out.name,
                target_w,
                target_h,
                out.stat().st_size,
            )
            return out
        except Exception as exc:
            logger.warning("cover prepare failed (%s) — использую оригинал", exc)
            return cover_path

    async def _thumbnail_app_only_message(self) -> bool:
        """True, если Studio пишет сменить значок только в приложении YouTube."""
        assert self.page
        msg = self.page.get_by_text(
            re.compile(
                r"приложени[ие].*YouTube|YouTube app|изменить значок|change (the )?thumbnail.*app",
                re.I,
            )
        )
        try:
            if await msg.count() == 0:
                return False
            for i in range(min(await msg.count(), 4)):
                if await msg.nth(i).is_visible():
                    return True
        except Exception:
            return False
        return False

    async def _find_cover_upload_control(self):
        """Кнопка/input обложки (codegen: button «Загрузить файл»)."""
        assert self.page
        selectors = [
            self.page.get_by_role("button", name="Загрузить файл"),
            self.page.get_by_role("button", name="Upload file"),
            self.page.get_by_role("button", name=re.compile(r"Загрузить файл|Upload file|Upload thumbnail|Загрузить", re.I)),
            self.page.get_by_text(re.compile(r"^Загрузить файл$|^Upload file$|^Upload thumbnail$", re.I)),
            self.page.locator("ytcp-video-thumbnail-with-uploading-editor button"),
            self.page.locator("ytcp-thumbnails-compact-editor-uploader-old button"),
            self.page.locator("#file-loader, ytcp-thumbnail-uploader button"),
            self.page.locator("ytcp-thumbnail-editor button, ytcp-video-thumbnail-editor button"),
        ]
        for loc in selectors:
            try:
                if await loc.count() == 0:
                    continue
                for i in range(min(await loc.count(), 6)):
                    el = loc.nth(i)
                    try:
                        if await el.is_visible():
                            return el
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    async def _find_cover_file_input(self):
        assert self.page
        candidates = [
            self.page.locator("ytcp-video-thumbnail-with-uploading-editor input[type='file']"),
            self.page.locator("ytcp-thumbnails-compact-editor-uploader-old input[type='file']"),
            self.page.locator("#file-loader input[type='file']"),
            self.page.locator("ytcp-thumbnail-uploader input[type='file']"),
            self.page.locator("ytcp-thumbnail-editor input[type='file']"),
            self.page.locator("input[type='file'][accept*='image']"),
            self.page.locator("input[type='file'][accept*='jpeg']"),
            self.page.locator("input[type='file'][accept*='jpg']"),
        ]
        for loc in candidates:
            try:
                if await loc.count() > 0:
                    return loc.last
            except Exception:
                continue
        return None

    async def _attach_cover(self, cover_path: Path) -> bool:
        """Обложка как в codegen: дождаться «Загрузить файл» → set_input_files."""
        assert self.page
        prepared = self._prepare_cover_for_youtube(cover_path)
        path = str(prepared.resolve())
        if not prepared.is_file():
            logger.error("cover missing on disk: %s", path)
            return False

        # Значок — НИЖЕ описания: крутим модалку вниз
        await self._scroll_details_to(
            r"Значок",
            r"Thumbnail",
            r"Обложка",
            r"Загрузить файл",
            r"Upload file",
            r"приложени",
        )

        deadline = asyncio.get_event_loop().time() + 20
        last_err = ""
        saw_app_only = False
        app_only_since: float | None = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                if await self._thumbnail_app_only_message():
                    saw_app_only = True
                    if app_only_since is None:
                        app_only_since = asyncio.get_event_loop().time()
                    last_err = "studio shows Shorts thumbnail via YouTube app only"
                    # нет кнопки загрузки — не ждём минуты, идём публиковать дальше
                    if asyncio.get_event_loop().time() - app_only_since >= 6:
                        logger.warning(
                            "Значок Shorts только в приложении YouTube — пропускаю обложку, продолжаю публикацию"
                        )
                        await self.screenshot("warn_cover_app_only")
                        return False
                    await self._scroll_uploads_dialog(delta=280)
                else:
                    app_only_since = None

                inp = await self._find_cover_file_input()
                if inp is not None:
                    try:
                        await inp.set_input_files(path)
                        await self.page.wait_for_timeout(1500)
                        logger.info("cover set via input[type=file]: %s", prepared.name)
                        await self.screenshot("step_cover_set")
                        return True
                    except Exception as exc:
                        last_err = f"input: {exc}"

                btn = await self._find_cover_upload_control()
                if btn is not None:
                    try:
                        await btn.scroll_into_view_if_needed(timeout=3000)
                    except Exception:
                        pass
                    try:
                        await btn.set_input_files(path)
                        await self.page.wait_for_timeout(1500)
                        logger.info("cover set via button.set_input_files: %s", prepared.name)
                        await self.screenshot("step_cover_set")
                        return True
                    except Exception as exc:
                        last_err = f"btn.set_input_files: {exc}"
                    try:
                        async with self.page.expect_file_chooser(timeout=8000) as fc_info:
                            await self._hclick(btn, timeout=8000)
                        chooser = await fc_info.value
                        await chooser.set_files(path)
                        await self.page.wait_for_timeout(1500)
                        logger.info("cover set via file_chooser: %s", prepared.name)
                        await self.screenshot("step_cover_set")
                        return True
                    except Exception as exc:
                        last_err = f"chooser: {exc}"
                else:
                    if not saw_app_only:
                        last_err = "no upload control yet"
                    await self._scroll_uploads_dialog(delta=350)
            except Exception as exc:
                last_err = str(exc)
            await self.page.wait_for_timeout(2000)

        if saw_app_only:
            logger.error(
                "YouTube для этого Shorts не даёт кнопку «Загрузить файл» на десктопе — "
                "показывает смену значка только в приложении. "
                "Кастомная обложка в Studio (как в записи) доступна каналам YPP / после раскатки; "
                "иначе остаётся кадр из ролика или приложение. last=%s",
                last_err,
            )
        else:
            logger.warning("Обложка не прикреплена за 20с (%s) — продолжаю публикацию", last_err)
        await self.screenshot("error_cover")
        return False

    async def _select_playlist(self) -> bool:
        """Выбрать один или несколько плейлистов (YOUTUBE_PLAYLIST=Cursor,Туториал) → ОК."""
        assert self.page
        names = list(self.playlists)
        if not names:
            logger.info("Плейлист не задан (YOUTUBE_PLAYLIST) — пропускаю")
            return True
        try:
            opener = self.page.get_by_role("button", name="Выберите плейлист")
            if await opener.count() == 0:
                opener = self.page.get_by_role("button", name=re.compile(r"^Select$|Select playlist", re.I))
            if await opener.count() == 0:
                opener = self.page.get_by_text(re.compile(r"Выберите плейлист|Select playlist", re.I))
            if await opener.count() == 0:
                logger.warning("Нет кнопки плейлиста")
                return False
            await self._hclick(opener.first, timeout=8000)
            await self.page.wait_for_timeout(800)

            selected = 0
            for name in names:
                ok_one = await self._tick_playlist_option(name)
                if ok_one:
                    selected += 1
                else:
                    logger.error("Плейлист не найден: %s", name)

            if selected == 0:
                await self.screenshot("error_playlist_missing")
                cancel = self.page.get_by_role("button", name=re.compile(r"^Отмена$|^Cancel$", re.I))
                if await cancel.count() > 0:
                    await self._hclick(cancel.first)
                return False

            ok = self.page.get_by_role("button", name="ОК", exact=True)
            if await ok.count() == 0:
                ok = self.page.get_by_role("button", name="Done", exact=True)
            if await ok.count() == 0:
                ok = self.page.get_by_role("button", name=re.compile(r"^OK$", re.I))
            if await ok.count() > 0:
                await self._hclick(ok.first, timeout=8000)
            else:
                logger.warning("Нет кнопки ОК после выбора плейлиста")
                await self.screenshot("error_playlist_no_ok")
                return False
            logger.info("playlist selected (%s/%s): %s", selected, len(names), ", ".join(names))
            await self._hpause(0.3, 0.7)
            return True
        except Exception as exc:
            logger.warning("Плейлист не выбран: %s", exc)
            await self.screenshot("error_playlist")
            return False

    async def _tick_playlist_option(self, name: str) -> bool:
        """Поиск в диалоге плейлиста + чекбокс (как в Studio: «Введите название»)."""
        assert self.page
        aliases = [name]
        low = name.casefold()
        if low in {"туториал", "tutorial", "tutorials"}:
            aliases.extend(
                [
                    "Туториал",
                    "Tutorial",
                    "Обучение нейросетям",
                    "Cursor AI обучение",
                ]
            )
        if "cursor" in low:
            aliases.extend(["Cursor AI обучение", "Cursor", "cursor"])

        seen: set[str] = set()
        names: list[str] = []
        for a in aliases:
            k = a.casefold()
            if k not in seen:
                seen.add(k)
                names.append(a)

        # поиск в диалоге ускоряет матч
        search = self.page.get_by_placeholder(re.compile(r"название плейлиста|Search|Find", re.I))
        if await search.count() == 0:
            search = self.page.get_by_role(
                "textbox", name=re.compile(r"плейлист|playlist|search", re.I)
            )

        for n in names:
            try:
                if await search.count() > 0:
                    await self._hclick(search.first, timeout=4000)
                    await search.first.fill("")
                    await search.first.fill(n)
                    await self.page.wait_for_timeout(500)
            except Exception:
                pass

            candidates = [
                self.page.get_by_text(n, exact=True),
                self.page.get_by_text(re.compile(rf"^{re.escape(n)}$", re.I)),
                self.page.get_by_text(n, exact=False),
                self.page.get_by_text(re.compile(re.escape(n), re.I)),
            ]
            target = None
            for loc in candidates:
                try:
                    if await loc.count() == 0:
                        continue
                    for i in range(await loc.count()):
                        el = loc.nth(i)
                        try:
                            if await el.is_visible():
                                target = el
                                break
                        except Exception:
                            continue
                    if target is not None:
                        break
                except Exception:
                    continue
            if target is None:
                continue

            try:
                row = target.locator(
                    "xpath=ancestor::*[.//div[@id='checkbox-container'] or .//tp-yt-paper-checkbox or contains(@class,'checkbox')][1]"
                )
                box = row.locator("#checkbox-container, #checkbox, tp-yt-paper-checkbox").first
                if await box.count() > 0 and await box.is_visible():
                    await self._hclick(box, timeout=5000)
                    await self.page.wait_for_timeout(250)
                    logger.info("playlist ticked via checkbox: %s", n)
                    return True
            except Exception:
                pass
            try:
                await self._hclick(target, timeout=5000)
                await self.page.wait_for_timeout(250)
                logger.info("playlist ticked via text: %s", n)
                return True
            except Exception:
                continue
        return False

    async def _open_advanced(self) -> None:
        assert self.page
        more = self.page.get_by_role("button", name="Показать дополнительные настройки")
        if await more.count() == 0:
            more = self.page.get_by_role("button", name="SHOW MORE")
        if await more.count() == 0:
            more = self.page.get_by_text(re.compile(r"Показать дополнительные|SHOW MORE", re.I))
        if await more.count() > 0:
            try:
                await self._hclick(more.first, timeout=5000)
                await self._hpause(0.4, 0.8)
            except Exception:
                pass

    async def _set_ai_disclosure(self) -> None:
        assert self.page
        if self.ai_used:
            radio = self.page.get_by_role(
                "radio", name=re.compile(r"Да,.*ИИ|Yes.*altered|Yes.*AI", re.I)
            )
        else:
            radio = self.page.get_by_role(
                "radio", name=re.compile(r"Нет, ИИ не использовался|No,.*AI|No.*altered", re.I)
            )
        if await radio.count() > 0:
            try:
                await self._hclick(radio.first, timeout=5000)
                logger.info("AI disclosure set (ai_used=%s)", self.ai_used)
            except Exception as exc:
                logger.warning("AI disclosure: %s", exc)

    async def _select_category(self) -> bool:
        assert self.page
        if not self.category:
            return True
        try:
            # Как в codegen: открыть select → клик по «Наука и техника»
            form = self.page.locator("ytcp-form-select#category, ytcp-form-select[id*='category']")
            if await form.count() > 0:
                try:
                    await self._hclick(form.first, timeout=5000)
                    await self.page.wait_for_timeout(400)
                except Exception:
                    pass
            else:
                for opener in (
                    self.page.get_by_text("Категория", exact=True),
                    self.page.get_by_text("Category", exact=True),
                    self.page.get_by_role("button", name=re.compile(r"Музыка|Music|Entertainment|Развлечения", re.I)),
                ):
                    try:
                        if await opener.count() > 0:
                            await self._hclick(opener.first, timeout=4000)
                            await self.page.wait_for_timeout(400)
                            break
                    except Exception:
                        continue

            opt = self.page.get_by_role("option", name=self.category)
            if await opt.count() == 0:
                opt = self.page.locator("tp-yt-paper-item, ytcp-ve, div").filter(
                    has_text=re.compile(rf"^{re.escape(self.category)}$", re.I)
                )
            if await opt.count() == 0:
                opt = self.page.get_by_text(self.category, exact=True)
            if await opt.count() == 0:
                opt = self.page.get_by_role("button", name=self.category)
            if await opt.count() == 0:
                logger.warning("Категория не найдена: %s", self.category)
                return False
            # nth(2) в codegen — берём видимый
            clicked = False
            for i in range(min(await opt.count(), 6)):
                el = opt.nth(i)
                try:
                    if await el.is_visible():
                        await self._hclick(el, timeout=8000, force=True)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                await self._hclick(opt.first, timeout=8000, force=True)

            try:
                backdrop = self.page.locator("tp-yt-iron-overlay-backdrop")
                if await backdrop.count() > 0:
                    await backdrop.last.click(timeout=2000, force=True)
            except Exception:
                pass
            logger.info("category: %s", self.category)
            return True
        except Exception as exc:
            logger.warning("Категория: %s", exc)
            await self.screenshot("error_category")
            return False

    async def _dismiss_rating_prompt(self) -> bool:
        """Studio показывает «Поставить оценку» — без клика «Далее» не активируется."""
        assert self.page
        rate = self.page.get_by_role("button", name=re.compile(r"Поставить оценку|Rate this", re.I))
        if await rate.count() == 0:
            return False
        try:
            btn = rate.first
            if not await btn.is_visible():
                return False
            # не кликаем disabled — ждём enabled (обработка видео)
            for _ in range(30):
                try:
                    if await btn.is_enabled():
                        break
                except Exception:
                    pass
                await self.page.wait_for_timeout(1000)
            else:
                return False
            await self._hclick(btn, timeout=8000)
            await self._hpause(0.5, 1.0)
            logger.info("clicked «Поставить оценку»")
            await self.screenshot("step_rating_clicked")
            return True
        except Exception as exc:
            logger.warning("rating prompt: %s", exc)
            return False

    async def _click_next_until_visibility(self, *, max_steps: int = 6) -> bool:
        """Жмём Далее (+ оценку / чекбоксы), пока не появится «Открытый доступ» / Public."""
        assert self.page
        for step in range(1, max_steps + 1):
            # Visibility step already here?
            pub = self.page.get_by_role(
                "radio", name=re.compile(r"Открытый доступ|Public", re.I)
            )
            if await pub.count() > 0:
                try:
                    if await pub.first.is_visible():
                        logger.info("visibility step reached (after %s next)", step - 1)
                        return True
                except Exception:
                    pass

            await self._accept_checks_if_any()
            await self._set_ad_suitability_if_needed()
            await self._dismiss_rating_prompt()

            nxt = self.page.get_by_role("button", name="Далее")
            if await nxt.count() == 0:
                nxt = self.page.get_by_role("button", name="Next")
            if await nxt.count() == 0:
                logger.warning("Нет «Далее» на шаге %s", step)
                break
            for _ in range(60):
                try:
                    if await nxt.first.is_enabled():
                        break
                except Exception:
                    pass
                # иногда блокирует непройденная оценка или шаг «Для рекламы»
                await self._dismiss_rating_prompt()
                await self._set_ad_suitability_if_needed()
                await self.page.wait_for_timeout(2000)
            else:
                await self.screenshot(f"error_next_disabled_{step}")
                logger.error("«Далее» disabled на шаге %s", step)
                return False
            await self._hclick(nxt.first, timeout=10000)
            await self._hpause(0.6, 1.3)
            logger.info("clicked Далее (%s/%s)", step, max_steps)
            # после Next снова может всплыть оценка
            await self._dismiss_rating_prompt()

        pub = self.page.get_by_role(
            "radio", name=re.compile(r"Открытый доступ|Public", re.I)
        )
        return await pub.count() > 0

    async def _accept_checks_if_any(self) -> None:
        """Шаг «Проверки»: НЕ ставим галочки про рекламу/спонсорство.

        Запрещено кликать «видео содержит рекламу / product placement / sponsor content»
        (часто это просто #checkbox-container — как в старом codegen). Ролики без рекламы.
        """
        assert self.page
        await self._ensure_no_paid_promotion()

    async def _ensure_no_paid_promotion(self) -> None:
        """Снять галочку paid promotion / прямой рекламы, если она вдруг отмечена."""
        assert self.page
        # текстовые маркеры блока (RU/EN)
        labels = self.page.get_by_text(
            re.compile(
                r"платн(ую|ая)\s+реклам|product placement|sponsor|"
                r"спонсор|прямой реклам|paid promotion|"
                r"реклам|размещени[ея]\s+продукт",
                re.I,
            )
        )
        try:
            n = min(await labels.count(), 8)
        except Exception:
            n = 0
        for i in range(n):
            lab = labels.nth(i)
            try:
                if not await lab.is_visible():
                    continue
                # чекбокс рядом с подписью
                row = lab.locator(
                    "xpath=ancestor::*[.//div[@id='checkbox-container'] or "
                    ".//tp-yt-paper-checkbox or .//*[@role='checkbox']][1]"
                )
                box = row.locator(
                    "#checkbox-container, tp-yt-paper-checkbox, [role='checkbox']"
                ).first
                if await box.count() == 0:
                    continue
                checked = False
                try:
                    aria = (await box.get_attribute("aria-checked")) or ""
                    checked = aria.casefold() == "true"
                except Exception:
                    checked = False
                if not checked:
                    try:
                        checked = await box.evaluate(
                            """(el) => {
                              const c = el.closest('tp-yt-paper-checkbox') || el;
                              return !!(c.checked || c.hasAttribute('checked') ||
                                c.getAttribute('aria-checked') === 'true' ||
                                c.classList.contains('checked'));
                            }"""
                        )
                    except Exception:
                        checked = False
                if checked:
                    await box.click(timeout=3000, force=True)
                    logger.warning("снял галочку paid promotion / реклама")
                    await self.page.wait_for_timeout(200)
            except Exception:
                continue

    async def _set_ad_suitability_if_needed(self) -> None:
        """Шаг «Подходит ли видео для рекламы» (self-certification).

        Раньше здесь не выбирался ответ → «Далее» оставался disabled, публикация висла.
        Дефолт: «Ни один вариант не подходит» (none). Можно переопределить env
        YOUTUBE_AD_SUITABILITY = some | sensitive.
        """
        assert self.page
        marker = self.page.get_by_text(
            re.compile(
                r"Подходит ли видео для рекламы|"
                r"Is the video suitable for advertising|"
                r"Ad suitability|advertising guidelines",
                re.I,
            )
        )
        try:
            if await marker.count() == 0 or not await marker.first.is_visible():
                return
        except Exception:
            return
        logger.info("Обнаружен шаг «Подходит ли видео для рекламы» — выбираю ответ")

        groups = {
            "none": re.compile(
                r"Ни один вариант.*не подходит|"
                r"None of the above|"
                r"не относится|"
                r"doesn.?t contain|"
                r"No.*inappropriate content",
                re.I,
            ),
            "some": re.compile(
                r"Некоторые варианты подходят|"
                r"Some of the above|"
                r"contains some",
                re.I,
            ),
            "sensitive": re.compile(
                r"Видео содержит неприемлемый контент|"
                r"Video contains inappropriate content|"
                r"sensitive content",
                re.I,
            ),
        }
        chosen = groups.get(self.ad_suitability, groups["none"])
        # Пробуем выбрать целевой ответ; fallback — «none»
        for pattern in (chosen, groups["none"]):
            try:
                radio = self.page.get_by_role("radio", name=pattern)
                if await radio.count() > 0:
                    await self._hclick(radio.first, timeout=5000)
                    logger.info("ad suitability: выбран вариант (%s)", pattern.pattern[:40])
                    await self._hpause(0.3, 0.7)
                    return
            except Exception:
                pass
            # Некоторые варианты реализованы как обычная кнопка
            try:
                btn = self.page.get_by_role("button", name=pattern)
                if await btn.count() > 0:
                    await self._hclick(btn.first, timeout=5000)
                    logger.info("ad suitability (button): выбран (%s)", pattern.pattern[:40])
                    await self._hpause(0.3, 0.7)
                    return
            except Exception:
                pass
        logger.warning("ad suitability: вариант не найден — оставляю как есть")

    async def _set_not_for_kids_if_needed(self) -> None:
        assert self.page
        # На шаге деталей иногда спрашивают «Контент для детей»
        if self.made_for_kids:
            radio = self.page.get_by_role(
                "radio", name=re.compile(r"Да.*дети|Yes.*kids|made for kids", re.I)
            )
        else:
            radio = self.page.get_by_role(
                "radio",
                name=re.compile(
                    r"Нет, это видео не для детей|No.*not made for kids|not for kids",
                    re.I,
                ),
            )
        if await radio.count() > 0:
            try:
                await self._hclick(radio.first, timeout=5000)
            except Exception:
                pass

    async def _set_public_and_publish(self, *, draft: bool) -> bool:
        assert self.page
        if draft:
            radio = self.page.get_by_role(
                "radio", name=re.compile(r"Доступ по ссылке|Unlisted|Private|Ограниченный", re.I)
            )
            if await radio.count() > 0:
                await self._hclick(radio.first)
            save = self.page.get_by_role("button", name=re.compile(r"Сохранить|Save", re.I))
            if await save.count() > 0:
                await self._hclick(save.first)
                logger.info("draft/unlisted saved")
                return True
            logger.error("Нет кнопки сохранения черновика")
            return False

        pub_radio = self.page.get_by_role("radio", name=re.compile(r"Открытый доступ|Public", re.I))
        if await pub_radio.count() > 0:
            await self._hclick(pub_radio.first, timeout=8000)
            logger.info("visibility: Public")

        publish = self.page.get_by_role("button", name="Опубликовать")
        if await publish.count() == 0:
            publish = self.page.get_by_role("button", name="Publish")
        if await publish.count() == 0:
            await self.screenshot("error_no_publish")
            logger.error("Нет кнопки «Опубликовать»")
            return False
        for _ in range(90):
            try:
                if await publish.first.is_enabled():
                    break
            except Exception:
                pass
            await self.page.wait_for_timeout(2000)
        else:
            await self.screenshot("error_publish_disabled")
            logger.error("«Опубликовать» не стала активной")
            return False

        await self._hclick(publish.first, timeout=10000)
        logger.info("clicked Publish")
        return True

    async def _wait_after_publish(self, *, timeout_sec: int = 120) -> bool:
        assert self.page
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            # сначала вытащить video_id, пока success-диалог ещё открыт
            vid = await self._capture_video_id_from_page()
            if vid:
                self.last_video_id = vid
            try:
                body = (await self.page.locator("body").inner_text(timeout=3000)).lower()
            except Exception:
                body = ""
            if any(
                s in body
                for s in (
                    "видео опубликовано",
                    "video published",
                    "обработка видео",
                    "video processing",
                    "скопировать ссылку",
                    "copy video link",
                )
            ):
                logger.info("Publish confirmed by success UI")
                if not self.last_video_id:
                    self.last_video_id = await self._capture_video_id_from_page()
                # закрыть диалог если есть
                try:
                    close = self.page.locator("#close-button").get_by_role(
                        "button", name=re.compile(r"Закрыть|Close", re.I)
                    )
                    if await close.count() > 0:
                        await self._hclick(close.first, timeout=5000)
                except Exception:
                    pass
                return True
            await self.page.wait_for_timeout(2500)
        logger.warning("После Publish явного success не увидели — смотрите screenshot")
        if not self.last_video_id:
            self.last_video_id = await self._capture_video_id_from_page()
        await self.screenshot("warn_after_publish")
        return True  # часто уже опубликовано

    async def _capture_video_id_from_page(self) -> str | None:
        """Достать id ролика из ссылок Studio / shorts / youtu.be на текущей странице."""
        assert self.page
        patterns = [
            re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})", re.I),
            re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,})", re.I),
            re.compile(r"studio\.youtube\.com/video/([A-Za-z0-9_-]{6,})", re.I),
            re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{6,})", re.I),
            re.compile(r"/video/([A-Za-z0-9_-]{6,})/edit", re.I),
        ]
        hrefs: list[str] = []
        try:
            hrefs = await self.page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href || '').filter(Boolean)",
            )
        except Exception:
            hrefs = []
        texts = []
        try:
            texts.append(await self.page.locator("body").inner_text(timeout=2000))
        except Exception:
            pass
        try:
            texts.append(self.page.url or "")
        except Exception:
            pass
        blob = "\n".join([*(hrefs or []), *texts])
        for pat in patterns:
            m = pat.search(blob)
            if m:
                vid = m.group(1)
                logger.info("captured video_id=%s", vid)
                return vid
        return None

    async def _find_video_id_by_title_in_content(self, title: str) -> str | None:
        """Fallback: Контент → Shorts → первая строка с похожим названием."""
        assert self.page
        clean = self._strip_hashtags(title or "").strip()
        needle = (clean[:48] if clean else "").casefold()
        if not needle:
            return None
        base = self._studio_home().rstrip("/")
        urls = [
            f"{base}/videos/short",
            f"{base}/videos/short?filter=%5B%5D&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D",
            f"{base}/content",
        ]
        for url in urls:
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await self.page.wait_for_timeout(2500)
            except Exception as exc:
                logger.debug("content goto %s: %s", url, exc)
                continue
            # прямые edit-ссылки в таблице
            try:
                links = self.page.locator("a[href*='/video/']")
                n = min(await links.count(), 40)
                for i in range(n):
                    a = links.nth(i)
                    try:
                        href = (await a.get_attribute("href")) or ""
                        txt = ((await a.inner_text()) or "").casefold()
                    except Exception:
                        continue
                    m = re.search(r"/video/([A-Za-z0-9_-]{6,})", href)
                    if not m:
                        continue
                    if needle[:24] in txt or txt[:24] in needle:
                        logger.info("video_id from content title match: %s", m.group(1))
                        return m.group(1)
                # если title не совпал — взять самый свежий short edit link
                for i in range(n):
                    href = (await links.nth(i).get_attribute("href")) or ""
                    m = re.search(r"/video/([A-Za-z0-9_-]{6,})", href)
                    if m:
                        logger.info("video_id fallback latest content row: %s", m.group(1))
                        return m.group(1)
            except Exception as exc:
                logger.debug("content scan: %s", exc)
        return None

    async def _attach_cover_on_edit_page(self, cover_path: Path) -> bool:
        """На странице studio …/video/ID/edit загрузить значок и Сохранить."""
        assert self.page
        prepared = self._prepare_cover_for_youtube(cover_path)
        path = str(prepared.resolve())
        if not prepared.is_file():
            return False

        # дождаться редактора
        for _ in range(20):
            if await self.page.get_by_text(
                re.compile(r"Значок|Thumbnail|Обложка", re.I)
            ).count() > 0:
                break
            await self.page.wait_for_timeout(500)

        # проскроллить к блоку значка
        for _ in range(8):
            try:
                loc = self.page.get_by_text(re.compile(r"^Значок$|^Thumbnail$|^Обложка$", re.I))
                if await loc.count() > 0:
                    await loc.first.scroll_into_view_if_needed(timeout=2000)
                    break
            except Exception:
                pass
            await self.page.mouse.wheel(0, 500)
            await self.page.wait_for_timeout(200)

        if await self._thumbnail_app_only_message():
            logger.warning("На edit-странице тоже «только в приложении» — обложка недоступна")
            await self.screenshot("warn_cover_edit_app_only")
            return False

        deadline = asyncio.get_event_loop().time() + 25
        last_err = ""
        while asyncio.get_event_loop().time() < deadline:
            try:
                inp = await self._find_cover_file_input()
                if inp is not None:
                    await inp.set_input_files(path)
                    await self.page.wait_for_timeout(1500)
                    logger.info("edit-page cover via input: %s", prepared.name)
                    break
                btn = await self._find_cover_upload_control()
                if btn is not None:
                    try:
                        await btn.set_input_files(path)
                        await self.page.wait_for_timeout(1500)
                        logger.info("edit-page cover via btn.set_input_files: %s", prepared.name)
                        break
                    except Exception:
                        async with self.page.expect_file_chooser(timeout=8000) as fc_info:
                            await btn.click(timeout=5000, force=True)
                        chooser = await fc_info.value
                        await chooser.set_files(path)
                        await self.page.wait_for_timeout(1500)
                        logger.info("edit-page cover via file_chooser: %s", prepared.name)
                        break
                last_err = "no upload control on edit page"
                await self.page.mouse.wheel(0, 400)
            except Exception as exc:
                last_err = str(exc)
            await self.page.wait_for_timeout(800)
        else:
            logger.warning("edit-page cover failed: %s", last_err)
            await self.screenshot("error_cover_edit_page")
            return False

        await self.screenshot("step_cover_edit_uploaded")
        # Сохранить
        save = self.page.get_by_role("button", name=re.compile(r"^Сохранить$|^Save$", re.I))
        if await save.count() == 0:
            save = self.page.get_by_role("button", name=re.compile(r"Сохранить|Save", re.I))
        try:
            if await save.count() > 0:
                btn = save.first
                for _ in range(30):
                    try:
                        if await btn.is_enabled():
                            break
                    except Exception:
                        pass
                    await self.page.wait_for_timeout(500)
                if await btn.is_enabled():
                    await btn.click(timeout=8000, force=True)
                    await self.page.wait_for_timeout(2000)
                    logger.info("edit-page Save clicked after cover")
                else:
                    logger.info("Save disabled — возможно обложка уже применена без dirty state")
            else:
                logger.warning("Нет кнопки Сохранить на edit-странице")
        except Exception as exc:
            logger.warning("Save after cover: %s", exc)
        await self.screenshot("step_cover_edit_saved")
        return True

    async def _set_cover_after_publish(
        self,
        cover_path: Path,
        *,
        title: str,
        video_id: str | None = None,
    ) -> bool:
        """После публикации: открыть Studio edit и поставить кастомный значок."""
        assert self.page
        vid = video_id or self.last_video_id or await self._capture_video_id_from_page()
        if not vid:
            logger.info("video_id неизвестен — ищу в Контенте по названию")
            vid = await self._find_video_id_by_title_in_content(title)
        if not vid:
            logger.warning("Не нашли video_id — post-publish обложку пропустить")
            await self.screenshot("error_cover_no_video_id")
            return False
        self.last_video_id = vid
        edit_url = f"https://studio.youtube.com/video/{vid}/edit"
        logger.info("Post-publish cover → %s", edit_url)
        try:
            await self.page.goto(edit_url, wait_until="domcontentloaded", timeout=90000)
            await self.page.wait_for_timeout(2500)
        except Exception as exc:
            logger.warning("goto edit failed: %s", exc)
            return False
        await self.screenshot("step_cover_edit_open")
        ok = await self._attach_cover_on_edit_page(cover_path)
        if ok:
            logger.info("Post-publish cover OK for %s", vid)
        else:
            logger.warning("Post-publish cover FAILED for %s", vid)
        return ok

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
        await self.screenshot("step1_studio")

        if not await self._open_upload_dialog():
            await self.screenshot("error_open_upload")
            return False

        if not await self._set_video_file(video_path):
            await self.screenshot("error_no_file_input")
            logger.error("Не удалось прикрепить видео")
            return False
        logger.info("video set: %s", video_path.name)
        await self._hpause(1.0, 2.0)

        if not await self._wait_details_form():
            await self.screenshot("error_no_form")
            logger.error("Форма названия не появилась")
            return False

        # Shorts URL часто появляется сразу после выбора файла
        early_id = await self._capture_video_id_from_page()
        if early_id:
            self.last_video_id = early_id

        # Название БЕЗ сырых #; хештеги — только клики по «Рекомендуемые хештеги»
        tag_list = self._normalize_tag_list(tags)
        clean_title = self._strip_hashtags((title or video_path.stem).strip())
        clean_title = re.sub(r"\s{2,}", " ", clean_title).strip(" -–—|")[:100]
        desc_text = self._compose_description(
            title=title, description=description, tags=tags
        )
        logger.info(
            "title(clean)=%s · preferred_hashtags=%s",
            clean_title,
            " ".join(f"#{t}" for t in tag_list[:8]),
        )
        picked_title_tags = await self._fill_title_description(
            title=clean_title,
            description=desc_text,
            preferred_hashtags=tag_list,
        )
        if not await self._uploads_dialog_open():
            logger.error(
                "Окно загрузки закрылось после title/hashtags (часто из‑за Escape). "
                "Видео ушло в черновик Studio — публикую дальше нельзя в этой сессии."
            )
            await self.screenshot("error_upload_dialog_closed")
            return False

        await self._set_not_for_kids_if_needed()

        # Обложка: один короткий попыт; для Shorts часто только app — не блокируем публикацию
        cover_ok = False
        if cover_path:
            await self._hpause(0.3, 0.6)
            cover_ok = await self._attach_cover(cover_path)
            if not cover_ok:
                logger.warning("Обложка пропущена — продолжаю к плейлисту/публикации")

        if not await self._uploads_dialog_open():
            logger.error("Окно загрузки закрылось перед плейлистом")
            await self.screenshot("error_upload_dialog_closed_mid")
            return False

        playlist_ok = await self._select_playlist()
        if not playlist_ok and self.playlists:
            logger.warning("Продолжаю без плейлиста (выбор не удался)")

        await self._open_advanced()
        await self._set_ai_disclosure()
        # «Теги» — отдельное поле (не хештеги в title): type + Shift+Enter
        await self._fill_tags(", ".join(tag_list))
        await self._select_category()
        await self.screenshot("step2_details_filled")

        # Details → Video elements → Checks → (оценка) → Visibility
        # «Поставить оценку» обязателен: без клика «Далее» остаётся disabled
        if not await self._click_next_until_visibility(max_steps=6):
            await self.screenshot("error_no_visibility")
            logger.error("Не дошли до шага «Видимость» (оценка/Далее)")
            return False

        await self.screenshot("step3_visibility")
        if not await self._set_public_and_publish(draft=draft):
            return False

        ok = await self._wait_after_publish()
        await self.screenshot("step4_after_publish")

        # Если на шаге загрузки обложку не дали — пробуем после Publish в edit
        if cover_path and not cover_ok:
            logger.info("Пробую обложку post-publish в Studio edit…")
            try:
                post_ok = await self._set_cover_after_publish(
                    cover_path,
                    title=clean_title,
                    video_id=self.last_video_id,
                )
                if post_ok:
                    cover_ok = True
                    logger.info("Обложка поставлена после публикации")
                else:
                    logger.warning("Post-publish обложка не встала — ролик уже опубликован без неё")
            except Exception as exc:
                logger.warning("Post-publish cover error: %s", exc)
                await self.screenshot("error_cover_post_publish")

        await self.save_cookies()
        logger.info(
            "YouTube: %s · video_id=%s · cover=%s",
            "draft" if draft else "published",
            self.last_video_id or "?",
            "ok" if (not cover_path or cover_ok) else "missing",
        )
        return ok


async def amain() -> int:
    parser = argparse.ArgumentParser(description="YouTube Studio Shorts — по записи codegen")
    parser.add_argument("--video", "-v")
    parser.add_argument("--title", "-t", default="")
    parser.add_argument("--description", "-d", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--cover", "-c")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--login-only", action="store_true")
    args = parser.parse_args()

    client = YoutubeClient()
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
    except Exception as exc:
        logger.exception("YouTube client crashed: %s", exc)
        try:
            await client.screenshot("error_crash")
        except Exception:
            pass
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
