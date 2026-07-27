#!/usr/bin/env python3
"""Playwright-клиент Instagram Reels по живой записи codegen (2026-07-27).

Сценарий:
  1) https://www.instagram.com/ + secrets/instagram_storage_state.json
  2) «Новая публикация / Создать»
  3) hidden input[type=file] → set_input_files(video)
     (НЕ кликать «Выбрать на компьютере» — иначе Windows Open dialog)
  4) OK (если есть) → crop 9:16 → Далее
  5) опционально обложка JPG (отдельный image input) → Далее
  6) подпись
  7) «Поделиться» → ждать «Reels опубликовано»

Запись: scripts/recordings/instagram_publish_codegen.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
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
_SHOT_DIR = _LOG_DIR / "instagram-screenshots"
_SHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "instagram_autopost.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("instagram_client")

for _env_path in (
    _PLUGIN_ROOT / "videoshorts.local.env",
    _PLUGIN_ROOT / ".env",
):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
load_dotenv(override=False)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class InstagramClient:
    HOME_URL = "https://www.instagram.com/"

    def __init__(self) -> None:
        default_storage = (
            _PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "instagram_storage_state.json"
        )
        self.storage_state_path = Path(
            os.getenv(
                "VIDEOSHORTS_INSTAGRAM_STORAGE",
                os.getenv("INSTAGRAM_STORAGE_STATE", str(default_storage)),
            )
        )
        self.headless = os.getenv("HEADLESS", "false").lower() == "true"
        self.timeout = int(os.getenv("BROWSER_TIMEOUT", "180000"))
        force_close = os.getenv("VIDEOSHORTS_FORCE_CLOSE_BROWSER", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        self.keep_open = (
            os.getenv("KEEP_BROWSER_OPEN", "false").lower() == "true"
        ) and not force_close
        self.locale = os.getenv("INSTAGRAM_LOCALE", "ru-RU")
        self.timezone_id = os.getenv("INSTAGRAM_TZ", "Europe/Moscow")
        self.aspect = os.getenv("INSTAGRAM_ASPECT", "9:16")

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
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
            headless=self.headless,
            args=launch_args,
        )
        ctx_kwargs: dict = {
            "viewport": {"width": 1440, "height": 1000},
            "locale": self.locale,
            "timezone_id": self.timezone_id,
        }
        storage = Path(self.storage_state_path)
        if storage.is_file() and storage.stat().st_size > 100:
            ctx_kwargs["storage_state"] = str(storage)
            logger.info("Cookies: %s", storage)
        else:
            logger.warning("No Instagram cookies — run instagram_login_save.py")

        self.context = await self.browser.new_context(**ctx_kwargs)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)

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
        assert self.page
        path = _SHOT_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await self.page.screenshot(path=str(path), full_page=False)
        logger.info("screenshot: %s", path.name)
        return path

    async def _click_first(
        self,
        *candidates: tuple[str, str],
        timeout: int = 8000,
        required: bool = True,
    ) -> bool:
        assert self.page
        last_err: Exception | None = None
        for kind, value in candidates:
            try:
                if kind == "role_button":
                    loc = self.page.get_by_role("button", name=value)
                elif kind == "role_link":
                    loc = self.page.get_by_role("link", name=value)
                elif kind == "text":
                    loc = self.page.get_by_text(value, exact=False)
                elif kind == "button_filter":
                    loc = self.page.locator("button").filter(has_text=value)
                elif kind == "css":
                    loc = self.page.locator(value)
                else:
                    continue
                target = loc.first
                await target.wait_for(state="visible", timeout=timeout)
                await target.click(timeout=timeout)
                logger.info("click OK: %s=%s", kind, value)
                return True
            except Exception as exc:
                last_err = exc
                continue
        if required:
            raise RuntimeError(f"Не удалось кликнуть ни один из кандидатов; last={last_err}")
        logger.info("optional click skipped; last=%s", last_err)
        return False

    async def _dismiss_noise(self) -> None:
        assert self.page
        for name in ("Не сейчас", "Not Now", "Accept", "Принять"):
            try:
                btn = self.page.get_by_role("button", name=name).first
                if await btn.count() and await btn.is_visible():
                    await btn.click(timeout=2000)
                    await self.page.wait_for_timeout(500)
                    logger.info("dismissed: %s", name)
            except Exception:
                continue

    async def ensure_logged_in(self) -> bool:
        assert self.page
        await self.page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=120000)
        await self.page.wait_for_timeout(2000)
        await self._dismiss_noise()
        url = (self.page.url or "").lower()
        if "accounts/login" in url:
            logger.error("Not logged in — run instagram_login_save.py")
            await self.screenshot("error_not_logged_in")
            return False
        names = {c.get("name") for c in await self.context.cookies()}
        if "sessionid" not in names:
            logger.error("sessionid missing")
            await self.screenshot("error_no_sessionid")
            return False
        logger.info("Session OK: %s", self.page.url)
        return True

    async def _set_latest_file(
        self,
        path: Path,
        *,
        timeout: int = 20000,
        prefer: str = "any",
        min_index: int = 0,
    ) -> None:
        assert self.page
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        if prefer == "image":
            inputs = self.page.locator(
                'input[type="file"][accept*="image"], '
                'input[type="file"]:not([accept*="video"])'
            )
        elif prefer == "video":
            inputs = self.page.locator(
                'input[type="file"][accept*="video"], input[type="file"]'
            )
        else:
            inputs = self.page.locator('input[type="file"]')

        deadline = asyncio.get_event_loop().time() + (timeout / 1000)
        count = 0
        while asyncio.get_event_loop().time() < deadline:
            count = await inputs.count()
            if count > min_index:
                break
            await self.page.wait_for_timeout(250)
        if count <= min_index:
            await self.screenshot("error_no_file_input")
            raise RuntimeError(
                f"input[type=file] не найден (prefer={prefer}, min_index={min_index})"
            )

        idx = count - 1
        await inputs.nth(idx).set_input_files(str(path))
        logger.info(
            "set_input_files[%s] prefer=%s (no native dialog) → %s",
            idx,
            prefer,
            path.name,
        )
        await self.page.wait_for_timeout(1500)

    async def publish_video(
        self,
        *,
        video: Path,
        caption: str = "",
        cover: Path | None = None,
        location: str = "",
        dry_run: bool = False,
    ) -> dict:
        assert self.page
        video = Path(video).resolve()
        if cover is not None:
            cover = Path(cover).resolve()
            if not cover.is_file():
                raise FileNotFoundError(cover)

        result: dict = {
            "ok": False,
            "video": str(video),
            "cover": str(cover) if cover else None,
            "caption": caption,
            "location": location or None,
            "dry_run": dry_run,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        for _ in range(2):
            try:
                close_btn = self.page.locator(
                    'svg[aria-label="Закрыть"], svg[aria-label="Close"]'
                ).first
                if await close_btn.count() and await close_btn.is_visible():
                    await close_btn.click(timeout=2000)
                    await self.page.wait_for_timeout(800)
            except Exception:
                break

        await self._click_first(
            ("role_link", "Новая публикация Создать"),
            ("role_link", "New post Create"),
            ("css", 'svg[aria-label="Новая публикация"]'),
            ("css", 'svg[aria-label="New post"]'),
            ("css", 'a[href*="/create"]'),
            timeout=20000,
        )
        await self.page.wait_for_timeout(1500)

        logger.info("upload video via hidden file input (skip native dialog)")
        await self._set_latest_file(video, prefer="video")
        await self.page.wait_for_timeout(4000)

        await self._click_first(
            ("role_button", "OK"),
            ("role_button", "Ок"),
            required=False,
            timeout=5000,
        )
        await self.page.wait_for_timeout(1500)

        await self._click_first(
            ("button_filter", "Выбрать размер и обрезать"),
            ("button_filter", "Select crop"),
            ("css", 'svg[aria-label="Выбрать размер и обрезать"]'),
            ("css", 'svg[aria-label="Select crop"]'),
            required=False,
            timeout=8000,
        )
        await self.page.wait_for_timeout(500)
        await self._click_first(
            ("role_button", self.aspect),
            ("text", self.aspect),
            required=False,
            timeout=5000,
        )
        await self.page.wait_for_timeout(500)

        await self._click_first(
            ("role_button", "Далее"),
            ("role_button", "Next"),
            timeout=15000,
        )
        await self.page.wait_for_timeout(1200)

        if cover is not None:
            try:
                before = await self.page.locator('input[type="file"]').count()
                await self._click_first(
                    ("button_filter", "Обложка"),
                    ("button_filter", "Cover"),
                    ("text", "Добавить обложку"),
                    ("text", "Edit cover"),
                    ("css", 'svg[aria-label="Обложка"]'),
                    required=False,
                    timeout=4000,
                )
                await self.page.wait_for_timeout(800)
                logger.info("upload cover via image file input (skip native dialog)")
                try:
                    await self._set_latest_file(cover, prefer="image", timeout=8000)
                except Exception:
                    after = await self.page.locator('input[type="file"]').count()
                    if after > before:
                        await self._set_latest_file(
                            cover, prefer="any", min_index=before, timeout=5000
                        )
                    else:
                        raise RuntimeError("отдельный input для обложки не появился")
            except Exception as exc:
                logger.warning("cover upload skipped: %s", exc)
            await self.page.wait_for_timeout(800)

        for _ in range(2):
            caption_box = self.page.get_by_role("textbox", name="Добавьте подпись…")
            if await caption_box.count() == 0:
                caption_box = self.page.get_by_role("textbox", name="Write a caption...")
            try:
                if await caption_box.count() and await caption_box.first.is_visible():
                    break
            except Exception:
                pass
            clicked = await self._click_first(
                ("role_button", "Далее"),
                ("role_button", "Next"),
                required=False,
                timeout=5000,
            )
            if not clicked:
                break
            await self.page.wait_for_timeout(1000)

        if caption:
            filled = False
            for name in ("Добавьте подпись…", "Write a caption...", "Write a caption…"):
                try:
                    box = self.page.get_by_role("textbox", name=name).first
                    await box.wait_for(state="visible", timeout=8000)
                    await box.click()
                    await box.fill(caption[:2200])
                    filled = True
                    logger.info("caption filled (%s chars)", len(caption[:2200]))
                    break
                except Exception:
                    continue
            if not filled:
                await self.screenshot("error_caption")
                raise RuntimeError("Не найдено поле подписи")

        if location:
            try:
                loc_box = self.page.get_by_role("textbox", name="Добавить место")
                if await loc_box.count() == 0:
                    loc_box = self.page.get_by_role("textbox", name="Add location")
                await loc_box.first.click(timeout=5000)
                await loc_box.first.fill(location)
                await self.page.wait_for_timeout(1200)
                suggestion = self.page.get_by_role("button", name=location).first
                if await suggestion.count():
                    await suggestion.click(timeout=3000)
                else:
                    await self.page.keyboard.press("Enter")
                logger.info("location set: %s", location)
            except Exception as exc:
                logger.warning("location skipped: %s", exc)

        await self.screenshot("before_share")

        if dry_run:
            result.update(
                {
                    "ok": True,
                    "published": False,
                    "message": "dry_run: stopped before Share",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return result

        await self._click_first(
            ("role_button", "Поделиться"),
            ("role_button", "Share"),
            ("text", "Поделиться"),
            ("text", "Share"),
            timeout=20000,
        )
        await self.page.wait_for_timeout(2000)
        await self.screenshot("after_share")

        done_texts = (
            "Реels опубликован",
            "Видео Reels опубликовано",
            "Ваше видео Reels опубликовано",
            "Reel shared",
            "Your reel has been shared",
            "публикация опубликована",
            "Ваша публикация опубликована",
            "Post shared",
            "опубликовано",
        )
        found = False
        for i in range(90):
            for t in done_texts:
                try:
                    loc = self.page.get_by_text(t, exact=False).first
                    if await loc.count() and await loc.is_visible():
                        found = True
                        logger.info("publish success text: %s", t)
                        break
                except Exception:
                    continue
            if found:
                break
            try:
                publishing = self.page.get_by_text("Публикация", exact=True)
                if await publishing.count() and await publishing.first.is_visible():
                    if i % 5 == 0:
                        logger.info("still publishing… (%ss)", i * 2)
                    await self.page.wait_for_timeout(2000)
                    continue
            except Exception:
                pass
            try:
                share_btn = self.page.get_by_role("button", name="Поделиться")
                if await share_btn.count() == 0:
                    logger.info("share dialog closed")
                    found = True
                    break
            except Exception:
                pass
            await self.page.wait_for_timeout(2000)

        await self.screenshot("publish_done")
        await self.save_cookies()
        result.update(
            {
                "ok": True,
                "published": True,
                "share_clicked": True,
                "success_text_seen": found,
                "url": self.page.url,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return result


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Instagram Reels auto-publish (Playwright)")
    parser.add_argument("--video", default="", help="Path to mp4")
    parser.add_argument("--caption", default="", help="Post caption")
    parser.add_argument("--caption-file", default="", help="UTF-8 file with caption")
    parser.add_argument("--cover", default="", help="Optional cover image")
    parser.add_argument("--location", default="", help="Optional location")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    if args.keep_open:
        os.environ["KEEP_BROWSER_OPEN"] = "true"

    client = InstagramClient()
    try:
        await client.start()
        if not await client.ensure_logged_in():
            return 2
        if args.login_only:
            await client.save_cookies()
            print(json.dumps({"ok": True, "mode": "login_only"}, ensure_ascii=False))
            return 0
        if not args.video:
            print("[ERROR] --video required", file=sys.stderr)
            return 2
        caption = args.caption
        if args.caption_file:
            caption = Path(args.caption_file).expanduser().resolve().read_text(encoding="utf-8")
        result = await client.publish_video(
            video=Path(args.video),
            caption=caption,
            cover=Path(args.cover) if args.cover else None,
            location=args.location,
            dry_run=args.dry_run,
        )
        _write_json(_LOG_DIR / "instagram-publish-last.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    except Exception as exc:
        logger.exception("publish failed: %s", exc)
        try:
            await client.screenshot("error_fatal")
        except Exception:
            pass
        _write_json(
            _LOG_DIR / "instagram-publish-last.json",
            {
                "ok": False,
                "error": str(exc),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 1
    finally:
        await client.close()


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
