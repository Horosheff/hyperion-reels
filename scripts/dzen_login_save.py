#!/usr/bin/env python3
"""Ручной вход в Дзен: открыть браузер → вы логинитесь → сохраняем cookies.

Не использует автологин из .env — только ручной вход + storage_state.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish_dzen import _load_local_env, _write_json, resolve_config  # noqa: E402


async def run_manual_login(*, timeout_sec: int = 600) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[ERROR] Нужен playwright: pip install playwright && playwright install chromium", file=sys.stderr)
        return 2

    cfg = resolve_config(PLUGIN_ROOT)
    storage = Path(cfg["storage"])
    channel = cfg.get("channel") or "artur_horosheff"
    studio_url = f"https://dzen.ru/profile/editor/{channel}/publications"

    # Свежий контекст без старых cookies — чтобы точно войти в нужный аккаунт
    backup = None
    if storage.is_file():
        backup = storage.with_suffix(storage.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        storage.replace(backup)
        print(f"Старые cookies → {backup.name}")

    print("=" * 50)
    print("РУЧНОЙ ВХОД В ДЗЕН")
    print(f"Канал: {channel}")
    print(f"URL:   {studio_url}")
    print("1) В открывшемся окне войдите в Яндекс / Дзен")
    print("2) Дождитесь студии канала (publications)")
    print("3) Cookies сохранятся сами")
    print(f"Ожидание до {timeout_sec // 60} мин…")
    print("=" * 50)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        context = await browser.new_context(viewport=None)
        page = await context.new_page()
        await page.goto(studio_url, wait_until="domcontentloaded", timeout=120000)

        ok = False
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            url = page.url or ""
            # Строго: студия редактора / publications, не лента и не passport
            on_studio = (
                "dzen.ru" in url
                and "passport" not in url
                and (
                    f"/editor/{channel}" in url
                    or f"/profile/editor/{channel}" in url
                    or (channel in url and "/publications" in url)
                )
            )
            if on_studio:
                await page.wait_for_timeout(2500)
                url = page.url or ""
                if "passport" not in url and channel in url:
                    ok = True
                    break
            await page.wait_for_timeout(3000)
            left = int(deadline - asyncio.get_event_loop().time())
            print(f"…ждём вход ({left}с)  url={url[:100]}", flush=True)

        if not ok:
            print("[ERROR] Таймаут: вход не обнаружен. Cookies не сохранены.", file=sys.stderr)
            if backup and backup.is_file() and not storage.is_file():
                backup.replace(storage)
                print("Восстановил старые cookies")
            await browser.close()
            return 1

        storage.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(storage))
        print(f"✅ Cookies сохранены: {storage}")
        print(f"   size={storage.stat().st_size} channel={channel}")

        log_path = PLUGIN_ROOT / "videoshorts-memory" / "output" / "dzen-login-log.json"
        _write_json(
            log_path,
            {
                "ok": True,
                "mode": "manual_login_save",
                "channel": channel,
                "storage": str(storage.resolve()),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "url": page.url,
            },
        )

        await page.wait_for_timeout(1500)
        await browser.close()
        return 0


def main() -> None:
    local = _load_local_env(PLUGIN_ROOT)
    # Не подставляем пароль — только ручной вход
    os.environ["HEADLESS"] = "false"
    if local.get("DZEN_CHANNEL_NAME"):
        os.environ["DZEN_CHANNEL_NAME"] = local["DZEN_CHANNEL_NAME"]
    if local.get("STORAGE_STATE") or local.get("VIDEOSHORTS_DZEN_STORAGE"):
        os.environ["STORAGE_STATE"] = local.get("STORAGE_STATE") or local["VIDEOSHORTS_DZEN_STORAGE"]
    raise SystemExit(asyncio.run(run_manual_login(timeout_sec=600)))


if __name__ == "__main__":
    main()
