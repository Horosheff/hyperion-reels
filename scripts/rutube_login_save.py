#!/usr/bin/env python3
"""Ручной вход в RuTube: браузер → логин → cookies в secrets/rutube_storage_state.json."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORAGE = PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "rutube_storage_state.json"
STUDIO_URL = "https://studio.rutube.ru/"
UPLOADER_URL = "https://studio.rutube.ru/uploader/"


def _load_local_env(root: Path) -> dict[str, str]:
    env_path = root / "videoshorts.local.env"
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
            os.environ.setdefault(key, val)
    return out


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_storage() -> Path:
    raw = (
        os.getenv("VIDEOSHORTS_RUTUBE_STORAGE")
        or os.getenv("RUTUBE_STORAGE_STATE")
        or str(DEFAULT_STORAGE)
    )
    path = Path(raw)
    if not path.is_absolute():
        path = PLUGIN_ROOT / path
    return path


def _looks_logged_in(url: str) -> bool:
    u = (url or "").lower()
    if not u:
        return False
    if any(x in u for x in ("login", "auth", "passport", "accounts.google", "oauth")):
        # studio sometimes keeps auth in popup — main URL may still be studio
        if "studio.rutube.ru" in u and "login" not in u:
            return True
        return False
    return "studio.rutube.ru" in u or ("rutube.ru" in u and "/channel/" in u)


async def run_manual_login(*, timeout_sec: int = 600) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "[ERROR] Нужен playwright: pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 2

    storage = resolve_storage()
    channel_id = os.getenv("RUTUBE_CHANNEL_ID", "33566314")
    channel_url = os.getenv("RUTUBE_CHANNEL_URL", f"https://rutube.ru/channel/{channel_id}/")

    backup = None
    if storage.is_file():
        backup = storage.with_suffix(storage.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        storage.replace(backup)
        print(f"Старые cookies → {backup.name}")

    print("=" * 50)
    print("РУЧНОЙ ВХОД В RUTUBE")
    print(f"Канал: {channel_id}")
    print(f"URL:   {channel_url}")
    print(f"Студия:{STUDIO_URL}")
    print("1) В открывшемся окне войдите в аккаунт RuTube")
    print("2) Дождитесь Студии (studio.rutube.ru)")
    print("3) Cookies сохранятся сами")
    print(f"Ожидание до {timeout_sec // 60} мин…")
    print("=" * 50)

    async with async_playwright() as p:
        try:
            from playwright_display import describe_placement, headed_launch_args

            launch_args = headed_launch_args()
            print(f"Display: {describe_placement()}")
        except Exception as exc:
            print(f"[WARN] playwright_display: {exc}")
            launch_args = ["--start-maximized"]
        browser = await p.chromium.launch(headless=False, args=launch_args)
        context = await browser.new_context(viewport=None)
        page = await context.new_page()
        await page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=120000)

        ok = False
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            url = page.url or ""
            try:
                # Типичные маркеры студии после входа
                has_upload = await page.locator(
                    'a[href*="uploader"], button:has-text("Загрузить"), '
                    '[data-testid*="upload"], text=Загрузить видео'
                ).count()
            except Exception:
                has_upload = 0

            if _looks_logged_in(url) and ("studio.rutube.ru" in url.lower()):
                # Не на странице логина
                body = ""
                try:
                    body = (await page.locator("body").inner_text(timeout=2000))[:800].lower()
                except Exception:
                    pass
                login_wall = any(
                    m in body
                    for m in (
                        "войти или зарегистрироваться",
                        "вход и регистрация",
                        "войдите в аккаунт",
                    )
                )
                if not login_wall and (has_upload > 0 or "/uploader" in url or "studio.rutube.ru" in url):
                    # Даем UI догрузиться
                    await page.wait_for_timeout(2000)
                    url2 = page.url or ""
                    if "studio.rutube.ru" in url2.lower() and "login" not in url2.lower():
                        ok = True
                        break

            await page.wait_for_timeout(3000)
            left = int(deadline - asyncio.get_event_loop().time())
            print(f"…ждём вход ({left}с)  url={url[:120]}", flush=True)

        if not ok:
            print("[ERROR] Таймаут: вход не обнаружен. Cookies не сохранены.", file=sys.stderr)
            if backup and backup.is_file() and not storage.is_file():
                backup.replace(storage)
                print("Восстановил старые cookies")
            await browser.close()
            return 1

        # Для проверки — открыть uploader (не обязательно оставаться)
        try:
            await page.goto(UPLOADER_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        storage.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(storage))
        print(f"[OK] Cookies saved: {storage}")
        print(f"   size={storage.stat().st_size} channel={channel_id}")

        log_path = PLUGIN_ROOT / "videoshorts-memory" / "output" / "rutube-login-log.json"
        _write_json(
            log_path,
            {
                "ok": True,
                "mode": "manual_login_save",
                "channel_id": channel_id,
                "channel_url": channel_url,
                "storage": str(storage.resolve()),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "url": page.url,
            },
        )

        await page.wait_for_timeout(1500)
        await browser.close()
        return 0


def main() -> None:
    _load_local_env(PLUGIN_ROOT)
    os.environ["HEADLESS"] = "false"
    raise SystemExit(asyncio.run(run_manual_login(timeout_sec=600)))


if __name__ == "__main__":
    main()
