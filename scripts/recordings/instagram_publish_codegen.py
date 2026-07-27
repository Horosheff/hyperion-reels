import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(locale="ru-RU", storage_state="cookies/storage_state.json", timezone_id="Europe/Moscow", viewport={"width":1440,"height":1000})
    page = await context.new_page()
    await page.goto("https://www.instagram.com/")
    await page.get_by_role("button", name="Включить").click()
    await page.get_by_role("link", name="Новая публикация Создать").click()
    await page.get_by_role("button", name="Выбрать на компьютере").click()
    await page.locator("input[type=\"file\"]").set_input_files("2026-05-28 20-49-10-vertical.mp4")
    await page.get_by_role("button", name="OK").click()
    await page.locator("button").filter(has_text="Выбрать размер и обрезать").click()
    await page.get_by_role("button", name="9:16").click()
    await page.get_by_role("button", name="Далее").click()
    await page.get_by_role("button", name="Выбрать на компьютере").click()
    await page.locator("input[type=\"file\"]").set_input_files("scale_1200.jpg")
    await page.get_by_role("button", name="Далее").click()
    await page.get_by_role("textbox", name="Добавьте подпись…").click()
    await page.get_by_role("textbox", name="Добавьте подпись…").fill("текст")
    await page.locator(".html-div.xdj266r.x14z9mp.xat24cr.xexx8yu.xyri2b.x18d9i69.x1c1uobl.x9f619.xjbqb8w.x78zum5.x15mokao.x1ga7v0g.x16uus16.xbiv7yw.x13fj5qh > .x1lliihq > path").first.click()
    await page.get_by_role("textbox", name="Добавить место").fill("Москва")
    await page.goto("https://www.instagram.com/artur_horoshev/")

    # ---------------------
    await context.storage_state(path="cookies/storage_state.json")
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
