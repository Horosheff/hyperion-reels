# Публикация Гиперион

Красивый контур после нарезки: SEO-тексты → выбор клипов → обложки → очередь → **параллельная** публикация в Дзен / VK / RuTube / TikTok (Playwright).

## Схема

```mermaid
flowchart TD
  A[Клипы готовы + Guardian PASS] --> B[metadata-writer]
  B --> C[Results UI: смотрим ролики]
  C --> D[Галочки: какие публиковать]
  D --> E[Платформы: Дзен / VK / RuTube / TikTok]
  E --> F[prepare_covers Kie]
  F --> G[prepare_publish_queue]
  G --> H[READY_TO_PUBLISH]
  H --> I["Опубликовать по галочкам — параллельно"]
  I --> J1[dzen_client]
  I --> J2[vk_client]
  I --> J3[rutube_client]
  I --> J4[tiktok_client]
```

## 1. SEO titles и descriptions

Агент: `videoshorts-metadata-writer` — **пишет JSON сам** (`decision_source: agent`).

| Платформа | Поля |
|-----------|------|
| YouTube | title, description + SEO keywords + hashtags, pinned_comment |
| Instagram | title, caption, hashtags, first_comment |
| TikTok | title, description, hashtags |
| Telegram | title, caption |
| VK / Дзен | title, description, до 5 тегов (чипы) |

## 2. Выбор клипов в UI

Откройте `http://127.0.0.1:8765/results`

1. Смотрите клип
2. SEO-вкладки (в т.ч. VK / Дзен)
3. Галочка **«Публиковать этот клип»**
4. Платформы (**Дзен / VK / RuTube / TikTok**)
5. **«Подготовить обложки»** — Kie только для выбранных
6. **«Опубликовать (по галочкам)»** — все отмеченные платформы стартуют **одновременно** (`/api/publish-platforms`, `ThreadPoolExecutor`)

Playwright-окна открываются на **мониторе №1 (правый)** — см. `docs/PLAYWRIGHT-DISPLAY.md` (`PLAYWRIGHT_MONITOR=1`).

## 3. Обложки (Kie GPT Image 2, 9:16)

Скрипт: `scripts/prepare_covers.py`

Brand kit: `videoshorts-memory/brand/covers/brand-urls.json` (HTTPS avatar + refs).

Ключ: `videoshorts.local.env` → `KIE_API_KEY` (шаблон: `videoshorts.local.env.example`).

## 4. Очередь публикации

`scripts/prepare_publish_queue.py` → `publish-queue.json`

- `zen` → `adapter: playwright:dzen`
- `vk` → `adapter: playwright:vk` (`publish_vk.py`)
- `rutube` → `adapter: playwright:rutube` (`publish_rutube.py`) — обложка: таб **Shorts** обязателен
- `tiktok` → `adapter: playwright:tiktok` (`publish_tiktok.py`) — диалог «Продолжить публикацию?» → второе **Опубликовать**

## 5. Дзен (внутри плагина)

Всё bundled — **не нужен** внешний каталог Tilda:

| Файл | Назначение |
|------|------------|
| `scripts/dzen_client.py` | Playwright: upload, description, ≤5 тегов-чипов, Publish, закрытие браузера |
| `scripts/publish_dzen.py` | Обёртка для Results UI / CLI |
| `scripts/dzen_login_save.py` | Ручной вход → cookies |
| `videoshorts-memory/secrets/dzen_storage_state.json` | Cookies (gitignored) |
| `videoshorts.local.env` | `DZEN_CHANNEL_NAME`, опционально login (gitignored) |

Шаблон env: `videoshorts.local.env.example`.

Зависимости: `playwright`, `python-dotenv` в `scripts/requirements.txt`  
(после install: `playwright install chromium`).

### UI

1. **Войти в Дзен (cookies)** — Playwright headed; cookies → `videoshorts-memory/secrets/`.
2. На карточке: галочки платформ → **Опубликовать (по галочкам)** (параллельно со всеми отмеченными).
3. После Publish: ждать завершения всех браузеров → зелёные галочки в Results.

### CLI

```powershell
cd scripts
python publish_dzen.py --status
python publish_dzen.py --login-only
python publish_dzen.py ..\videoshorts-memory\output\clips\<stem> --index 7 --draft
python publish_dzen.py ..\videoshorts-memory\output\clips\<stem> --index 7
python publish_vk.py ..\videoshorts-memory\output\clips\<stem> --index 1
python publish_rutube.py ..\videoshorts-memory\output\clips\<stem> --index 1
python publish_tiktok.py ..\videoshorts-memory\output\clips\<stem> --index 1
```

Ограничения Дзен: вертикаль 9:16, до ~2 мин, MP4/WEBM, **максимум 5 тегов**.

Лог: `output/clips/<stem>/dzen-publish-log.json`  
Скриншоты: `videoshorts-memory/output/dzen-screenshots/`

## 6. Adapters

| Adapter | Статус |
|---------|--------|
| `playwright:dzen` | готов |
| `playwright:vk` | готов |
| `playwright:rutube` | готов (Shorts cover) |
| `playwright:tiktok` | готов (confirm dialog) |
| YouTube / IG / TG API | позже |

## Агенты

| Агент | Роль |
|-------|------|
| `videoshorts-metadata-writer` | SEO titles/descriptions |
| `videoshorts-cover-writer` | AI-обложки выбранных клипов |
| `videoshorts-publish-prep` | selection → covers → queue → (кнопка UI) |

## Чеклист

- [ ] Клипы прошли QA
- [ ] Метаданные есть
- [ ] Выбраны клипы + платформы (Дзен / VK / RuTube / TikTok)
- [ ] Обложки готовы
- [ ] Cookies платформ (или «Войти…»)
- [ ] «Опубликовать (по галочкам)» — параллельный старт
- [ ] В репозитории нет `videoshorts.local.env` и `secrets/*.json` (только `.example` / `.gitkeep`)
