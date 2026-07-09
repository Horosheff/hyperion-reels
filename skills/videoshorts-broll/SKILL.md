# VideoShorts B-roll

Запускается только если `bRoll: true` в `videoshorts-memory/00-brief.md`.

## Входы

- `clip-decisions.json`, `refined-moments.json`, `dramaturgy-report.json`, `montage-plan.json`;
- `transcript.json` с `words[]`;
- `output/clips/<stem>/manifest.json`.

## Бюджет и отбор

- Не более `bRollMax` вставок, в тестовом UI — максимум **3 на исходное видео**.
- Одна вставка на один клип, длительность 2–3 секунды.
- Не ставить в первые 2 секунды hook, на сильное лицо/эмоциональный payoff, внутри слова, либо если экран уже наглядно показывает тезис.
- Выбирать только визуализируемые смыслы: сравнение, схема процесса, риск/лимит, архитектура, число/метрика или итог.

## Визуальный контракт webinar

Каждая вставка — полноэкранная 9:16 информационная сцена: 3D-схема, архитектурная метафора или нейтральная data-визуализация, которая объясняет конкретный тезис. Это не декоративный фон и не маленький оверлей. Запрещены: текст в кадре, логотипы, интерфейс реального продукта, фотореалистичный человек, лицо/голос спикера, знаменитости.

Сначала создай референс GPT Image 2 (`9:16`, `1K`), затем передай его URL Grok Imagine Video (`9:16`, `720p`, `3s`). Не выводи и не записывай `KIE_API_KEY`.

## Артефакты

В `output/clips/<stem>/`:

- `broll-plan.json`: `clip_index`, `at_sec`, `duration_sec`, тезис, `visual_type`, prompts, placement=`top_screen`, причина, status;
- `broll-jobs.json`: только task IDs, модели, result URLs и статусы; без ключа;
- `broll-assets/clip_XX_broll.mp4`;
- `broll-report.json` после `scripts/broll_composite.py`.

Если ключа нет, запиши `SKIPPED: KIE_API_KEY is not configured`; не делай сетевых вызовов и не считай это успехом генерации.

После генерации и скачивания вызови:

```bash
python scripts/broll_generate.py videoshorts-memory/output/clips/<stem> \
  --plan videoshorts-memory/output/clips/<stem>/broll-plan.json

python scripts/broll_composite.py videoshorts-memory/output/clips/<stem> \
  --plan videoshorts-memory/output/clips/<stem>/broll-plan.json
```

## Handoff

Добавь `=== VIDEOSHORTS-BROLL ===` в `.cursor/videoshorts-handoff.md`, fragment `videoshorts-memory/fragments/broll.md` и `incident_report: none` либо ссылку на incident.
