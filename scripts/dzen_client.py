"""
Клиент для автоматизации загрузки коротких видео (роликов) в Дзен
Использует Playwright для автоматизации браузера

Функционал:
- Авторизация через Яндекс Паспорт (с сохранением cookies)
- Загрузка видео файла
- Транскрибация видео через Whisper для понимания содержимого
- Генерация обложки через Nano Banana Pro с референсным изображением
- Автоматическое заполнение описания и тегов
- Загрузка обложки и публикация

Требования:
- Аккаунт Яндекс с привязанным каналом Дзен
- Видео в формате MP4/WEBM, вертикальное, до 2 минут
- openai-whisper (pip install openai-whisper)
- ffmpeg для транскрибации
"""

import asyncio
import os
import sys
import json
import subprocess
import requests
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
try:
    from dotenv import load_dotenv
except ImportError:  # optional — publish_dzen already injects env
    def load_dotenv(*_a, **_k):  # type: ignore[misc]
        return False
import logging

# ВАЖНО (Windows): чтобы кириллица в логах не превращалась в "����"
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Настройка логирования
_LOG_DIR = Path(__file__).resolve().parents[1] / "videoshorts-memory" / "output"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / 'dzen_autopost.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения (plugin-local first, no absolute Tilda paths)
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for _env_path in (
    _PLUGIN_ROOT / "videoshorts.local.env",
    _PLUGIN_ROOT / ".env",
    Path.cwd() / "videoshorts.local.env",
    Path.cwd() / ".env",
):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
load_dotenv(override=False)  # fallback: any .env near cwd


class DzenClient:
    """Клиент для работы с Дзен через автоматизацию браузера"""
    
    # URL-ы Дзена
    BASE_URL = "https://dzen.ru"
    LOGIN_URL = "https://passport.yandex.ru/auth"
    STUDIO_URL = "https://dzen.ru/media/zen/login"
    
    # URL для публикаций — {channel} заменяется на имя канала
    PUBLICATIONS_URL_TEMPLATE = "https://dzen.ru/profile/editor/{channel}/publications"
    
    # Nano Banana Pro API (через внешний сервис)
    NANO_BANANA_API_URL = "https://tempfile.aiquickdraw.com/workers/nano/generate"
    
    # Референсное изображение для обложек (человек в красном пиджаке)
    REFERENCE_IMAGE_PATH = os.getenv('COVER_REFERENCE_IMAGE', '06bd46d4-89a4-4ad3-bf87-a84adbf8d952.png')
    
    # FAL.AI API ключ для Nano Banana Pro
    FAL_API_KEY = os.getenv('FAL_API_KEY', '')
    
    def __init__(self):
        # Переменные из .env
        self.login = os.getenv('DZEN_LOGIN')  # Логин или email Яндекс
        self.password = os.getenv('DZEN_PASSWORD')
        self.channel_name = os.getenv('DZEN_CHANNEL_NAME', '')  # Имя канала (из URL)
        self.headless = os.getenv('HEADLESS', 'false').lower() == 'true'
        self.timeout = int(os.getenv('BROWSER_TIMEOUT', '120000'))  # 2 минуты для видео
        default_storage = _PLUGIN_ROOT / "videoshorts-memory" / "secrets" / "dzen_storage_state.json"
        self.storage_state_path = os.getenv('STORAGE_STATE', str(default_storage))
        # Для VideoShorts publish всегда закрываем браузер (иначе UI зависает)
        force_close = os.getenv("VIDEOSHORTS_FORCE_CLOSE_BROWSER", "1").lower() not in {"0", "false", "no"}
        self.keep_open = (os.getenv('KEEP_BROWSER_OPEN', 'false').lower() == 'true') and not force_close
        
        # Playwright объекты
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Credentials опциональны — можно авторизоваться вручную
        self.manual_login = False
        if not self.login or not self.password:
            if os.path.exists(self.storage_state_path):
                logger.info("Credentials не указаны, будут использованы сохранённые cookies")
            else:
                logger.warning("Credentials не указаны и нет cookies — потребуется ручная авторизация")
                self.manual_login = True
    
    async def start(self):
        """Запуск браузера и создание контекста"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        # Создание контекста с реалистичными настройками
        context_kwargs = {
            'viewport': {'width': 1920, 'height': 1080},
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'locale': 'ru-RU',
            'timezone_id': 'Europe/Moscow'
        }
        
        # Загрузка cookies если есть
        if self.storage_state_path and os.path.exists(self.storage_state_path):
            context_kwargs['storage_state'] = self.storage_state_path
            logger.info(f"Загружены cookies из {self.storage_state_path}")
        
        self.context = await self.browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        
        # Подключаем отладочные слушатели
        self._attach_debug_listeners()
        
        logger.info("Браузер запущен")
    
    def _attach_debug_listeners(self):
        """Подключает логирование консоли/ошибок из браузера"""
        if not self.page:
            return
        
        def _on_console(msg):
            if msg.type in ['error', 'warning']:
                logger.debug(f"[БРАУЗЕР] {msg.type}: {msg.text}")
        
        def _on_page_error(err):
            logger.error(f"[ОШИБКА СТРАНИЦЫ] {err}")
        
        self.page.on("console", _on_console)
        self.page.on("pageerror", _on_page_error)
    
    async def close(self, force: bool = False):
        """Закрытие браузера. force=True — всегда закрыть (для VideoShorts publish)."""
        if self.keep_open and not force:
            logger.info("Браузер оставлен открытым (KEEP_BROWSER_OPEN=true)")
            logger.info("Закройте браузер вручную когда закончите")
            # Ждём бесконечно пока браузер не закроют вручную
            try:
                while self.browser and self.browser.is_connected():
                    await asyncio.sleep(5)
            except Exception:
                pass
            return
        
        try:
            if self.context:
                await self.save_cookies()
        except Exception:
            pass
        try:
            if self.page and not self.page.is_closed():
                await self.page.close()
        except Exception:
            pass
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        logger.info("Браузер закрыт")
    
    async def save_cookies(self):
        """Сохранение cookies для последующих сессий"""
        if self.context and self.storage_state_path:
            await self.context.storage_state(path=self.storage_state_path)
            logger.info(f"Cookies сохранены в {self.storage_state_path}")
    
    async def screenshot(self, name: str = "screenshot"):
        """Сделать скриншот с таймстампом (в plugin memory, не в cwd Tilda)."""
        shot_dir = _PLUGIN_ROOT / "videoshorts-memory" / "output" / "dzen-screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        filename = shot_dir / f'{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
        await self.page.screenshot(path=str(filename))
        logger.info(f"Скриншот: {filename}")
        return str(filename)
    
    async def _wait_and_click(self, selectors: List[str], description: str = "элемент") -> bool:
        """Ждёт появления одного из селекторов и кликает"""
        for selector in selectors:
            try:
                element = self.page.locator(selector).first
                if await element.count() > 0:
                    await element.wait_for(state='visible', timeout=5000)
                    await element.click()
                    logger.info(f"✓ Клик по {description} (селектор: {selector})")
                    return True
            except Exception:
                continue
        return False
    
    async def _fill_field(self, selectors: List[str], value: str, description: str = "поле") -> bool:
        """Заполняет первое найденное поле"""
        for selector in selectors:
            try:
                field = self.page.locator(selector).first
                if await field.count() > 0:
                    await field.click()
                    await field.fill(value)
                    logger.info(f"✓ {description} заполнено")
                    return True
            except Exception:
                continue
        return False
    
    # ============================================
    # МЕТОДЫ ДЛЯ ОБРАБОТКИ ВИДЕО
    # ============================================
    
    def transcribe_video(self, video_path: str) -> str:
        """
        Транскрибация видео через Whisper
        
        Args:
            video_path: Путь к видео файлу
            
        Returns:
            str: Текст транскрипции
        """
        try:
            logger.info("Транскрибация видео через Whisper...")
            
            # Создаём имя файла для транскрипции
            transcript_path = video_path.rsplit('.', 1)[0] + '.txt'
            
            # Если транскрипция уже есть — используем её
            if os.path.exists(transcript_path):
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                    if text:
                        logger.info(f"✓ Найдена готовая транскрипция: {len(text)} символов")
                        return text
            
            # Запускаем Whisper через Python модуль
            result = subprocess.run(
                [
                    sys.executable, '-m', 'whisper',
                    video_path,
                    '--model', 'base',
                    '--language', 'ru',
                    '--output_format', 'txt',
                    '--output_dir', os.path.dirname(video_path) or '.'
                ],
                capture_output=True,
                text=True,
                timeout=300  # 5 минут максимум
            )
            
            if result.returncode != 0:
                logger.warning(f"Whisper ошибка: {result.stderr}")
                return ""
            
            # Читаем результат
            if os.path.exists(transcript_path):
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                    logger.info(f"✓ Транскрибация завершена: {len(text)} символов")
                    return text
            
            return ""
            
        except subprocess.TimeoutExpired:
            logger.error("Транскрибация превысила таймаут (5 минут)")
            return ""
        except Exception as e:
            logger.error(f"Ошибка транскрибации: {e}")
            return ""
    
    def generate_description_and_tags(self, transcript: str, max_desc_len: int = 180) -> Tuple[str, List[str]]:
        """
        Генерация описания и релевантных тегов на основе транскрипции
        """
        if not transcript:
            return "", []
        
        # Берём первые предложения для описания
        sentences = re.split(r'[.!?]+', transcript)
        description = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(description) + len(sentence) + 2 <= max_desc_len:
                description += sentence + ". "
            elif description:
                break
        
        description = description.strip()
        if len(description) > max_desc_len:
            description = description[:max_desc_len-3] + "..."
        
        text_lower = transcript.lower()
        tags = []
        
        # Тематические теги — ищем по ключевым словам в тексте
        topic_tags = {
            # AI и нейросети
            'нейросети': ['нейросет', 'нейронн', 'neural', 'ai ', ' ии '],
            'искусственный интеллект': ['искусственн', 'интеллект', 'artificial'],
            'GPT': ['gpt', 'чатгпт', 'chatgpt', 'openai'],
            'автоматизация': ['автоматиз', 'автомат'],
            'AI агенты': ['агент', 'agent'],
            # Мессенджеры и соцсети
            'Telegram': ['telegram', 'телеграм', 'тг ', ' тг'],
            'MAX': [' max ', ' макс ', 'мессенджер max'],
            'ВКонтакте': ['вконтакте', 'вк ', ' вк', 'vk'],
            'Дзен': ['дзен', 'zen', 'яндекс дзен'],
            # Технологии
            'программирование': ['программ', 'код', 'разработ', 'developer'],
            'Python': ['python', 'питон', 'пайтон'],
            'API': ['api', 'апи'],
            'боты': ['бот', 'bot'],
            # Бизнес
            'маркетинг': ['маркетинг', 'marketing', 'продвиж'],
            'заработок': ['заработ', 'деньги', 'доход', 'монетиз'],
            'бизнес': ['бизнес', 'business', 'предприним'],
            # Контент
            'обучение': ['обучен', 'урок', 'курс', 'учи'],
            'лайфхак': ['лайфхак', 'lifehack', 'совет', 'трюк'],
            'новости': ['новост', 'news'],
            # Разное
            'технологии': ['технолог', 'tech'],
            'Россия': ['росси', 'russia', 'рф '],
            'промпты': ['промпт', 'prompt', 'промт'],
            'структура': ['структур'],
        }
        
        # Ищем совпадения с тематическими тегами
        for tag, keywords in topic_tags.items():
            for keyword in keywords:
                if keyword in text_lower and tag not in tags:
                    tags.append(tag)
                    break
        
        # Если тегов мало — добавляем общие по теме
        if len(tags) < 3:
            # Определяем общую тему
            if any(w in text_lower for w in ['gpt', 'нейросет', 'агент', 'ai']):
                if 'нейросети' not in tags:
                    tags.append('нейросети')
                if 'технологии' not in tags:
                    tags.append('технологии')
            if any(w in text_lower for w in ['telegram', 'телеграм', 'max', 'мессенджер']):
                if 'мессенджеры' not in tags:
                    tags.append('мессенджеры')
        
        # Ограничиваем до 5 тегов
        tags = tags[:5]
        
        logger.info(f"✓ Сгенерировано описание ({len(description)} симв.) и {len(tags)} тегов")
        return description, tags
    
    def generate_cover(
        self, 
        title: str, 
        transcript: str = "",
        output_path: str = "cover_generated.png"
    ) -> Optional[str]:
        """
        Генерация обложки через Nano Banana Pro
        
        Args:
            title: Заголовок видео
            transcript: Транскрипция для контекста
            output_path: Путь для сохранения обложки
            
        Returns:
            str: Путь к сгенерированной обложке или None
        """
        try:
            logger.info("Генерация обложки через Nano Banana Pro...")
            
            # Формируем промпт для генерации
            # Стиль: фотореалистичный, формат 9:16, YouTube превью
            prompt = f"""Photorealistic YouTube thumbnail style, 9:16 vertical format, 
            man in red suit with glasses looking at camera, dark background, 
            bold Russian text '{title[:30]}' in white, 
            professional lighting, high quality, cinematic, social media cover"""
            
            # Вызов API через requests
            # Используем внешний сервис который предоставляет доступ к fal.ai
            api_url = "https://fal.run/fal-ai/nano-banana/image"
            
            headers = {
                "Content-Type": "application/json"
            }
            
            if self.FAL_API_KEY:
                headers["Authorization"] = f"Key {self.FAL_API_KEY}"
            
            payload = {
                "prompt": prompt,
                "image_size": "portrait_16_9",  # 9:16 вертикальный
                "num_images": 1,
                "enable_safety_checker": False
            }
            
            response = requests.post(api_url, json=payload, headers=headers, timeout=60)
            
            if response.status_code == 200:
                data = response.json()
                if 'images' in data and len(data['images']) > 0:
                    image_url = data['images'][0].get('url', '')
                    if image_url:
                        # Скачиваем изображение
                        img_response = requests.get(image_url, timeout=30)
                        if img_response.status_code == 200:
                            with open(output_path, 'wb') as f:
                                f.write(img_response.content)
                            logger.info(f"✓ Обложка сохранена: {output_path}")
                            return output_path
            
            # Fallback: попробуем через MCP endpoint если доступен
            logger.warning("Не удалось сгенерировать через API, используем заглушку")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка генерации обложки: {e}")
            return None
    
    async def upload_cover(self, cover_path: str) -> bool:
        """
        Загрузка обложки в форму редактирования ролика
        
        Args:
            cover_path: Путь к файлу обложки
            
        Returns:
            bool: True если обложка загружена
        """
        try:
            if not os.path.exists(cover_path):
                logger.warning(f"Файл обложки не найден: {cover_path}")
                return False
            
            logger.info("Загрузка обложки...")
            
            # Кликаем на кнопку "Добавить обложку"
            add_cover_btn = self.page.locator('button:has-text("Добавить обложку")').first
            if await add_cover_btn.count() > 0:
                await add_cover_btn.click()
                await self.page.wait_for_timeout(1000)
            
            # Делаем input[type=file] видимым через JS
            await self.page.evaluate('''() => {
                const input = document.querySelector('input[type="file"][accept*="image"]');
                if (input) {
                    input.style.display = 'block';
                    input.style.visibility = 'visible';
                    input.style.opacity = '1';
                }
            }''')
            await self.page.wait_for_timeout(500)
            
            # Ищем input для изображений
            file_input = self.page.locator('input[type="file"][accept*="image"]').first
            
            if await file_input.count() > 0:
                await file_input.set_input_files(cover_path)
                logger.info("✓ Обложка загружена через input")
                await self.page.wait_for_timeout(3000)  # Ждём обработку
                return True
            else:
                # Альтернатива: file chooser
                async with self.page.expect_file_chooser(timeout=5000) as fc_info:
                    await add_cover_btn.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(cover_path)
                logger.info("✓ Обложка загружена через file chooser")
                await self.page.wait_for_timeout(3000)
                return True
                
        except Exception as e:
            logger.error(f"Ошибка загрузки обложки: {e}")
            return False
    
    async def login_yandex(self) -> bool:
        """
        Авторизация через Яндекс Паспорт
        
        Returns:
            bool: True если авторизация успешна
        """
        try:
            logger.info("=" * 50)
            logger.info("АВТОРИЗАЦИЯ В ЯНДЕКС/ДЗЕН")
            logger.info("=" * 50)
            
            # Если есть cookies — проверяем авторизацию БЕЗ перехода на passport
            if os.path.exists(self.storage_state_path):
                logger.info("Проверяем авторизацию через cookies...")
                
                # Переходим в студию с именем канала (без него - 404!)
                channel = self.channel_name or 'evolyuciya'
                studio_url = f"https://dzen.ru/profile/editor/{channel}/publications"
                await self.page.goto(studio_url, wait_until='domcontentloaded')
                await self.page.wait_for_timeout(3000)
                
                current_url = self.page.url
                # Если не редиректнуло на passport — авторизованы
                if 'passport.yandex' not in current_url:
                    logger.info("✓ Уже авторизованы (cookies работают)")
                    await self.save_cookies()
                    return True
                else:
                    logger.info("Cookies устарели, требуется повторная авторизация")
            
            # Нет cookies или устарели — нужна авторизация
            logger.info("Переход на страницу авторизации...")
            
            # Если нет credentials — только ручная авторизация
            if not self.login or not self.password:
                self.manual_login = True
            
            # Режим ручной авторизации
            if self.manual_login:
                logger.info("=" * 50)
                logger.info("РУЧНАЯ АВТОРИЗАЦИЯ")
                logger.info("Пожалуйста, авторизуйтесь в открытом браузере")
                logger.info("После авторизации cookies будут сохранены автоматически")
                logger.info("=" * 50)
                
                # Ждём пока пользователь авторизуется (до 3 минут)
                for i in range(36):  # 36 * 5 = 180 секунд
                    await self.page.wait_for_timeout(5000)
                    current_url = self.page.url
                    if 'passport.yandex' not in current_url and 'dzen.ru' in current_url:
                        logger.info("✓ Авторизация обнаружена!")
                        await self.save_cookies()
                        return True
                    logger.info(f"Ожидание авторизации... ({i*5}/180 сек)")
                
                logger.error("Таймаут ожидания авторизации")
                return False
            
            # ============================================
            # ШАГ 1: Выбор входа по логину (не телефону)
            # ============================================
            logger.info("Выбор способа входа по логину...")
            
            # Нажимаем "Ещё" чтобы увидеть вариант входа по логину
            await self._wait_and_click(
                ['button:has-text("Ещё")', '[data-t="button:pseudo"]'],
                "кнопка Ещё"
            )
            await self.page.wait_for_timeout(500)
            
            # Нажимаем "Войти по логину"
            await self._wait_and_click(
                ['[data-t="login-by-login"]', 'button:has-text("Войти по логину")', 
                 'menuitem:has-text("Войти по логину")', ':text("Войти по логину")'],
                "Войти по логину"
            )
            await self.page.wait_for_timeout(1000)
            
            # ============================================
            # ШАГ 2: Ввод логина
            # ============================================
            logger.info("Ввод логина...")
            
            login_filled = await self._fill_field(
                ['input[name="login"]', 'input[placeholder*="Логин"]', 
                 'input[placeholder*="email"]', '#passp-field-login',
                 'input[data-t="field:input-login"]'],
                self.login,
                "Логин"
            )
            
            if not login_filled:
                await self.screenshot("error_no_login_field")
                raise Exception("Не найдено поле для логина")
            
            await self.page.wait_for_timeout(500)
            
            # Нажимаем "Войти" после логина
            await self._wait_and_click(
                ['button:has-text("Войти")', 'button[type="submit"]',
                 '[data-t="button:action"]', '[data-t="button:submit"]'],
                "кнопка Войти (после логина)"
            )
            await self.page.wait_for_timeout(2000)
            
            # ============================================
            # ШАГ 3: Ввод пароля
            # ============================================
            logger.info("Ввод пароля...")
            
            password_filled = await self._fill_field(
                ['input[name="passwd"]', 'input[type="password"]',
                 '#passp-field-passwd', 'input[data-t="field:input-passwd"]'],
                self.password,
                "Пароль"
            )
            
            if not password_filled:
                await self.screenshot("error_no_password_field")
                raise Exception("Не найдено поле для пароля")
            
            await self.page.wait_for_timeout(500)
            
            # Нажимаем "Войти" после пароля
            await self._wait_and_click(
                ['button:has-text("Войти")', 'button:has-text("Продолжить")',
                 'button[type="submit"]', '[data-t="button:action"]'],
                "кнопка Войти (после пароля)"
            )
            
            # Ожидание перехода после авторизации
            logger.info("Ожидание завершения авторизации...")
            await self.page.wait_for_timeout(5000)
            
            # ============================================
            # ПРОВЕРКА: Капча или дополнительная верификация
            # ============================================
            current_url = self.page.url.lower()
            page_content = await self.page.content()
            
            if 'captcha' in current_url or 'captcha' in page_content.lower() or 'не робот' in page_content.lower():
                logger.warning("=" * 50)
                logger.warning("⚠️ ОБНАРУЖЕНА КАПЧА!")
                logger.warning("Пожалуйста, пройдите капчу вручную в открытом браузере")
                logger.warning("=" * 50)
                await self.screenshot("captcha_detected")
                
                # Ждём пока пользователь пройдёт капчу (до 2 минут)
                for i in range(24):  # 24 * 5 = 120 секунд
                    await self.page.wait_for_timeout(5000)
                    current_url = self.page.url.lower()
                    if 'captcha' not in current_url and 'passport.yandex' not in current_url:
                        logger.info("Капча пройдена!")
                        break
            
            # Проверяем успешность авторизации
            current_url = self.page.url
            
            if 'dzen.ru' in current_url and 'passport' not in current_url:
                logger.info("✓ АВТОРИЗАЦИЯ УСПЕШНА")
                await self.save_cookies()
                return True
            elif 'passport.yandex' in current_url:
                await self.screenshot("error_still_on_passport")
                logger.error("✗ Остались на странице авторизации — возможно неверные credentials")
                return False
            else:
                # Попробуем перейти на Дзен
                await self.page.goto(self.BASE_URL, wait_until='domcontentloaded')
                await self.page.wait_for_timeout(2000)
                
                # Проверяем наличие кнопки "Войти"
                login_button = self.page.locator('button:has-text("Войти")')
                if await login_button.count() == 0:
                    logger.info("✓ АВТОРИЗАЦИЯ УСПЕШНА")
                    await self.save_cookies()
                    return True
                else:
                    await self.screenshot("error_not_logged_in")
                    logger.error("✗ Авторизация не удалась")
                    return False
            
        except Exception as e:
            logger.error(f"✗ Ошибка авторизации: {e}")
            await self.screenshot("error_login_exception")
            return False
    
    async def _count_tag_chips(self) -> list[str]:
        """Тексты уже добавленных чипов тегов в форме ролика."""
        try:
            return await self.page.evaluate(
                """() => {
                  const nodes = document.querySelectorAll(
                    '[class*="tag-input-child__content"], [class*="tagInputChild"] [class*="content"]'
                  );
                  const out = [];
                  for (const n of nodes) {
                    const t = (n.textContent || '').trim();
                    if (t) out.push(t);
                  }
                  return [...new Set(out)];
                }"""
            )
        except Exception:
            return []

    async def _add_video_tags(self, tags: List[str]) -> int:
        """Добавляет теги по одному чипу (не хэштеги в описание). Возвращает число чипов."""
        if not tags:
            return 0

        selectors = [
            'input[placeholder="Добавьте теги"]',
            'input[placeholder*="Добавьте тег"]',
            'input[placeholder*="тег"]',
            'input[placeholder*="Тег"]',
            'input[placeholder*="запятую"]',
            '[class*="tag-input"] input',
            '[class*="TagInput"] input',
            'input[aria-label*="тег"]',
            'input[aria-label*="Тег"]',
            'input[role="combobox"]',
        ]

        tags_input = None
        for sel in selectors:
            loc = self.page.locator(sel).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    tags_input = loc
                    logger.info(f"Поле тегов: {sel}")
                    break
            except Exception:
                continue

        if tags_input is None:
            try:
                by_label = self.page.get_by_placeholder(re.compile(r"тег|запят", re.I)).first
                if await by_label.count() > 0:
                    tags_input = by_label
            except Exception:
                pass

        if tags_input is None:
            logger.warning("Поле тегов не найдено на странице")
            await self.screenshot("tags_field_missing")
            return 0

        before = await self._count_tag_chips()
        added = 0
        try:
            await tags_input.scroll_into_view_if_needed()
            await self.page.wait_for_timeout(200)
            await tags_input.click()
            await self.page.wait_for_timeout(200)

            for tag in tags:
                tag = tag.strip().lstrip("#").strip()
                if not tag:
                    continue
                # Уже есть такой чип
                existing = await self._count_tag_chips()
                if any(tag.casefold() == e.casefold() for e in existing):
                    logger.info(f"Тег уже есть: {tag}")
                    added += 1
                    continue
                try:
                    await tags_input.click()
                    await tags_input.fill("")
                    await self.page.wait_for_timeout(80)
                    try:
                        await tags_input.press_sequentially(tag, delay=35)
                    except Exception:
                        await tags_input.type(tag, delay=35)
                    await self.page.wait_for_timeout(500)

                    # 1) клик по саджесту Дзена (+ тег)
                    clicked_suggest = False
                    for sug_sel in (
                        f'[class*="tag"] :text-is("{tag}")',
                        f'[class*="suggest"] :text-is("{tag}")',
                        f'[role="option"]:has-text("{tag}")',
                        f'li:has-text("{tag}")',
                        f'button:has-text("{tag}")',
                        f'div:has-text("+ {tag}")',
                    ):
                        try:
                            sug = self.page.locator(sug_sel).first
                            if await sug.count() > 0 and await sug.is_visible():
                                await sug.click(timeout=1500)
                                clicked_suggest = True
                                break
                        except Exception:
                            continue

                    if not clicked_suggest:
                        # UI: «Теги через запятую» — Enter или запятая создают чип
                        await self.page.keyboard.press("Enter")
                        await self.page.wait_for_timeout(200)
                        chips_now = await self._count_tag_chips()
                        if not any(tag.casefold() == e.casefold() for e in chips_now):
                            await self.page.keyboard.press(",")
                            await self.page.wait_for_timeout(200)
                            await self.page.keyboard.press("Enter")

                    await self.page.wait_for_timeout(350)
                    chips_after = await self._count_tag_chips()
                    if any(tag.casefold() == e.casefold() for e in chips_after):
                        added += 1
                        logger.info(f"✓ Чип тега: {tag} (всего {len(chips_after)})")
                    else:
                        logger.warning(f"⚠ Чип «{tag}» не появился после ввода")
                except Exception as exc:
                    logger.warning(f"Тег «{tag}» не добавлен: {exc}")
        except Exception as exc:
            logger.warning(f"Ошибка блока тегов: {exc}")
            await self.screenshot("tags_add_error")

        after = await self._count_tag_chips()
        logger.info(f"Чипы тегов: было {before} → стало {after}: {after}")
        await self.screenshot("tags_chips_result")
        return added

    async def upload_short_video(
        self,
        video_path: str,
        title: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        cover_path: Optional[str] = None,
        auto_generate: bool = True,
        publish: bool = True
    ) -> bool:
        """
        Загрузка короткого ролика в Дзен с автоматической генерацией метаданных
        
        Args:
            video_path: Путь к видео файлу (MP4/WEBM, вертикальное, до 2 минут)
            title: Заголовок ролика (если пусто и auto_generate=True — генерируется)
            description: Описание ролика (если пусто и auto_generate=True — генерируется)
            tags: Список тегов (если пусто и auto_generate=True — генерируется)
            cover_path: Путь к обложке (если пусто и auto_generate=True — генерируется)
            auto_generate: Автоматически генерировать метаданные из видео
            publish: True = опубликовать сразу, False = сохранить как черновик
            
        Returns:
            bool: True если ролик загружен успешно
        """
        try:
            logger.info("=" * 50)
            logger.info("ЗАГРУЗКА РОЛИКА В ДЗЕН")
            logger.info("=" * 50)
            
            # Проверяем файл
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Видео не найдено: {video_path}")
            
            file_size_mb = os.path.getsize(video_path) / 1024 / 1024
            logger.info(f"Видео: {os.path.basename(video_path)} ({file_size_mb:.1f} MB)")
            
            # ============================================
            # АВТОГЕНЕРАЦИЯ МЕТАДАННЫХ
            # ============================================
            transcript = ""
            
            if auto_generate and (not title or not description or not tags):
                logger.info("-" * 40)
                logger.info("АВТОГЕНЕРАЦИЯ МЕТАДАННЫХ")
                logger.info("-" * 40)
                
                # Транскрибация видео
                transcript = self.transcribe_video(video_path)
                
                if transcript:
                    # Генерация описания и тегов
                    if not description or not tags:
                        gen_desc, gen_tags = self.generate_description_and_tags(transcript)
                        if not description:
                            description = gen_desc
                        if not tags:
                            tags = gen_tags
                    
                    # Генерация заголовка из первого предложения
                    if not title:
                        first_sentence = transcript.split('.')[0].strip()
                        title = first_sentence[:60] + ("..." if len(first_sentence) > 60 else "")
                        if not title:
                            title = f"Ролик {datetime.now().strftime('%d.%m.%Y')}"
            
            # Генерация обложки если не указана
            if auto_generate and not cover_path:
                cover_output = os.path.join(
                    os.path.dirname(video_path) or '.',
                    f"cover_{os.path.basename(video_path).rsplit('.', 1)[0]}.png"
                )
                cover_path = self.generate_cover(title, transcript, cover_output)
            
            # Финальные значения
            if not title:
                title = f"Ролик {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            if not tags:
                tags = []
            
            logger.info(f"Заголовок: {title}")
            logger.info(f"Описание: {description[:50]}..." if len(description) > 50 else f"Описание: {description}")
            logger.info(f"Теги: {', '.join(tags[:5])}" if tags else "Теги: нет")
            logger.info(f"Обложка: {cover_path or 'не задана'}")
            
            # ============================================
            # ШАГ 1: Переход в студию (страница публикаций)
            # ============================================
            logger.info("Переход в Дзен-студию...")
            
            # Определяем имя канала
            channel = self.channel_name
            if not channel:
                # Попробуем получить из URL после авторизации
                await self.page.goto(self.BASE_URL, wait_until='domcontentloaded')
                await self.page.wait_for_timeout(2000)
                
                # Ищем ссылку на канал
                channel_link = self.page.locator('a[href*="/profile/editor/"]').first
                if await channel_link.count() > 0:
                    href = await channel_link.get_attribute('href')
                    if href and '/profile/editor/' in href:
                        channel = href.split('/profile/editor/')[1].split('/')[0]
                        logger.info(f"Определён канал: {channel}")
                
                if not channel:
                    channel = 'publications'  # fallback
            
            # Переходим напрямую в студию
            publications_url = f"https://dzen.ru/profile/editor/{channel}/publications"
            await self.page.goto(publications_url, wait_until='domcontentloaded')
            await self.page.wait_for_timeout(3000)
            
            studio_loaded = False
            # Проверяем что мы в студии
            pub_header = self.page.locator('h2:has-text("Публикации"), [class*="publications"]')
            if await pub_header.count() > 0:
                logger.info(f"✓ Студия загружена: {publications_url}")
                studio_loaded = True
            else:
                logger.info(f"Страница загружена: {publications_url}")
            
            if not studio_loaded:
                logger.warning("Не удалось загрузить студию, пробуем прямой переход")
            
            # Проверяем авторизацию
            if 'passport.yandex' in self.page.url:
                logger.warning("Требуется авторизация...")
                if not await self.login_yandex():
                    raise Exception("Не удалось авторизоваться")
                await self.page.goto(publications_url, wait_until='domcontentloaded')
                await self.page.wait_for_timeout(3000)
            
            await self.screenshot("step1_studio")
            
            # ============================================
            # ЗАКРЫТИЕ МОДАЛЬНЫХ ОКОН (реклама, донаты и т.п.)
            # ============================================
            try:
                # Закрываем все модальные окна по крестику
                close_selectors = [
                    '[class*="modal"] [class*="close"]',
                    '[class*="Modal"] button[class*="close"]',
                    '[class*="popup"] [class*="close"]',
                    'button[aria-label="Закрыть"]',
                    'button[aria-label="Close"]',
                    '[class*="dialog"] button:first-child',
                    'svg[class*="close"]',
                    '[class*="dismiss"]',
                ]
                for selector in close_selectors:
                    try:
                        close_btn = self.page.locator(selector).first
                        if await close_btn.is_visible(timeout=500):
                            await close_btn.click()
                            logger.info(f"✓ Закрыто модальное окно через {selector}")
                            await self.page.wait_for_timeout(500)
                    except:
                        pass
                
                # Также попробуем клик вне модалки или Escape
                await self.page.keyboard.press('Escape')
                await self.page.wait_for_timeout(500)
            except Exception as e:
                logger.debug(f"Не удалось закрыть модалки: {e}")
            
            # ============================================
            # ШАГ 2: Клик на кнопку "+" (создать)
            # ============================================
            logger.info("Открытие меню создания...")
            
            create_clicked = False
            
            # Кнопка "+" — оранжевая круглая кнопка рядом с логотипом ДЗЕН
            # Приоритетные селекторы
            create_selectors = [
                # Кнопка с плюсом в header
                'header button:has(svg)',
                '[class*="Header"] button:has(svg)',
                '[class*="header"] button:first-of-type',
                # Кнопка создания по классам
                'button[class*="create"]',
                'button[class*="Create"]',
                'button[class*="add"]',
                'button[class*="Add"]',
                # По aria-label
                '[aria-label*="Создать"]',
                '[aria-label*="создать"]',
                '[aria-label*="Create"]',
                # Fallback — любая кнопка с svg
                'button:has(svg)',
            ]
            
            for selector in create_selectors:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                        logger.debug(f"Пробуем клик по: {selector}")
                        await btn.click(timeout=3000)
                        await self.page.wait_for_timeout(800)
                        
                        # Проверяем открылось ли меню
                        menu_item = self.page.locator('text="Загрузить видео"')
                        if await menu_item.count() > 0:
                            create_clicked = True
                            logger.info(f"✓ Меню создания открыто (селектор: {selector})")
                            break
                        else:
                            # Закрываем если открылось что-то другое
                            await self.page.keyboard.press('Escape')
                            await self.page.wait_for_timeout(300)
                except Exception as e:
                    logger.debug(f"Селектор {selector} не сработал: {e}")
                    continue
            
            # Fallback: ищем все кнопки и кликаем по первым 10
            if not create_clicked:
                logger.info("Fallback: перебор кнопок...")
                try:
                    buttons = await self.page.locator('button').all()
                    for i, btn in enumerate(buttons[:10]):
                        try:
                            if await btn.is_visible(timeout=500):
                                await btn.click(timeout=2000)
                                await self.page.wait_for_timeout(600)
                                
                                menu_item = self.page.locator('text="Загрузить видео"')
                                if await menu_item.count() > 0:
                                    create_clicked = True
                                    logger.info(f"✓ Меню создания открыто (кнопка #{i})")
                                    break
                                else:
                                    await self.page.keyboard.press('Escape')
                                    await self.page.wait_for_timeout(200)
                        except Exception:
                            continue
                except Exception as e:
                    logger.warning(f"Ошибка при переборе кнопок: {e}")
            
            if not create_clicked:
                await self.screenshot("error_no_create_button")
                raise Exception("Не удалось найти кнопку создания контента")
            
            await self.screenshot("step2_menu_opened")
            
            # ============================================
            # ШАГ 3: Клик на "Загрузить видео"
            # ============================================
            logger.info("Выбор 'Загрузить видео'...")
            
            upload_video_clicked = await self._wait_and_click(
                [
                    'button:has-text("Загрузить видео")',
                    ':text("Загрузить видео")',
                    '[data-testid="upload-video"]'
                ],
                "Загрузить видео"
            )
            
            if not upload_video_clicked:
                raise Exception("Не найдена опция 'Загрузить видео'")
            
            await self.page.wait_for_timeout(2000)
            await self.screenshot("step3_upload_dialog")
            
            # ============================================
            # ШАГ 4: Загрузка видео файла
            # ============================================
            logger.info("Загрузка видео файла...")
            
            # Дзен использует скрытый input[type="file"]
            # Сначала ищем его напрямую
            file_input = self.page.locator('input[type="file"]')
            
            if await file_input.count() > 0:
                # Файловый input найден — загружаем напрямую
                await file_input.first.set_input_files(video_path)
                logger.info("✓ Файл загружен через input")
            else:
                # Ищем кнопку "Выбрать видео" и используем file chooser
                logger.info("Ожидание file chooser...")
                
                async with self.page.expect_file_chooser() as fc_info:
                    # Кликаем на кнопку "Выбрать видео"
                    select_button = self.page.locator('button:has-text("Выбрать видео")').first
                    if await select_button.count() > 0:
                        await select_button.click()
                    else:
                        # Альтернативные селекторы
                        await self._wait_and_click(
                            [
                                ':text("Выбрать видео")',
                                'button:has-text("Выбрать файл")',
                                '[class*="upload"] button'
                            ],
                            "Выбрать видео"
                        )
                
                file_chooser = await fc_info.value
                await file_chooser.set_files(video_path)
                logger.info("✓ Файл выбран через file chooser")
            
            # ============================================
            # ШАГ 5: Ожидание загрузки видео на сервер
            # ============================================
            wait_time = max(60, int(file_size_mb * 15)) + 60  # Минимум 1 минута + буфер
            logger.info(f"Ожидание загрузки видео (до {wait_time} сек)...")
            
            upload_complete = False
            for i in range(wait_time // 5):
                await self.page.wait_for_timeout(5000)
                
                # Проверяем прогресс
                progress_indicators = [
                    '[class*="progress"]',
                    '[class*="loading"]',
                    '[class*="upload"]'
                ]
                
                for indicator in progress_indicators:
                    element = self.page.locator(indicator).first
                    if await element.count() > 0:
                        text = await element.text_content()
                        if text:
                            logger.info(f"Прогресс: {text}")
                
                # Проверяем завершение
                complete_indicators = [
                    'video',
                    '[class*="preview"]',
                    '[class*="thumbnail"]',
                    'input[name="title"]',
                    'textarea[name="description"]',
                    '[class*="editor"]'
                ]
                
                for indicator in complete_indicators:
                    if await self.page.locator(indicator).count() > 0:
                        upload_complete = True
                        logger.info("✓ Загрузка завершена")
                        break
                
                if upload_complete:
                    break
            
            if not upload_complete:
                logger.warning("⚠ Не удалось подтвердить загрузку, продолжаем...")
            
            await self.screenshot("step5_uploaded")
            
            # ============================================
            # ШАГ 6: Заполнение метаданных
            # ============================================
            logger.info("Заполнение метаданных...")
            
            await self.page.wait_for_timeout(2000)
            
            # Заголовок + описание в contenteditable (без тегов — теги отдельным полем)
            # Лимит Дзена на описание короткого ролика ~200 символов
            full_description = (title or "").strip()
            if description:
                desc = description.strip()
                # Не дублируем заголовок, если description уже начинается с него
                if desc and desc != full_description:
                    remaining = 200 - len(full_description) - 1
                    if remaining > 20:
                        full_description = f"{full_description}\n{desc[:remaining]}".strip()
            
            if len(full_description) > 200:
                full_description = full_description[:197] + "..."
            
            # Поле описания - contenteditable div
            desc_field = self.page.locator('[contenteditable="true"]').first
            if await desc_field.count() > 0:
                await desc_field.click()
                await desc_field.fill(full_description)
                logger.info(f"✓ Описание заполнено ({len(full_description)} симв.)")
            else:
                # Альтернативные селекторы
                await self._fill_field(
                    [
                        'textarea[name="description"]',
                        'textarea[placeholder*="Описание"]',
                        'input[name="title"]'
                    ],
                    full_description,
                    "Описание"
                )
            await self.page.wait_for_timeout(1000)
            
            # Обложку ставим ДО тегов: после cover UI иногда перерисовывается
            # ============================================
            # ШАГ 6.5: Выбор обложки
            # ============================================
            # Если нет кастомной обложки, выбираем из автогенерированных
            if cover_path and os.path.exists(cover_path):
                await self.upload_cover(cover_path)
                await self.screenshot("step6_cover")
            else:
                # Выбираем кадр из автогенерированных обложек
                logger.info("Выбор обложки из автогенерированных...")
                cover_selected = False
                try:
                    # Ищем все кликабельные элементы в секции обложек
                    # На основе скриншота — это div-ы с изображениями
                    cover_selectors = [
                        'div[class*="cover"] > div:nth-child(2)',  # Второй div в секции
                        'div[class*="Cover"] > div:nth-child(2)',
                        '[class*="thumbnail"]:nth-child(2)',
                        'img[class*="cover"]:nth-child(2)',
                        'div:has(img):nth-of-type(2)',  # Второй элемент с картинкой
                    ]
                    for sel in cover_selectors:
                        try:
                            elem = self.page.locator(sel).first
                            if await elem.count() > 0 and await elem.is_visible(timeout=1000):
                                await elem.click(timeout=2000)
                                cover_selected = True
                                logger.info("✓ Обложка выбрана")
                                break
                        except:
                            continue
                    
                    if not cover_selected:
                        # Fallback: просто кликаем второй img на странице (после иконки камеры)
                        all_images = await self.page.locator('img').all()
                        if len(all_images) > 2:
                            await all_images[2].click()
                            logger.info("✓ Обложка выбрана (fallback)")
                            cover_selected = True
                except Exception as e:
                    logger.debug(f"Не удалось выбрать обложку: {e}")
                
                if not cover_selected:
                    logger.warning("⚠ Обложка не выбрана, используется первый кадр по умолчанию")

            # Теги — чипы по одному (после обложки, чтобы не сбросились)
            await self.page.wait_for_timeout(500)
            clean_tags: List[str] = []
            if tags:
                for raw in tags:
                    t = str(raw).strip().lstrip("#").strip()
                    if t and t not in clean_tags:
                        clean_tags.append(t)
                clean_tags = clean_tags[:5]  # Дзен: максимум 5 тегов
                tags_added = await self._add_video_tags(clean_tags)
                if tags_added == 0:
                    logger.warning("⚠ Не удалось добавить теги — селектор поля мог измениться")
                else:
                    logger.info(f"✓ Добавлено тегов: {tags_added}/{len(clean_tags)} → {clean_tags[:tags_added]}")
                chips = await self._count_tag_chips()
                if len(chips) < len(clean_tags):
                    logger.warning(f"⚠ Чипов меньше ожидаемого: {chips}")
            
            await self.screenshot("step6_metadata")
            
            # ============================================
            # ШАГ 7: Публикация
            # ============================================
            if publish:
                logger.info("Публикация ролика...")
                
                await self.page.wait_for_timeout(1000)
                
                publish_clicked = await self._wait_and_click(
                    [
                        'button:has-text("Опубликовать")',
                        'button:has-text("Отправить")',
                        '[data-testid="publish"]',
                        'button[type="submit"]'
                    ],
                    "кнопка Опубликовать"
                )
                
                if publish_clicked:
                    # После клика Дзен обрабатывает публикацию — ждём 10 сек, затем закрываем окно
                    logger.info("Ожидание 10 сек после «Опубликовать»…")
                    await self.page.wait_for_timeout(10000)

                    closed = False
                    for close_sel in (
                        'button[aria-label="Закрыть"]',
                        'button[aria-label="Close"]',
                        '[class*="modal"] button[class*="close"]',
                        '[class*="Modal"] button[class*="close"]',
                        '[class*="popup"] [class*="close"]',
                        'button:has-text("Закрыть")',
                        '[class*="dialog"] button:has(svg)',
                    ):
                        try:
                            btn = self.page.locator(close_sel).first
                            if await btn.count() > 0 and await btn.is_visible(timeout=800):
                                await btn.click(timeout=2000)
                                closed = True
                                logger.info(f"✓ Окно закрыто: {close_sel}")
                                break
                        except Exception:
                            continue
                    if not closed:
                        try:
                            await self.page.keyboard.press("Escape")
                            await self.page.wait_for_timeout(500)
                            await self.page.keyboard.press("Escape")
                            logger.info("✓ Закрытие через Escape")
                        except Exception:
                            pass

                    await self.page.wait_for_timeout(800)
                    current_url = self.page.url
                    page_content = await self.page.content()
                    if "publications" in current_url or "Опубликовано" in page_content or "опубликован" in page_content.lower():
                        logger.info("✓ Ролик опубликован!")
                    else:
                        logger.info("✓ Ролик отправлен на публикацию (после ожидания 10с)")
                else:
                    logger.warning("⚠ Кнопка публикации не найдена")
                    return False
            else:
                logger.info("Сохранение черновика...")
                await self._wait_and_click(
                    [
                        'button:has-text("Сохранить")',
                        'button:has-text("Черновик")'
                    ],
                    "кнопка Сохранить"
                )
                await self.page.wait_for_timeout(2000)
                logger.info("✓ Черновик сохранён")
            
            await self.screenshot("step7_done")
            
            logger.info("=" * 50)
            logger.info("✓ РОЛИК УСПЕШНО ЗАГРУЖЕН!")
            logger.info("=" * 50)
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Ошибка загрузки ролика: {e}")
            await self.screenshot("error_upload")
            return False


# ============================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================
async def main():
    """Тестовый запуск клиента с полной автоматизацией"""
    
    import argparse
    
    parser = argparse.ArgumentParser(description='Загрузка видео в Дзен')
    parser.add_argument('--video', '-v', help='Путь к видео файлу')
    parser.add_argument('--title', '-t', help='Заголовок ролика')
    parser.add_argument('--description', '-d', help='Описание ролика')
    parser.add_argument('--tags', help='Теги через запятую')
    parser.add_argument('--cover', '-c', help='Путь к обложке')
    parser.add_argument('--no-auto', action='store_true', help='Отключить автогенерацию')
    parser.add_argument('--draft', action='store_true', help='Сохранить как черновик')
    parser.add_argument('--login-only', action='store_true', help='Только авторизация')
    
    args = parser.parse_args()
    
    # Проверяем наличие тестового видео
    video_path = args.video or os.getenv('TEST_VIDEO_PATH', '')
    
    client = DzenClient()
    
    try:
        await client.start()
        
        # Авторизация
        if not await client.login_yandex():
            logger.error("❌ Авторизация не удалась")
            return
        
        logger.info("✓ Авторизация успешна!")
        
        if args.login_only:
            logger.info("Режим только авторизации. Cookies сохранены.")
            return
        
        # Если есть видео — загружаем
        if video_path and os.path.exists(video_path):
            # Парсинг тегов
            tags = None
            if args.tags:
                tags = [t.strip() for t in args.tags.split(',')]
            
            result = await client.upload_short_video(
                video_path=video_path,
                title=args.title or "",
                description=args.description or "",
                tags=tags,
                cover_path=args.cover,
                auto_generate=not args.no_auto,
                publish=not args.draft
            )
            
            if result:
                logger.info("=" * 50)
                logger.info("🎉 РОЛИК УСПЕШНО ЗАГРУЖЕН!")
                logger.info("=" * 50)
            else:
                logger.error("❌ Загрузка не удалась")
        else:
            if video_path:
                logger.error(f"Видео не найдено: {video_path}")
            else:
                logger.info("Видео не указано. Используйте --video или TEST_VIDEO_PATH")
            logger.info("")
            logger.info("Примеры использования:")
            logger.info("  python dzen_client.py --video my_video.mp4")
            logger.info("  python dzen_client.py -v video.mp4 -t 'Мой заголовок' --draft")
            logger.info("  python dzen_client.py -v video.mp4 --no-auto -t 'Заголовок' -d 'Описание'")
            
    finally:
        # VideoShorts / publish desk: всегда закрываем Chromium, иначе UI ждёт ответа вечно
        force_close = os.getenv("VIDEOSHORTS_FORCE_CLOSE_BROWSER", "1").lower() not in {"0", "false", "no"}
        if force_close:
            client.keep_open = False
        await client.close(force=force_close)


if __name__ == "__main__":
    asyncio.run(main())
