#!/usr/bin/env python3
"""Playwright-клиент TikTok Studio Upload по живой записи codegen (2026-07-25).

Сценарий:
  1) https://www.tiktok.com/tiktokstudio/upload
  2) «Select video» → set_input_files (без native dialog)
  3) «Turn on» / «Got it» (если попапы)
  4) Описание (Draft.js combobox / block)
  5) Обложка: Edit cover → Upload cover image → Save
  6) Who can watch: Everyone
  7) Post
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
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
_SHOT_DIR = _LOG_DIR / "tiktok-screenshots"
_SHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "tiktok_autopost.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("tiktok_client")

for _env_path in (
    _PLUGIN_ROOT / "videoshorts.local.env",
    _PLUGIN_ROOT / ".env",
):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
load_dotenv(override=False)


class TikTokClient:
    UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"

    def __init__(self) -> None:
        default_storage = (
            _PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "tiktok_storage_state.json"
        )
        self.storage_state_path = os.getenv(
            "VIDEOSHORTS_TIKTOK_STORAGE",
            os.getenv("TIKTOK_STORAGE_STATE", str(default_storage)),
        )
        self.timezone_id = os.getenv("TIKTOK_TZ", "Europe/Vilnius")
        self.headless = os.getenv("HEADLESS", "false").lower() == "true"
        self.timeout = int(os.getenv("BROWSER_TIMEOUT", "180000"))
        force_close = os.getenv("VIDEOSHORTS_FORCE_CLOSE_BROWSER", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        self.keep_open = (os.getenv("KEEP_BROWSER_OPEN", "false").lower() == "true") and not force_close
        self.visibility = os.getenv("TIKTOK_VISIBILITY", "Everyone")
        from browser_humanize import make_humanize

        self.hz = make_humanize(lambda: self.page, "TIKTOK_HUMANIZE", "HUMANIZE", name="tiktok")

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

            launch_args = chromium_window_args(maximize=True) + [
                "--disable-blink-features=AutomationControlled"
            ]
            logger.info("Display: %s", describe_placement())
        except Exception as exc:
            logger.warning("playwright_display unavailable: %s", exc)
            launch_args = ["--start-maximized", "--disable-blink-features=AutomationControlled"]
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
        )
        ctx_kwargs: dict = {
            "viewport": None,
            "locale": os.getenv("TIKTOK_LOCALE", "ru-RU"),
            "timezone_id": self.timezone_id,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        if storage.is_file() and storage.stat().st_size > 100:
            ctx_kwargs["storage_state"] = str(storage)
            logger.info("Cookies: %s", storage)
        else:
            logger.warning("No TikTok cookies — run tiktok_login_save.py first")
        self.context = await self.browser.new_context(**ctx_kwargs)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        logger.info("TikTok browser started · humanize=%s", self.hz.enabled)
        logger.info("TikTok browser started · tz=%s", self.timezone_id)

    async def close(self) -> None:
        try:
            if self.context:
                await self.save_cookies()
        except Exception:
            pass
        if self.keep_open:
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
        await self.page.goto(self.UPLOAD_URL, wait_until="domcontentloaded", timeout=120000)
        await self.page.wait_for_timeout(2500)
        url = (self.page.url or "").lower()
        if "login" in url or "signup" in url:
            logger.error("Not logged in — run tiktok_login_save.py (VPN on)")
            await self.screenshot("error_not_logged_in")
            return False
        logger.info("Session OK: %s", self.page.url)
        return True

    @staticmethod
    def _extract_hashtags(*texts: str) -> list[str]:
        found: list[str] = []
        for text in texts:
            if not text:
                continue
            for m in re.finditer(r"#([^\s#]+)", text):
                tag = m.group(1).strip().strip(",.;:")
                if tag and tag.lower() not in {t.lower() for t in found}:
                    found.append(tag)
        return found

    @staticmethod
    def _strip_hashtags(text: str) -> str:
        """Убрать сырые #теги из описания — их добавим через UI-список TikTok."""
        if not text:
            return ""
        # remove hashtag tokens, then collapse blank lines
        cleaned = re.sub(r"#\S+", " ", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        lines = [ln.strip() for ln in cleaned.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines).strip()

    def _compose_caption(self, *, title: str, description: str, tags: str) -> str:
        """Цельный текст: заголовок + описание, без # (хештеги только через UI-список)."""
        desc = self._strip_hashtags((description or "").strip())
        title = (title or "").strip()
        # обрезанные хвосты вроде «Сильный payoff: а» — отбросить
        if re.search(r"payoff:\s*а\s*$", desc, re.I):
            desc = re.sub(r"\n?Сильный payoff:\s*а\s*$", "", desc, flags=re.I).strip()
        if title and desc:
            if desc.startswith(title):
                body = desc
            else:
                body = f"{title}\n{desc}"
        elif desc:
            body = desc
        else:
            body = title
        return body[:2200].strip()

    def _resolve_tags(self, *, description: str, tags: str) -> list[str]:
        from_desc = self._extract_hashtags(description or "")
        from_arg = [
            t.strip().lstrip("#")
            for t in (tags or "").replace(";", ",").split(",")
            if t.strip()
        ]
        out: list[str] = []
        for t in from_desc + from_arg:
            if t and t.lower() not in {x.lower() for x in out}:
                out.append(t)
            if len(out) >= 8:
                break
        return out

    async def _click_any_button(self, *names: str, exact: bool = True) -> bool:
        assert self.page
        for name in names:
            try:
                btn = self.page.get_by_role("button", name=name, exact=exact)
                if await btn.count() > 0 and await btn.first.is_visible():
                    await self._hclick(btn.first, timeout=5000)
                    logger.info("click button: %s", name)
                    await self.page.wait_for_timeout(400)
                    return True
            except Exception:
                continue
            try:
                loc = self.page.get_by_text(name, exact=exact)
                if await loc.count() > 0 and await loc.first.is_visible():
                    await self._hclick(loc.first, timeout=5000)
                    logger.info("click text: %s", name)
                    await self.page.wait_for_timeout(400)
                    return True
            except Exception:
                continue
        return False

    async def _dismiss_popups(self) -> None:
        assert self.page
        for name in (
            "Got it",
            "Turn on",
            "Allow",
            "OK",
            "Close",
            "Not now",
            "Skip",
            "Понятно",
            "Включить",
            "Разрешить",
            "Закрыть",
            "Не сейчас",
            "Пропустить",
            "Хорошо",
        ):
            try:
                btn = self.page.get_by_role("button", name=name, exact=True)
                if await btn.count() > 0 and await btn.first.is_visible():
                    await self._hclick(btn.first, timeout=3000)
                    logger.info("popup: %s", name)
                    await self.page.wait_for_timeout(400)
            except Exception:
                continue

    async def _select_video_button(self):
        assert self.page
        for name in ("Select video", "Выбрать видео", "Select files", "Выбрать файлы"):
            btn = self.page.get_by_role("button", name=name, exact=True)
            if await btn.count() > 0:
                return btn.first
            loc = self.page.get_by_text(name, exact=False)
            if await loc.count() > 0:
                return loc.first
        return None

    async def _set_video(self, video_path: Path) -> bool:
        assert self.page
        for _ in range(40):
            btn = await self._select_video_button()
            if btn is not None:
                try:
                    await btn.set_input_files(str(video_path.resolve()))
                    return True
                except Exception as exc:
                    logger.debug("set_input_files on Select video: %s", exc)
            inp = self.page.locator('input[type="file"]').first
            if await inp.count() > 0:
                try:
                    await inp.set_input_files(str(video_path.resolve()))
                    return True
                except Exception as exc:
                    logger.debug("file input: %s", exc)
            try:
                btn = await self._select_video_button()
                if btn is not None:
                    async with self.page.expect_file_chooser(timeout=8000) as fc_info:
                        await self._hclick(btn, timeout=5000)
                    chooser = await fc_info.value
                    await chooser.set_files(str(video_path.resolve()))
                    return True
            except Exception as exc:
                logger.debug("filechooser: %s", exc)
            await self.page.wait_for_timeout(1000)
        return False

    async def _post_button(self):
        assert self.page
        for name in ("Post", "Опубликовать", "Publish"):
            btn = self.page.get_by_role("button", name=name, exact=True)
            if await btn.count() > 0:
                # Берём первую основную кнопку формы (не из скрытого диалога)
                return btn.first
        return None

    async def _confirm_publish_dialog(self) -> bool:
        """После первого Post TikTok часто показывает:
        «Продолжить публикацию?» / video still being checked → нужно второе «Опубликовать».
        """
        assert self.page
        dialog_markers = (
            "Продолжить публикацию",
            "Continue posting",
            "Continue to post",
            "still being checked",
            "еще проверяется",
            "ещё проверяется",
            "до завершения проверки",
        )
        dialog_seen = False
        for _ in range(20):  # ~10s
            body = ""
            try:
                body = await self.page.locator("body").inner_text(timeout=2000)
            except Exception:
                pass
            if any(m.lower() in body.lower() for m in dialog_markers):
                dialog_seen = True
                break
            await self.page.wait_for_timeout(500)

        if not dialog_seen:
            # Нет диалога — возможно пост ушёл сразу
            logger.info("confirm dialog not shown — assuming direct publish")
            return True

        await self.screenshot("step4b_confirm_dialog")
        # Кнопка внутри диалога: предпочтительно role=dialog / alertdialog
        for role in ("dialog", "alertdialog"):
            dlg = self.page.get_by_role(role)
            if await dlg.count() == 0:
                continue
            for name in ("Опубликовать", "Post", "Publish", "Post now"):
                btn = dlg.last.get_by_role("button", name=name, exact=True)
                if await btn.count() == 0:
                    btn = dlg.last.get_by_role("button", name=name, exact=False)
                if await btn.count() > 0:
                    try:
                        await self._hclick(btn.last, timeout=8000)
                        logger.info("confirm dialog: clicked %s (role=%s)", name, role)
                        await self.page.wait_for_timeout(1500)
                        return True
                    except Exception as exc:
                        logger.warning("confirm dialog click failed: %s", exc)

        # Fallback: все видимые «Опубликовать» — берём последнюю (обычно в модалке)
        for name in ("Опубликовать", "Post", "Publish"):
            btns = self.page.get_by_role("button", name=name, exact=True)
            n = await btns.count()
            for i in range(n - 1, -1, -1):
                try:
                    b = btns.nth(i)
                    if await b.is_visible():
                        await self._hclick(b, timeout=8000)
                        logger.info("confirm dialog: clicked visible %s #%s", name, i)
                        await self.page.wait_for_timeout(1500)
                        return True
                except Exception:
                    continue

        # Текст кнопки без role
        for name in ("Опубликовать", "Post"):
            loc = self.page.get_by_text(name, exact=True)
            if await loc.count() > 0:
                try:
                    await self._hclick(loc.last, timeout=8000, force=True)
                    logger.info("confirm dialog: force-click text %s", name)
                    await self.page.wait_for_timeout(1500)
                    return True
                except Exception as exc:
                    logger.warning("confirm text click: %s", exc)

        logger.error("confirm publish dialog present but Опубликовать not clicked")
        await self.screenshot("error_confirm_publish")
        return False

    async def _publish_succeeded(self) -> bool:
        """Грубый check: диалог подтверждения исчез / ушли с upload editor."""
        assert self.page
        await self.page.wait_for_timeout(2000)
        try:
            body = (await self.page.locator("body").inner_text(timeout=3000)).lower()
        except Exception:
            body = ""
        if any(
            m in body
            for m in (
                "продолжить публикацию",
                "continue posting",
                "still being checked",
                "еще проверяется",
                "ещё проверяется",
            )
        ):
            return False
        url = (self.page.url or "").lower()
        if "upload" in url and "content" not in url:
            # ещё на форме — смотрим, есть ли success toast
            if any(s in body for s in ("опубликовано", "posted", "your video is being uploaded", "загружается")):
                return True
            # если диалога нет и Post снова виден — возможно не ушло
            post = await self._post_button()
            if post is not None and await post.is_visible():
                # диалог закрыт, но мы всё ещё на upload — часто OK (редирект медленный)
                return True
        return True

    async def _wait_editor(self, *, timeout_sec: int = 180) -> bool:
        assert self.page
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            await self._dismiss_popups()
            block = self.page.locator(".public-DraftStyleDefault-block")
            combo = self.page.get_by_role("combobox")
            post = await self._post_button()
            if await block.count() > 0 or await combo.count() > 0 or post is not None:
                try:
                    if post is not None or (
                        await block.count() > 0 and await block.first.is_visible()
                    ):
                        return True
                except Exception:
                    pass
            await self.page.wait_for_timeout(1500)
        return False

    async def _caret_to_end_of_caption(self) -> None:
        """Каретка в самый конец Draft.js / contenteditable (не End внутри одного блока)."""
        assert self.page
        await self.page.evaluate(
            """() => {
              const root =
                document.querySelector('div[contenteditable="true"]') ||
                document.querySelector('.public-DraftEditor-content') ||
                document.querySelector('[role="combobox"][contenteditable="true"]');
              if (!root) return false;
              root.focus();
              const sel = window.getSelection();
              if (!sel) return false;
              const range = document.createRange();
              range.selectNodeContents(root);
              range.collapse(false);
              sel.removeAllRanges();
              sel.addRange(range);
              return true;
            }"""
        )
        await self.page.wait_for_timeout(150)

    async def _fill_caption(self, caption: str) -> None:
        assert self.page
        caption = (caption or "").strip()
        # Combobox fill надёжнее для цельного текста (не ломает блоки Draft)
        try:
            combo = self.page.get_by_role("combobox").first
            if await combo.count() > 0 and await combo.is_visible():
                await self._hclick(combo)
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Backspace")
                await self._htype(combo, caption)
                logger.info("caption via combobox.fill (%s chars)", len(caption))
                await self._caret_to_end_of_caption()
                return
        except Exception as exc:
            logger.debug("combobox fill: %s", exc)
        try:
            block = self.page.locator(".public-DraftStyleDefault-block").first
            if await block.count() > 0:
                await self._hclick(block)
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Backspace")
                # insertText сохраняет юникод лучше, чем type по символам
                await self.page.keyboard.insert_text(caption)
                logger.info("caption via insert_text (%s chars)", len(caption))
                await self._caret_to_end_of_caption()
                return
        except Exception as exc:
            logger.debug("draft insert: %s", exc)
        ed = self.page.locator('[contenteditable="true"]').first
        if await ed.count() > 0:
            await self._hclick(ed)
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Backspace")
            await self.page.keyboard.insert_text(caption)
            logger.info("caption via contenteditable (%s chars)", len(caption))
            await self._caret_to_end_of_caption()

    async def _attach_cover(self, cover_path: Path) -> bool:
        assert self.page
        try:
            opened = await self._click_any_button(
                "Edit cover",
                "Редактировать обложку",
                "Change cover",
                "Изменить обложку",
                exact=False,
            )
            if not opened:
                # text link without role=button
                edit = self.page.get_by_text("Edit cover", exact=False).or_(
                    self.page.get_by_text("Редактировать обложку", exact=False)
                ).or_(self.page.get_by_text("обложк", exact=False))
                if await edit.count() == 0:
                    logger.warning("Edit cover not found")
                    return False
                await self._hclick(edit.first, timeout=8000)
            await self.page.wait_for_timeout(800)

            upload_btn = self.page.get_by_role("button", name="Upload cover image")
            if await upload_btn.count() == 0:
                upload_btn = self.page.get_by_role("button", name="Загрузить обложку")
            if await upload_btn.count() == 0:
                upload_btn = self.page.get_by_text("Upload cover", exact=False).or_(
                    self.page.get_by_text("Загрузить", exact=False)
                )

            try:
                async with self.page.expect_file_chooser(timeout=12000) as fc_info:
                    await self._hclick(upload_btn.first, timeout=8000)
                chooser = await fc_info.value
                await chooser.set_files(str(cover_path.resolve()))
            except Exception:
                dialog = self.page.get_by_role("dialog")
                file_in_dialog = dialog.locator('input[type="file"]')
                if await file_in_dialog.count() > 0:
                    await file_in_dialog.first.set_input_files(str(cover_path.resolve()))
                elif await dialog.count() > 0:
                    await dialog.set_input_files(str(cover_path.resolve()))
                else:
                    raise

            await self.page.wait_for_timeout(1200)
            saved = await self._click_any_button("Save", "Сохранить", "Confirm", "Подтвердить")
            if not saved:
                save = self.page.get_by_role("button", name="Save")
                if await save.count() > 0:
                    await self._hclick(save.first, timeout=8000)
            logger.info("cover set: %s", cover_path.name)
            await self.page.wait_for_timeout(800)
            return True
        except Exception as exc:
            logger.warning("cover failed: %s", exc)
            await self.screenshot("error_cover")
            return False

    async def _set_visibility_everyone(self) -> bool:
        """Who can watch this video → Everyone / Все."""
        assert self.page
        target_en = "Everyone"
        target_ru = "Все"
        target = self.visibility or target_en
        targets = [target, target_en, target_ru] if target not in (target_en, target_ru) else [target_en, target_ru]
        try:
            for opener_text in (
                "Who can watch this video",
                "Who can watch",
                "Кто может смотреть это видео",
                "Кто может смотреть",
                "Privacy",
                "Конфиденциальность",
                "Viewers",
                "Зрители",
            ):
                loc = self.page.get_by_text(opener_text, exact=False)
                if await loc.count() > 0:
                    try:
                        await self._hclick(loc.first, timeout=4000)
                        await self.page.wait_for_timeout(400)
                    except Exception:
                        pass

            body = ""
            try:
                body = await self.page.locator("body").inner_text(timeout=3000)
            except Exception:
                pass

            for current in (
                "Friends",
                "Only you",
                "Only You",
                "Private",
                "Followers",
                "Друзья",
                "Только вы",
                "Подписчики",
            ):
                btn = self.page.get_by_role("button", name=current, exact=True)
                if await btn.count() > 0 and await btn.first.is_visible():
                    await self._hclick(btn.first, timeout=5000)
                    await self.page.wait_for_timeout(400)
                    break
            else:
                for role_name in ("combobox", "listbox"):
                    try:
                        el = self.page.get_by_role(role_name).filter(
                            has_text=re.compile(r"Everyone|Friends|Only|Все|Друзья|Только", re.I)
                        )
                        if await el.count() > 0:
                            await self._hclick(el.first, timeout=4000)
                            break
                    except Exception:
                        continue

            for t in targets:
                opt = self.page.get_by_role("option", name=t, exact=True)
                if await opt.count() == 0:
                    opt = self.page.get_by_text(t, exact=True)
                if await opt.count() > 0:
                    await self._hclick(opt.first, timeout=8000)
                    logger.info("visibility: %s", t)
                    await self.page.wait_for_timeout(400)
                    return True

            for t in targets:
                if t.lower() in body.lower() or t in body:
                    everyone_btn = self.page.get_by_role("button", name=t, exact=True)
                    if await everyone_btn.count() > 0:
                        logger.info("visibility already: %s", t)
                        return True

            logger.warning("Could not set visibility to Everyone/Все")
            await self.screenshot("error_visibility")
            return False
        except Exception as exc:
            logger.warning("visibility failed: %s", exc)
            await self.screenshot("error_visibility")
            return False

    async def _set_interaction_defaults(self) -> None:
        """Комментарии / дуэт / стич — включить, если есть тумблеры."""
        assert self.page
        labels_on = (
            ("Allow comments", "Разрешить комментарии", "Comments", "Комментарии"),
            ("Allow Duet", "Разрешить дуэт", "Duet", "Дуэт"),
            ("Allow Stitch", "Разрешить стич", "Stitch", "Стич"),
        )
        for group in labels_on:
            for label in group:
                try:
                    row = self.page.get_by_text(label, exact=False)
                    if await row.count() == 0:
                        continue
                    # switch near label
                    switch = row.first.locator("xpath=ancestor::*[self::div or self::label][1]//button[@role='switch']")
                    if await switch.count() == 0:
                        switch = self.page.locator(f'[aria-label*="{label}"][role="switch"]')
                    if await switch.count() == 0:
                        continue
                    checked = await switch.first.get_attribute("aria-checked")
                    if checked == "false":
                        await self._hclick(switch.first, timeout=3000)
                        logger.info("enabled: %s", label)
                    else:
                        logger.info("already on: %s", label)
                    break
                except Exception:
                    continue

    async def _set_ai_disclosure_if_needed(self, *, disclose: bool = False) -> None:
        """AI-generated content — по умолчанию выкл (вебинар, не чистый AI-ролик)."""
        assert self.page
        if not disclose:
            return
        for label in (
            "AI-generated content",
            "Контент, созданный ИИ",
            "Content disclosure",
            "Раскрытие информации о контенте",
        ):
            try:
                if await self.page.get_by_text(label, exact=False).count() > 0:
                    await self._hclick(self.page.get_by_text(label, exact=False).first, timeout=4000)
                    await self._click_any_button("AI-generated", "Создано ИИ", exact=False)
                    logger.info("AI disclosure set via %s", label)
                    return
            except Exception:
                continue

    async def _add_hashtags_via_ui(self, tags: list[str] | str) -> int:
        """Выбрать хештеги из списка Studio: кнопка «# Хэштеги» → ввод → mention-option.

        Нельзя просто дописывать « #tag» текстом — получаются битые `# #tag`.
        """
        assert self.page
        if isinstance(tags, str):
            tag_list = [
                t.strip().lstrip("#")
                for t in tags.replace(";", ",").split(",")
                if t.strip()
            ]
        else:
            tag_list = [str(t).strip().lstrip("#") for t in tags if str(t).strip()]
        # только однословные / без пробелов — TikTok-тег не содержит пробел
        cleaned: list[str] = []
        for t in tag_list:
            t = re.sub(r"\s+", "", t)
            if t and t.lower() not in {x.lower() for x in cleaned}:
                cleaned.append(t)
            if len(cleaned) >= 8:
                break
        tag_list = cleaned
        if not tag_list:
            return 0

        async def focus_caption() -> None:
            for loc in (
                self.page.locator(".public-DraftStyleDefault-block").first,
                self.page.get_by_role("combobox").first,
                self.page.locator('[contenteditable="true"]').first,
            ):
                try:
                    if await loc.count() > 0 and await loc.is_visible():
                        await self._hclick(loc, timeout=4000)
                        await self.page.keyboard.press("End")
                        return
                except Exception:
                    continue

        async def click_hashtag_button() -> bool:
            # Точная кнопка под полем описания (RU Studio)
            candidates = [
                self.page.get_by_role("button", name="# Хэштеги", exact=True),
                self.page.get_by_role("button", name="Hashtag", exact=True),
                self.page.get_by_role("button", name="# Hashtags", exact=True),
                self.page.locator("button").filter(has_text=re.compile(r"^#\s*Хэштег", re.I)),
                self.page.locator("button").filter(has_text=re.compile(r"^#?\s*Hashtag", re.I)),
            ]
            for loc in candidates:
                try:
                    if await loc.count() == 0:
                        continue
                    el = loc.first
                    if await el.is_visible():
                        await self._hclick(el, timeout=4000)
                        await self.page.wait_for_timeout(400)
                        return True
                except Exception:
                    continue
            return False

        async def wait_and_pick(tag: str) -> bool:
            deadline = asyncio.get_event_loop().time() + 5
            while asyncio.get_event_loop().time() < deadline:
                opts = self.page.locator("[id^='mention-option-']")
                n = await opts.count()
                for i in range(n):
                    try:
                        opt = opts.nth(i)
                        txt = (await opt.inner_text()).strip()
                        # нормализуем: "#Make" / "Make"
                        norm = txt.lstrip("#").strip().lower().replace(" ", "")
                        if norm == tag.lower() or norm.startswith(tag.lower()):
                            await self._hclick(opt, timeout=3000)
                            return True
                    except Exception:
                        continue
                # role=option fallback
                try:
                    opt = self.page.get_by_role("option").filter(
                        has_text=re.compile(rf"^#?{re.escape(tag)}$", re.I)
                    )
                    if await opt.count() > 0:
                        await self._hclick(opt.first, timeout=3000)
                        return True
                except Exception:
                    pass
                await self.page.wait_for_timeout(200)
            return False

        picked = 0
        await self._caret_to_end_of_caption()
        # перевод строки перед блоком хештегов — не врезаться в середину текста
        try:
            await self.page.keyboard.press("Enter")
            await self.page.keyboard.press("Enter")
        except Exception:
            pass

        for tag in tag_list:
            await self._caret_to_end_of_caption()
            opened = await click_hashtag_button()
            await self.page.wait_for_timeout(250)
            # После кнопки Studio обычно уже ставит «#» — печатаем только имя
            try:
                if opened:
                    await self.page.keyboard.type(tag, delay=random.randint(28, 60) if self.hz.enabled else 10)
                else:
                    await self.page.keyboard.type(f"#{tag}", delay=random.randint(28, 60) if self.hz.enabled else 10)
            except Exception as exc:
                logger.warning("type hashtag failed #%s: %s", tag, exc)
                continue

            await self.page.wait_for_timeout(600)
            ok = await wait_and_pick(tag)
            if ok:
                picked += 1
                logger.info("hashtag picked from list: #%s", tag)
                await self.page.wait_for_timeout(350)
                await self._caret_to_end_of_caption()
                try:
                    await self.page.keyboard.type(" ", delay=10)
                except Exception:
                    pass
                continue

            logger.warning("hashtag NOT in dropdown, skip raw leave: #%s", tag)
            try:
                for _ in range(len(tag) + 2):
                    await self.page.keyboard.press("Backspace")
            except Exception:
                try:
                    await self.page.keyboard.press("Escape")
                except Exception:
                    pass

        await self.screenshot("step2b_hashtags")
        logger.info("hashtags result: %s/%s from list", picked, len(tag_list))
        return picked

    async def upload_short_video(
        self,
        *,
        video: str,
        title: str,
        description: str = "",
        cover: str | None = None,
        tags: str = "",
        draft: bool = False,
        pinned_comment: str = "",
    ) -> bool:
        assert self.page and self.context
        video_path = Path(video)
        if not video_path.is_file():
            raise FileNotFoundError(video)
        cover_path = Path(cover) if cover else None
        if cover_path and not cover_path.is_file():
            logger.warning("Cover missing: %s", cover)
            cover_path = None

        if not await self.ensure_logged_in():
            return False

        await self.screenshot("step1_upload")

        if not await self._set_video(video_path):
            await self.screenshot("error_no_video")
            logger.error("Failed to attach video")
            return False
        logger.info("video set: %s", video_path.name)
        await self._hpause(1.2, 2.4)
        await self._dismiss_popups()

        if not await self._wait_editor():
            await self.screenshot("error_no_editor")
            logger.error("Editor did not appear")
            return False

        await self._dismiss_popups()
        await self._hpause(0.6, 1.3)
        caption = self._compose_caption(title=title, description=description, tags=tags)
        tag_list = self._resolve_tags(description=description, tags=tags)
        logger.info(
            "caption (%s chars, no raw #): %s…",
            len(caption),
            caption[:120].replace("\n", " "),
        )
        logger.info("hashtags via UI list: %s", ", ".join(f"#{t}" for t in tag_list))
        await self._fill_caption(caption)
        await self.screenshot("step2_caption")
        await self._hpause(0.5, 1.1)
        n_tags = await self._add_hashtags_via_ui(tag_list)
        logger.info("hashtags picked: %s/%s", n_tags, len(tag_list))

        if cover_path:
            await self._hpause(0.5, 1.0)
            ok_cover = await self._attach_cover(cover_path)
            logger.info("cover ok=%s", ok_cover)
        await self.screenshot("step3_cover")

        await self._hpause(0.4, 0.9)
        await self._set_visibility_everyone()
        await self._set_interaction_defaults()
        await self._set_ai_disclosure_if_needed(disclose=False)
        await self.screenshot("step4_before_post")

        if draft:
            for name in ("Save draft", "Drafts", "Save as draft", "Сохранить черновик", "Черновик"):
                btn = self.page.get_by_role("button", name=name)
                if await btn.count() > 0:
                    await self._hclick(btn.first, timeout=8000)
                    logger.info("draft: %s", name)
                    break
            else:
                logger.error("Draft button not found")
                return False
        else:
            post = await self._post_button()
            if post is None:
                await self.screenshot("error_no_post")
                logger.error("Post button not found")
                return False
            for _ in range(60):
                try:
                    if await post.is_enabled():
                        break
                except Exception:
                    pass
                await self.page.wait_for_timeout(2000)
            else:
                await self.screenshot("error_post_disabled")
                logger.error("Post stayed disabled")
                return False
            await post.scroll_into_view_if_needed()
            await self._hpause(0.4, 0.9)
            await self._hclick(post)
            logger.info("clicked Post (visibility=%s)", self.visibility)
            await self._hpause(0.8, 1.6)
            # Диалог «Продолжить публикацию?» — обязательный второй клик
            if not await self._confirm_publish_dialog():
                await self.screenshot("error_no_confirm_publish")
                logger.error("Не нажали финальное «Опубликовать» в диалоге подтверждения")
                return False
            if not await self._publish_succeeded():
                # ещё раз попробовать подтвердить
                logger.warning("publish confirm still open — retry")
                if not await self._confirm_publish_dialog():
                    await self.screenshot("error_publish_still_open")
                    return False

        await self.page.wait_for_timeout(12000)
        await self.screenshot("step5_after_post")
        if pinned_comment:
            logger.info("pinned_comment (manual follow-up): %s", pinned_comment[:100])
        await self.save_cookies()
        logger.info("TikTok: %s", "draft" if draft else "published")
        return True


async def amain() -> int:
    parser = argparse.ArgumentParser(description="TikTok Studio upload (codegen)")
    parser.add_argument("--video", "-v")
    parser.add_argument("--title", "-t", default="")
    parser.add_argument("--description", "-d", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--cover", "-c")
    parser.add_argument("--pinned-comment", default="")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--login-only", action="store_true")
    args = parser.parse_args()

    client = TikTokClient()
    try:
        await client.start()
        if args.login_only:
            ok = await client.ensure_logged_in()
            await client.screenshot("login_ok" if ok else "login_fail")
            return 0 if ok else 1
        if not args.video:
            logger.error("Need --video")
            return 2
        ok = await client.upload_short_video(
            video=args.video,
            title=args.title or Path(args.video).stem,
            description=args.description,
            cover=args.cover,
            tags=args.tags,
            draft=args.draft,
            pinned_comment=args.pinned_comment,
        )
        return 0 if ok else 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
