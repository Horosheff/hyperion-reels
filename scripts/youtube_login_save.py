#!/usr/bin/env python3
"""Ручной вход в YouTube Studio через Playwright → cookies.

Как instagram/rutube_login_save: браузер открывается, вы логинитесь сами
(Google / 2FA), скрипт ждёт Studio и сохраняет storage_state в secrets/.
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
    PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "youtube_storage_state.json"
)
STUDIO_URL = "https://studio.youtube.com/"
UPLOAD_URL = "https://www.youtube.com/upload"
# Сильные cookies Google/YouTube после реального входа
SESSION_COOKIE_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "LOGIN_INFO",
    "__Secure-1PSID",
    "__Secure-3PSID",
}
AUTH_URL_MARKERS = (
    "accounts.google.com",
    "ServiceLogin",
    "/signin/",
    "identifier",
    "challenge",
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
        os.getenv("VIDEOSHORTS_YOUTUBE_STORAGE")
        or os.getenv("YOUTUBE_STORAGE_STATE")
        or str(DEFAULT_STORAGE)
    )
    path = Path(raw)
    if not path.is_absolute():
        path = PLUGIN_ROOT / path
    return path


def _is_auth_url(url: str) -> bool:
    u = (url or "").lower()
    return any(m.lower() in u for m in AUTH_URL_MARKERS)


async def _cookie_names(context) -> set[str]:
    try:
        cookies = await context.cookies()
    except Exception:
        return set()
    return {str(c.get("name")) for c in cookies if isinstance(c, dict) and c.get("name")}


async def _page_looks_logged_in(page) -> tuple[bool, str]:
    url = page.url or ""
    if _is_auth_url(url):
        return False, f"still_on_google_auth url={url[:120]}"

    names = await _cookie_names(page.context)
    strong = names & SESSION_COOKIE_NAMES
    if len(strong) < 2:
        return False, f"weak_cookies have={sorted(names)[:14]} url={url[:90]}"

    u = url.lower()
    on_studio = "studio.youtube.com" in u
    on_youtube = "youtube.com" in u and "accounts.google" not in u
    if not (on_studio or on_youtube):
        return False, f"not_on_youtube strong={sorted(strong)} url={url[:90]}"

    # Студия: типичные кнопки / навигация после входа
    try:
        markers = page.locator(
            "#create-icon, #avatar-btn, ytcp-button#create-icon, "
            "tp-yt-paper-icon-button#avatar-btn, "
            'a[href*="/channel/"], button:has-text("Create"), '
            'button:has-text("Создать"), ytcp-animatable#content'
        )
        if await markers.count() > 0:
            return True, f"ok studio_ui cookies={sorted(strong)} url={url[:100]}"
    except Exception:
        pass

    if on_studio and len(strong) >= 3:
        return True, f"ok studio_url cookies={sorted(strong)} url={url[:100]}"

    # Главная YouTube с аватаром
    try:
        avatar = page.locator("#avatar-btn, button#avatar-btn, img.yt-spec-avatar-shape__image")
        if await avatar.count() > 0 and len(strong) >= 2:
            return True, f"ok youtube_home cookies={sorted(strong)} url={url[:100]}"
    except Exception:
        pass

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

    _load_local_env(PLUGIN_ROOT)
    storage = resolve_storage()
    if storage.is_file():
        bak = storage.with_suffix(
            storage.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        storage.replace(bak)
        print(f"Старые cookies → {bak.name}")

    print("=" * 56)
    print("ВХОД В YOUTUBE STUDIO")
    print(f"Открываю: {STUDIO_URL}")
    print("1) Войдите в Google-аккаунт канала YouTube")
    print("2) Пройдите 2FA / проверку при необходимости")
    print("3) Дождитесь YouTube Studio (studio.youtube.com)")
    print("4) Cookies сохранятся сами в secrets/ (не в git)")
    print(f"Жду до {timeout_sec // 60} минут")
    print(f"Файл: {storage}")
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
            viewport=None,
            locale=os.getenv("YOUTUBE_LOCALE", "ru-RU"),
            timezone_id=os.getenv("YOUTUBE_TZ", "Europe/Moscow"),
        )
        page = await context.new_page()
        await page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(2000)
        print("Браузер открыт — логиньтесь в Google / YouTube…", flush=True)

        ok = False
        reason = ""
        stable_hits = 0
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            try:
                if page.is_closed():
                    print("[ERROR] Браузер закрыт — cookies не сохранены.", file=sys.stderr)
                    return 1
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

        # Мягкая проверка Studio / Upload
        try:
            await page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        storage.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(storage))
        print(f"[OK] Cookies сохранены: {storage}")
        print(f"   size={storage.stat().st_size}")
        _write_json(
            PLUGIN_ROOT / "videoshorts-memory" / "output" / "youtube-login-log.json",
            {
                "ok": True,
                "mode": "manual_login_save",
                "storage": str(storage.resolve()),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "url": page.url,
                "reason": reason,
            },
        )
        await browser.close()
        return 0


def main() -> None:
    _load_local_env(PLUGIN_ROOT)
    timeout = int(os.getenv("YOUTUBE_LOGIN_TIMEOUT_SEC", "1200"))
    raise SystemExit(asyncio.run(run_manual_login(timeout_sec=timeout)))


if __name__ == "__main__":
    main()
