#!/usr/bin/env python3
"""Ручной вход в VK Видео.

Браузер НЕ закрывается, пока вы не закончите вход и не окажетесь
на vkvideo.ru (не на id.vk.ru/auth). Слабые cookies вроде remixstlid
не считаются сессией.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish_vk import resolve_config, _write_json  # noqa: E402

# Реальная сессия VK — не tracking-cookie remixstlid
SESSION_COOKIE_NAMES = {"remixsid", "remixnsid", "remixsid_encrypted"}
AUTH_HOST_MARKERS = (
    "id.vk.com",
    "id.vk.ru",
    "login.vk.com",
    "login.vk.ru",
    "oauth.vk.com",
    "oauth.vk.ru",
    "/auth",
)


def _is_auth_url(url: str) -> bool:
    u = (url or "").lower()
    if any(h in u for h in ("id.vk.com", "id.vk.ru", "login.vk.", "oauth.vk.")):
        return True
    return False


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
    if not strong:
        return False, f"no_session_cookie have={sorted(names)[:12]} url={url[:90]}"

    # Гостевые CTA
    for sel in (
        'button:has-text("Войти")',
        'a:has-text("Войти")',
        "text=Войдите в аккаунт",
        "text=Больше возможностейпосле входа",
        "text=Больше возможностей после входа",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return False, f"login_cta_visible cookies={sorted(strong)} url={url[:80]}"
        except Exception:
            continue

    on_vkvideo = "vkvideo.ru" in url.lower()
    file_inputs = 0
    try:
        file_inputs = await page.locator('input[type="file"]').count()
    except Exception:
        pass

    if on_vkvideo and ("/upload" in url.lower() or file_inputs > 0):
        return True, f"ok upload session={sorted(strong)} files={file_inputs}"
    if on_vkvideo and strong:
        # канал / главная после редиректа — тоже ок, потом уйдём на upload
        return True, f"ok vkvideo session={sorted(strong)}"

    return False, f"waiting strong={sorted(strong)} url={url[:100]}"


async def run_manual_login(*, timeout_sec: int = 1200) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "[ERROR] Нужен playwright: pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 2

    cfg = resolve_config(PLUGIN_ROOT)
    storage = Path(cfg["storage"])
    channel = cfg.get("channel") or "kov4eg_ai"
    upload_url = "https://vkvideo.ru/upload"

    if storage.is_file():
        backup = storage.with_suffix(
            storage.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        storage.replace(backup)
        print(f"Старые cookies → {backup.name}")

    print("=" * 56)
    print("ВХОД В VK ВИДЕО — НЕ ТОРОПИТЕСЬ")
    print(f"Канал: @{channel}")
    print("1) Войдите в аккаунт в открывшемся окне")
    print("2) Дождитесь возврата на vkvideo.ru (не id.vk.ru)")
    print("3) Лучше откройте /upload — окно закроется само")
    print(f"Жду до {timeout_sec // 60} минут. Можно не спешить.")
    print("=" * 56)

    async with async_playwright() as p:
        try:
            from playwright_display import chromium_window_args, describe_placement

            launch_args = [
                "--disable-blink-features=AutomationControlled",
                *chromium_window_args(maximize=True),
            ]
            print(f"Display: {describe_placement()}")
        except Exception as exc:
            print(f"[WARN] playwright_display: {exc}")
            launch_args = ["--disable-blink-features=AutomationControlled", "--start-maximized"]
        browser = await p.chromium.launch(
            headless=False,
            args=launch_args,
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        page = await context.new_page()
        await page.goto(upload_url, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(2000)

        for sel in ('button:has-text("Войти")', 'a:has-text("Войти")'):
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=4000)
                    print("Открыл форму входа — логиньтесь спокойно…", flush=True)
                    break
            except Exception:
                continue

        ok = False
        reason = ""
        stable_hits = 0
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            try:
                if page.is_closed():
                    print("[ERROR] Окно браузера закрыто — cookies не сохранены.", file=sys.stderr)
                    return 1
                # Никогда не принимать id.vk.ru как успех
                if _is_auth_url(page.url or ""):
                    stable_hits = 0
                    left = int(deadline - asyncio.get_event_loop().time())
                    print(f"…идёт авторизация ({left}с)  url={(page.url or '')[:110]}", flush=True)
                    await page.wait_for_timeout(3000)
                    continue

                ok, reason = await _page_looks_logged_in(page)
                left = int(deadline - asyncio.get_event_loop().time())
                print(f"…проверка ({left}с)  {reason}", flush=True)
                if ok:
                    stable_hits += 1
                    # 3 подряд успешные проверки ≈ 9 сек на странице после входа
                    if stable_hits >= 3:
                        break
                else:
                    stable_hits = 0
                await page.wait_for_timeout(3000)
            except Exception as loop_exc:
                name = type(loop_exc).__name__
                if "TargetClosed" in name or "closed" in str(loop_exc).lower():
                    print("[ERROR] Браузер закрыт во время входа — cookies не сохранены.", file=sys.stderr)
                    return 1
                print(f"[WARN] login loop: {loop_exc}", flush=True)
                await asyncio.sleep(2)

        if not ok or stable_hits < 3:
            print("[ERROR] Вход не подтверждён вовремя. Cookies не сохранены.", file=sys.stderr)
            print(f"   last={reason}", file=sys.stderr)
            try:
                shot = (
                    PLUGIN_ROOT
                    / "videoshorts-memory"
                    / "output"
                    / "vk-screenshots"
                    / f"login_timeout_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                )
                shot.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(shot), full_page=True)
                print(f"   screenshot={shot}", file=sys.stderr)
            except Exception:
                pass
            await browser.close()
            return 1

        # На всякий случай дойдём до upload
        if "upload" not in (page.url or "").lower():
            try:
                await page.goto(upload_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(2000)
            except Exception:
                pass

        if _is_auth_url(page.url or ""):
            print("[ERROR] После входа снова auth-страница — cookies не сохраняю.", file=sys.stderr)
            await browser.close()
            return 1

        storage.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(storage))
        print(f"✅ Cookies сохранены: {storage}")
        print(f"   size={storage.stat().st_size}")
        print(f"   url={page.url}")
        print(f"   reason={reason}")
        _write_json(
            PLUGIN_ROOT / "videoshorts-memory" / "output" / "vk-login-log.json",
            {
                "ok": True,
                "mode": "manual_login_save",
                "channel": channel,
                "storage": str(storage.resolve()),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "url": page.url,
                "reason": reason,
            },
        )
        await page.wait_for_timeout(2500)
        await browser.close()
        return 0


def main() -> None:
    code = asyncio.run(run_manual_login(timeout_sec=1200))
    if code != 0:
        _write_json(
            PLUGIN_ROOT / "videoshorts-memory" / "output" / "vk-login-log.json",
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
