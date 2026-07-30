# Data-flow контракты субагентов

Кто что читает, что пишет и как это проверяется. Источник истины по схеме —
`scripts/validate_agent_artifacts.py`, по авторству — `shared/agent-decision-contract.md`.

Обозначения: `<stem>` — имя видео без расширения. Все пути относительно `videoshorts-memory/`.

## Slim-цепочка (AGENT_CHAIN в `ui_server.py`)

| # | Агент | Читает (входы) | Пишет (выходы) | Проверка |
|---|-------|----------------|----------------|----------|
| 1 | system-profiler | ПК, Python, FFmpeg, Whisper, Playwright | `system-profile.json`, `dependencies-report.json` | `ready: true`, иначе стоп |
| 2 | intake | Видео + brief из UI (`run-request.json`) | `00-brief.md`, `input/<video>`, `intake-report.json` | brief `min_sec/max_sec/count` |
| 3 | transcriber | `input/<video>` | `transcripts/<stem>/transcript.json` (+ `.srt`) | наличие `segments[]` с таймкодами |
| 4 | cleanup-planner | `transcript.json` | `transcripts/<stem>/cleanup-plan.json`, `filler-removal-plan.json` | `validate cleanup-plan` |
| 5 | moment-finder | `transcript.json`, `cleanup-plan.json`, brief | `moments/candidate-moments.json` → `moments/<stem>-moments.json` | `validate candidates`, `validate moments` |
| 6 | scorekeeper/editor | `<stem>-moments.json` | `moments/clip-scores.json`, `editor-review.json`, `virality-review.json` | `validate clip-scores`, `editor-review`, `virality-review` |
| 7 | boundary-refiner | моменты + оценки, `transcript.json` | `moments/refined-moments.json`, `clip-decisions.json`, `montage-plan.json` | `validate refined-moments`, `clip-decisions`, `montage-plan` + **`validate editorial-bundle`** (кросс-артефактный гейт) |
| 8 | cutter | `input/<video>`, `refined-moments.json`, `montage-plan.json` | `output/clips/<stem>/clip_XX.mp4`, `manifest.json` | **agent gate** (`clip-decisions.json`, `decision_source=agent`) + editorial-bundle PASS |
| 9 | audio-polisher | `clip_XX.mp4` | audio-report в `manifest.json` / loudnorm | ffprobe-метрики |
| 10 | subtitle-writer | `transcript.json`, `refined-moments.json` | `output/clips/<stem>/subtitles/clip_XX.ass`, `subtitles-manifest.json` | наличие ASS per keep-клип |
| 11 | subtitle-burner | `clip_XX.mp4` + ASS | `output/clips/<stem>/final/clip_XX_final.mp4` | файл создан, non-zero size |
| 12 | guardian | final-клипы, brief | `post-render-review.json`, QA через `qa_clips.py`; при FAIL — инцидент в `pipeline-fix-queue.md` | `validate post-render-review` |
| 13 | metadata-writer | final-клипы, моменты | `metadata/clip_XX.metadata.json|md`, `metadata-manifest.json` | `validate metadata` (**вкл. лимиты API платформ**) |
| 14 | packager | всё выше | `output/clips/<stem>-publish/`, `latest-results.json` | agent gate + полнота пакета |

## Publish desk (после packager, ручные галочки в Results UI)

| Агент | Читает | Пишет | Проверка |
|-------|--------|-------|----------|
| publish-prep | `latest-results.json`, выбор пользователя | `output/clips/<stem>/publish-selection.json`, `publish-queue.json` | queue items = выбранные индексы |
| cover-writer | выбранные клипы, `cover_prompt` | `covers-manifest.json`, `covers/clip_XX.png` | `ok: true` per cover |
| fixic | `pipeline-fix-queue.md` | правки в plugin + `status: closed` в инцидентах | нет `status: open` |

## Гейты (порядок не нарушать)

```text
clip-decisions.json (decision_source=agent, selected_by_agent)
        ↓ agent_gate
editorial-bundle (scores/editor/virality/refined/decisions/montage согласованы)
        ↓ PASS
cutter → … → guardian → metadata (лимиты API) → packager
        ↓
publish-selection → covers → publish-queue (атомарные записи через json_store)
```

## Общие правила записи

- Все JSON-артефакты общего состояния пишутся через `scripts/json_store.py`
  (атомарная запись + межпроцессный `.lock`). Не использовать голый `write_text`
  для `publish-queue.json`, `run-status.json`, `pipeline-fix-queue.md`.
- Логи каждого скрипта: `videoshorts-memory/logs/<script>.log` (ротация 3×2 МБ),
  уровень — `VIDEOSHORTS_LOG_LEVEL`, каталог — `VIDEOSHORTS_LOG_DIR`.

## Env-ручки (эксплуатация)

| Переменная | Default | Что ограничивает |
|------------|---------|------------------|
| `VIDEOSHORTS_FFMPEG_TIMEOUT` | 3600 с | один вызов ffmpeg/ffprobe |
| `VIDEOSHORTS_WHISPER_TIMEOUT` | 7200 с | транскрипция |
| `VIDEOSHORTS_PUBLISH_CLIENT_TIMEOUT` | 900 с | publish-клиент на клип |
| `VIDEOSHORTS_PUBLISH_TIMEOUT` | 7200 с | publish-клиент (UI, суммарно) |
| `VIDEOSHORTS_LOGIN_TIMEOUT` | 600 с | login-save из UI |
| `VIDEOSHORTS_COVERS_TIMEOUT` | 1800 с | подготовка обложек из UI |
| `VIDEOSHORTS_QUEUE_TIMEOUT` | 600 с | запись publish-queue из UI |
| `VIDEOSHORTS_PIPELINE_STEP_TIMEOUT` | 10800 с | стадия `run_pipeline.py` (legacy) |
| `VIDEOSHORTS_AGENT_MODE` | — | `1/true/agent` — обязательные agent-решения |
| `VIDEOSHORTS_SHARPEN` | 1 | `0` — отключить unsharp после даунскейла |
| `VIDEOSHORTS_COLOR_GRADE` | 1 | `0` — отключить HDR→SDR тонемаппинг / SDR-грейд |

## Видео-качество (Q1/Q2, рендер-слой)

- **Резкость:** все `scale` — `flags=lanczos`, после кадрирования `unsharp=5:5:0.6`.
- **Цвет:** HDR-источники (smpte2084 / arib-std-b67 / bt2020) проходят `zscale+tonemap=hable` → bt709; SDR получает лёгкий `eq=contrast=1.02:saturation=1.05`.
- **Кодирование:** level 5.1, потолок битрейта release 12M/bufsize 24M, faststart.
- **fps:** источники >60 fps (slow-mo) приводятся к 60; VFR не форсится.
