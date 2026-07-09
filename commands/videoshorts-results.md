# VideoShorts — открыть результаты

Открой локальную HTML-панель `ui/videoshorts-results.html` после `videoshorts-packager`.

Источник данных: `videoshorts-memory/output/latest-results.json`.

Если HTML не может сам прочитать локальный JSON без выбора файла, используй протокол:

1. Открой `videoshorts-memory/output/latest-results.json`.
2. Нажми «Открыть latest-results.json» в HTML или вставь JSON в поле вручную.
3. Проверь `qa-report.json`, `safe-zone-report.json`, `audio-qa-report.json`, `clip-scores.json`, `cleanup-plan.json`, `retry-plan.json`, `publish-manifest.json`, пути к клипам и команды открытия папок.

HTML результатов не встраивает MP4 и не кодирует видео в base64.
