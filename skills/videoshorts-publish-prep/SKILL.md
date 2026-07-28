---
name: videoshorts-publish-prep
description: Selection → covers → publish-queue; YouTube/Instagram/TikTok/VK/RuTube/Дзен параллельно из Results UI.
---

# VideoShorts Publish Prep

## Роль

Собирает финальный пакет к публикации после ручного выбора клипов.
Публикация из Results UI: **«Опубликовать (по галочкам)»** → `/api/publish-platforms` стартует **все отмеченные платформы параллельно** (YouTube / Instagram / TikTok / VK / RuTube / Дзен).

Cookies: `videoshorts-memory/secrets/*_storage_state.json` (не в git).

## Шаги

1. Убедиться, что есть `metadata-manifest.json` (иначе metadata-writer).
2. Прочитать `publish-selection.json` (галочки; платформы включают `zen`, `vk`, `rutube`, `tiktok`, `instagram`).
3. Covers (только selected):

```bash
cd scripts
python prepare_covers.py "../videoshorts-memory/output/clips/<stem>" --mode auto
```

4. Очередь:

```bash
python prepare_publish_queue.py "../videoshorts-memory/output/clips/<stem>"
```

5. `publish-queue.json` → `READY_TO_PUBLISH`.

6. UI: отметить платформы → **Опубликовать (по галочкам)** (параллельно).

CLI (по одной платформе, если нужно):

```bash
python publish_dzen.py --login-only
python publish_dzen.py "../videoshorts-memory/output/clips/<stem>" --index N
python publish_vk.py "../videoshorts-memory/output/clips/<stem>" --index N
python publish_rutube.py "../videoshorts-memory/output/clips/<stem>" --index N
python publish_tiktok.py "../videoshorts-memory/output/clips/<stem>" --index N
python publish_instagram.py --login-only
python publish_instagram.py "../videoshorts-memory/output/clips/<stem>" --index N
```

## Важно

- RuTube: в модалке обложки обязателен таб **Shorts** (`rutube_client._select_cover_shorts_tab`).
- TikTok: после Post нажать второе **Опубликовать** в диалоге «Продолжить публикацию?» (`tiktok_client._confirm_publish_dialog`).
- Instagram: только `set_input_files` (без Windows Open dialog); ждать «Reels опубликовано» после Share.
- Параллельный запуск: `ui_server.py` → `ThreadPoolExecutor` по отмеченным платформам.

## Не делать

Не публиковать через внешние API YouTube/Telegram — только Playwright-адаптеры выше.
Не коммитить `videoshorts-memory/secrets/*.json`.

Playwright всегда на мониторе из `PLAYWRIGHT_MONITOR` (default **1 = правый**). См. `docs/PLAYWRIGHT-DISPLAY.md`.
