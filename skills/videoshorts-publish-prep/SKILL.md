---
name: videoshorts-publish-prep
description: Selection → covers → publish-queue; Дзен через publish_dzen.py (Playwright).
---

# VideoShorts Publish Prep

## Роль

Собирает финальный пакет к публикации после ручного выбора клипов.
Дзен публикуется из Results UI кнопкой (`publish_dzen.py` → **bundled** `scripts/dzen_client.py`).
Cookies: `videoshorts-memory/secrets/dzen_storage_state.json` (не в git).

## Шаги

1. Убедиться, что есть `metadata-manifest.json` (иначе metadata-writer).
2. Прочитать `publish-selection.json` (галочки; платформы включают `vk`, `zen`).
3. Covers (только selected):

```bash
cd scripts
python prepare_covers.py "../videoshorts-memory/output/clips/<stem>" --mode auto
```

4. Очередь:

```bash
python prepare_publish_queue.py "../videoshorts-memory/output/clips/<stem>"
```

5. `publish-queue.json` → `READY_TO_PUBLISH`; `zen.adapter = playwright:dzen`.

6. Дзен (человек в UI или CLI):

```bash
python publish_dzen.py --login-only
python publish_dzen.py "../videoshorts-memory/output/clips/<stem>" --index N
```

## Не делать сейчас

Не публиковать YouTube/Instagram/TikTok/VK API — только Дзен Playwright.
Не копировать секреты в handoff/fragment.

## Fragment

`videoshorts-memory/fragments/publish-prep.md` + `incident_report`.
