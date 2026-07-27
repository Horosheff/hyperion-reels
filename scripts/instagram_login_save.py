#!/usr/bin/env python3
"""Ручной вход в Instagram через Playwright → cookies.

Как vk_login_save.py: браузер открывается, вы логинитесь сами,
скрипт ждёт sessionid и сохраняет storage_state в secrets/ (не в git).
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
DEFAULT_STORAGE = (
    PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "instagram_storage_state.json"
)
LOGIN_URL = "https://www.instagram.com/accounts/login/"
HOME_URL = "https://www.instagram.com/"
SESSION_COOKIE_NAMES = {"sessionid", "ds_user_id"}
AUTH_MARKERS = (
    "accounts/login",
    "accounts/emailsignup",
    "/challenge/",
    "two_factor",
)


def _load_local_env(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for env_path in (root / "videoshorts.local.env", root / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
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
        os.getenv("VIDEOSHORTS_INSTAGRAM_STORAGE")
        or os.getenv("INSTAGRAM_STORAGE_STATE")
        or str(DEFAULT_STORAGE)
    )
    path = Path(raw)
    if not path.is_absolute():
        path = PLUGIN_ROOT / path
    return path


def _is_auth_url(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in AUTH_MARKERS)


async def _session_cookie_names(page) -> set[str]:
    try:
        cookies = await page.context.cookies()
    except Exception:
        return set()
    return {str(c.get("name")) for c in cookies if isinstance(c, dict) and c.get("name")}


async def _page_looks_logged_in(page) -> tuple[bool, str]:
    url = page.url or ""
    if _is_auth_url(url):
        return False, f"still_on_auth url={url[:120]}"
    names = await _session_cookie_names(page)
    strong = names & SESSION_COOKIE_NAMES
    if "sessionid" not in strong:
        return False, f"no_sessionid have={sorted(names)[:12]} url={url[:90]}"
    for sel in (
        'input[name="username"]',
        'input[name="password"]',
        'button:has-text("Log in")',
        'button:has-text("Войти")',
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return False, f"login_form_visible cookies={sorted(strong)}"
        except Exception:
            continue
    if "instagram.com" in url.lower() and strong:
        return True, f"ok session={sorted(strong)} url={url[:100]}"
    return False, f"waiting strong={sorted(strong)} url={url[:100]}"


async def run_manual_login(*, timeout_sec: int = 1200) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "[ERROR] pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 2

    storage = resolve_storage()
    if storage.is_file():
        bak = storage.with_suffix(
            storage.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        storage.replace(bak)
        print(f"Старые cookies → {bak.name}")

    print("=" * 56)
    print("ВХОД В INSTAGRAM")
    print("1) Войдите в аккаунт в открывшемся окне")
    print("2) Пройдите 2FA / checkpoint при необходимости")
    print("3) Дождитесь ленты / профиля")
    print("4) Cookies сохранятся сами в secrets/ (не в git)")
    print(f"Жду до {timeout_sec // 60} минут")
    print("=" * 56)

    async with async_playwright() as p:
        try:
            from playwright_display import chromium_window_args, describe_placement

            launch_args = chromium_window_args(maximize=True) + [
                "--disable-blink-features=AutomationControlled"
            ]
            print(f"Display: {describe_placement()}")
        except Exception as exc:
            print(f"[WARN] playwright_display: {exc}")
            launch_args = [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ]
        browser = await p.chromium.launch(headless=False, args=launch_args)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale=os.getenv("INSTAGRAM_LOCALE", "ru-RU"),
            timezone_id=os.getenv("INSTAGRAM_TZ", "Europe/Moscow"),
        )
        page = await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(2000)
        print("Браузер открыт — логиньтесь…", flush=True)

        ok = False
        reason = ""
        stable_hits = 0
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            try:
                if page.is_closed():
                    print("[ERROR] Браузер закрыт — cookies не сохранены.", file=sys.stderr)
                    return 1
                if _is_auth_url(page.url or ""):
                    stable_hits = 0
                    left = int(deadline - asyncio.get_event_loop().time())
                    print(
                        f"…авторизация ({left}с) url={(page.url or '')[:110]}",
                        flush=True,
                    )
                    await page.wait_for_timeout(3000)
                    continue
                ok, reason = await _page_looks_logged_in(page)
                left = int(deadline - asyncio.get_event_loop().time())
                print(f"…проверка ({left}с) {reason}", flush=True)
                if ok:
                    stable_hits += 1
                    if stable_hits >= 3:
                        break
                else:
                    stable_hits = 0
                await page.wait_for_timeout(3000)
            except Exception as loop_exc:
                name = type(loop_exc).__name__
                if "TargetClosed" in name or "closed" in str(loop_exc).lower():
                    print("[ERROR] Браузер закрыт — cookies не сохранены.", file=sys.stderr)
                    return 1
                print(f"[WARN] login loop: {loop_exc}", flush=True)
                await asyncio.sleep(2)

        if not ok or stable_hits < 3:
            print("[ERROR] Вход не подтверждён. Cookies не сохранены.", file=sys.stderr)
            await browser.close()
            return 1

        try:
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        storage.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(storage))
        print(f"✅ Cookies сохранены: {storage}")
        print(f"   size={storage.stat().st_size}")
        _write_json(
            PLUGIN_ROOT / "videoshorts-memory" / "output" / "instagram-login-log.json",
            {
                "ok": True,
                "mode": "manual_login_save",
                "storage": str(storage.resolve()),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "url": page.url,
                "reason": reason,
            },
        )
        await page.wait_for_timeout(2000)
        await browser.close()
        return 0


def main() -> None:
    _load_local_env(PLUGIN_ROOT)
    code = asyncio.run(run_manual_login(timeout_sec=1200))
    if code != 0:
        _write_json(
            PLUGIN_ROOT / "videoshorts-memory" / "output" / "instagram-login-log.json",
            {
                "ok": False,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "mode": "manual_login_save",
                "error": "login_not_confirmed",
            },
        )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
