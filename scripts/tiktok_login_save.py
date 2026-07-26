#!/usr/bin/env python3
"""Ручная регистрация / вход TikTok через Playwright → cookies.

ВАЖНО: перед запуском VPN должен показывать НЕ-РФ IP (проверка whoer/2ip).
"""
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
DEFAULT_STORAGE = PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "tiktok_storage_state.json"
SIGNUP_URL = "https://www.tiktok.com/signup"
STUDIO_URL = "https://www.tiktok.com/tiktokstudio/upload"


def _load_local_env(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    env_path = root / "videoshorts.local.env"
    if not env_path.is_file():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key:
            out[key] = val
            os.environ.setdefault(key, val)
    return out


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_storage() -> Path:
    raw = (
        os.getenv("VIDEOSHORTS_TIKTOK_STORAGE")
        or os.getenv("TIKTOK_STORAGE_STATE")
        or str(DEFAULT_STORAGE)
    )
    path = Path(raw)
    if not path.is_absolute():
        path = PLUGIN_ROOT / path
    return path


def _looks_logged_in(url: str) -> bool:
    u = (url or "").lower()
    if not u or "tiktok.com" not in u:
        return False
    if any(x in u for x in ("/login", "/signup", "passport")):
        return False
    return any(
        x in u
        for x in (
            "/foryou",
            "/following",
            "/tiktokstudio",
            "/upload",
            "/@",
            "/messages",
        )
    )


async def run_manual_register(*, timeout_sec: int = 900) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[ERROR] pip install playwright && playwright install chromium", file=sys.stderr)
        return 2

    storage = resolve_storage()
    if storage.is_file():
        bak = storage.with_suffix(storage.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        storage.replace(bak)
        print(f"Old cookies → {bak.name}")

    print("=" * 50)
    print("TIKTOK REGISTER / LOGIN")
    print(f"Open: {SIGNUP_URL}")
    print("1) Use EMAIL (preferred) or foreign phone — NOT +7")
    print("2) Finish signup / verify email if asked")
    print("3) Wait until you see For You / profile / Studio")
    print("4) Cookies save automatically")
    print(f"Wait up to {timeout_sec // 60} min")
    print("=" * 50)

    async with async_playwright() as p:
        try:
            from playwright_display import chromium_window_args, describe_placement

            launch_args = chromium_window_args(maximize=True) + [
                "--disable-blink-features=AutomationControlled"
            ]
            print(f"Display: {describe_placement()}")
        except Exception as exc:
            print(f"[WARN] playwright_display: {exc}")
            launch_args = ["--start-maximized", "--disable-blink-features=AutomationControlled"]
        browser = await p.chromium.launch(
            headless=False,
            args=launch_args,
        )
        context = await browser.new_context(
            viewport=None,
            locale="en-US",
            timezone_id=os.getenv("TIKTOK_TZ", "Europe/Vilnius"),
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=120000)

        ok = False
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            url = page.url or ""
            logged = False
            try:
                # Avatar / upload / studio markers
                if await page.locator('[data-e2e="nav-upload"], [data-e2e="top-login-button"]').count() == 0:
                    pass
                upload = page.locator(
                    '[data-e2e="nav-upload"], a[href*="upload"], '
                    'a[href*="tiktokstudio"], [data-e2e="user-avatar"]'
                )
                if await upload.count() > 0 and _looks_logged_in(url):
                    logged = True
                if "/tiktokstudio" in url.lower() or "/upload" in url.lower():
                    logged = True
                # After signup often lands on foryou with avatar
                avatar = page.locator('[data-e2e="user-avatar"], [data-e2e="profile-icon"]')
                if await avatar.count() > 0 and "signup" not in url.lower() and "login" not in url.lower():
                    logged = True
            except Exception:
                pass

            if logged:
                await page.wait_for_timeout(2500)
                ok = True
                break

            left = int(deadline - asyncio.get_event_loop().time())
            print(f"...waiting login ({left}s) url={url[:110]}", flush=True)
            await page.wait_for_timeout(4000)

        if not ok:
            print("[ERROR] Timeout — cookies NOT saved. Finish signup and retry.", file=sys.stderr)
            await browser.close()
            return 1

        # Soft check: try studio upload page
        try:
            await page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        storage.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(storage))
        print(f"[OK] Cookies saved: {storage}")
        print(f"     size={storage.stat().st_size}")

        _write_json(
            PLUGIN_ROOT / "videoshorts-memory" / "output" / "tiktok-login-log.json",
            {
                "ok": True,
                "mode": "manual_register_login",
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
    raise SystemExit(asyncio.run(run_manual_register(timeout_sec=900)))


if __name__ == "__main__":
    main()
