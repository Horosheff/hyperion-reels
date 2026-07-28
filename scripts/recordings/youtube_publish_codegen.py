import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(locale="ru-RU", storage_state="C:\\Users\\mrrut\\.cursor\\plugins\\local\\hyperion\\videoshorts-memory\\secrets\\youtube_storage_state.json", timezone_id="Europe/Moscow", viewport={"width":1440,"height":1000})
    page = await context.new_page()
    await page.goto("https://studio.youtube.com/channel/UCQ2_R6IaR6FvJpvqLaNqu6w")
    await page.get_by_role("button", name="Создать", exact=True).click()
    await page.get_by_text("Добавить видео").click()
    await page.get_by_role("button", name="Выбрать файлы").click()
    await page.get_by_role("button", name="Выбрать файлы").set_input_files("2026-05-28 20-49-10-vertical.mp4")
    await page.get_by_role("textbox", name="Укажите название. Если вы хотите упомянуть другого автора, введите символ \"@\", а").click()
    await page.get_by_role("textbox", name="Укажите название. Если вы хотите упомянуть другого автора, введите символ \"@\", а").dblclick()
    await page.get_by_role("textbox", name="Укажите название. Если вы хотите упомянуть другого автора, введите символ \"@\", а").click()
    await page.get_by_role("textbox", name="Укажите название. Если вы хотите упомянуть другого автора, введите символ \"@\", а").click()
    await page.get_by_role("textbox", name="Укажите название. Если вы хотите упомянуть другого автора, введите символ \"@\", а").fill("название")
    await page.get_by_text("Рекомендуемые хештеги Эти рекомендации созданы автоматически на основе контента,").click()
    await page.get_by_role("button", name="Иллюстрация к персонализированному предложению #aiагенты").click()
    await page.get_by_role("button", name="#automobile").click()
    await page.get_by_role("button", name="Иллюстрация к персонализированному предложению #cursorai").click()
    await page.get_by_role("button", name="#coding").click()
    await page.get_by_role("textbox", name="Расскажите, о чем ваше видео. Если вы хотите упомянуть другого автора, введите с").click()
    await page.get_by_role("textbox", name="Расскажите, о чем ваше видео. Если вы хотите упомянуть другого автора, введите с").fill("описание")
    await page.get_by_role("button", name="Загрузить файл").click()
    await page.get_by_role("button", name="Загрузить файл").set_input_files("scale_1200.jpg")
    await page.get_by_role("button", name="Выберите плейлист").click()
    await page.locator("#checkbox-0 #checkbox-container").click()
    await page.get_by_role("button", name="ОК", exact=True).click()
    await page.get_by_role("button", name="Показать дополнительные настройки").click()
    await page.get_by_role("radio", name="Нет, ИИ не использовался").click()
    await page.get_by_role("textbox", name="Теги").click()
    await page.get_by_role("textbox", name="Теги").fill("теги")
    await page.get_by_role("textbox", name="Теги").press("Shift+Enter")
    await page.get_by_role("textbox", name="Теги").fill("много тегов")
    await page.get_by_role("textbox", name="Теги").press("Shift+Enter")
    await page.get_by_role("button", name="Музыка").nth(1).click()
    await page.locator("div").filter(has_text="Наука и техника").nth(2).click()
    await page.get_by_role("button", name="Наука и техника").nth(1).click()
    await page.locator("tp-yt-iron-overlay-backdrop").nth(2).click()
    await page.get_by_role("button", name="Далее").click()
    # НЕ ставить галочку paid promotion / прямой рекламы
    await page.get_by_role("button", name="Далее").click()
    await page.get_by_role("button", name="Поставить оценку").click()
    await page.get_by_role("button", name="Далее").click()
    await page.get_by_role("button", name="Далее").click()
    await page.get_by_role("button", name="Далее").click()
    await page.get_by_role("radio", name="Открытый доступ").click()
    await page.get_by_role("button", name="Опубликовать").click()
    await page.locator("#close-button").get_by_role("button", name="Закрыть").click()
    await page.get_by_role("menuitem", name="Контент", exact=True).click()
    await page.get_by_text("Shorts", exact=True).click()

    # ---------------------
    await context.storage_state(path="C:\\Users\\mrrut\\.cursor\\plugins\\local\\hyperion\\videoshorts-memory\\secrets\\youtube_storage_state.json")
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
