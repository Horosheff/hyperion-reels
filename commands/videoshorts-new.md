# VideoShorts — новая нарезка

Запусти пайплайн VideoShorts для видео из brief.

1. Запусти `.\open-videoshorts-ui.ps1` — он откроет `http://127.0.0.1:8765/`.
2. Основной сценарий: кнопка **«Добавить файл локально»** → настройки → **«OK — передать Cursor Director»**.
3. Bridge в режиме по умолчанию `runMode=agent` сохраняет файл в `videoshorts-memory/input/`, пишет `videoshorts-memory/00-brief.md`, `videoshorts-memory/run-request.json`, ставит `READY_FOR_AGENT` и **не запускает** `scripts/run_pipeline.py`.
4. Сбрось `.cursor/videoshorts-handoff.md`.
5. Заполни `videoshorts-memory/00-brief.md`: путь к видео, число клипов, длины, Whisper, субтитры, burn, QA, package.
6. Task P0: videoshorts-system-profiler → intake → transcriber → cleanup-planner → candidate-generator → moment-finder → scorekeeper → editor → virality-critic → boundary-refiner → dramaturg → montage-planner → cutter → audio-polisher → subtitle-writer → subtitle-burner → guardian-v2 (`videoshorts-guardian`) → post-render-reviewer → metadata-writer → packager.
7. P1 docs/stub: layout-planner до cutter и thumbnail-writer перед packager; в P0 их можно не запускать.
8. После `videoshorts-packager` проверь `videoshorts-memory/output/latest-results.json`; результаты доступны в `http://127.0.0.1:8765/results`.
9. Проверь open incidents: `python scripts/incident_queue.py --project-root .`. Если `OPEN_INCIDENTS=1`, запусти Task `videoshorts-fixic`.

HTML передаёт локальный файл на локальный Python bridge, не кодирует MP4 в base64. Рабочий протокол Agent-режима — файл/настройки → brief/run-request → `READY_FOR_AGENT` → Task-цепочка → latest-results.json. Candidate-generator создаёт 30-80 кандидатов, moment-finder выбирает excerpts, scorekeeper оценивает, editor/virality-critic отбраковывают, boundary-refiner уточняет границы, dramaturg проверяет дугу мысли, montage-planner пишет ТЗ, Guardian v2 проверяет QA/audio/safe-zone, post-render-reviewer подтверждает готовые MP4, metadata-writer готовит title/description/hashtags.

Режим `runMode=local` / «Диагностика: локальный backend без субагентов» запускает прямой `scripts/run_pipeline.py` только для тестов и не считается работой Cursor subagents.

См. `rules/videoshorts-orchestrator.mdc` и `README.md`.
