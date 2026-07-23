# Контракт решений: агент пишет, скрипт исполняет

## Правило

В **Agent mode** субагент — единственный автор смысловых артефактов.

| Слой | Делает |
|------|--------|
| Субагент (Task) | Читает входы, **решает**, пишет JSON инструментом **Write** |
| `validate_agent_artifacts.py` | Проверяет схему и обязательные поля |
| Скрипты без `--heuristic` | **Не** генерируют решения (exit 3) |
| Скрипты с `--heuristic` | Только `run_pipeline.py` / локальная диагностика |
| Механика (ffmpeg, Whisper, burn, package) | Скрипты-инструменты — агент их вызывает |

## Запрещено в Agent mode

- Запускать `write_metadata.py`, `score_clips.py`, `editor_review.py`, `find_moments.py` и т.п. **без** `--heuristic` как «сделай за меня».
- Считать `local_heuristic_draft` финальным решением.
- Ставить `selected_by_agent=true` без реальной редакторской проверки.

## Обязательные поля верхнего уровня

Каждый decision-артефакт:

```json
{
  "schema_version": 1,
  "decision_source": "agent",
  "authored_by": "videoshorts-<role>"
}
```

`decision_source` должен быть ровно `"agent"`. Значения `local_heuristic_draft` и эвристики — только для local fallback.

## Decision-артефакты (агент пишет сам) — slim P0

| Роль | Файл |
|------|------|
| cleanup-planner | `transcripts/<stem>/cleanup-plan.json`, `filler-removal-plan.json` |
| candidate-generator | `moments/candidate-moments.json` |
| moment-finder | `moments/<stem>-moments.json` |
| **editor** (единый) | `moments/clip-scores.json` + `editor-review.json` + `virality-review.json` (`authored_by: videoshorts-editor`) |
| **boundary-refiner** | `moments/refined-moments.json` + `clip-decisions.json` + **`montage-plan.json`** |
| **guardian** | `output/clips/<stem>/post-render-review.json` (+ QA reports через `qa_clips.py`) |
| metadata-writer | `output/clips/<stem>/metadata/*.json` + `*.md` + `metadata-manifest.json` (`json` + `markdown` paths) |

### Legacy (не вызывать в slim run)

`scorekeeper`, `virality-critic`, `dramaturg`, `montage-planner`, `post-render-reviewer` — только ручной repair.  
`dramaturgy-report.json` в slim **не обязателен** (packager терпит отсутствие).

`clip-decisions.json` — канонический agent gate перед cutter/packager.

## Duration policy (brief → агенты)

UI / brief задают `clip_count`, `min_sec`, `max_sec`. Это **жёсткий контракт** для candidate-generator, moment-finder, editor, boundary-refiner, guardian:

| Правило | Смысл |
|---------|--------|
| Диапазон | каждый keep-клип в `[min_sec, max_sec]` (±2 с word-snap) |
| Не midpoint-only | запрещены все окна одной длины и все клипы ±5 с от `(min+max)/2` |
| Spread | при `max_sec ≥ 75` целиться в short / mid / long (часть клипов до `max_sec`) |
| Ceiling ≠ target | `max_sec` — потолок; но long-мысли **можно и нужно** тянуть к нему, не резать «под 45–55» без новой темы |
| Quota | `clip_count` — целевой keep; меньше — только с editor evidence + notes |
| QA | `qa_clips.py --min/--max` = brief, не хардкод 30/60 |

Устаревшие формулировки «всегда 30–60» в docs/skills — игнорировать в пользу brief.

## Механика (скрипты ок)

`transcribe.py`, `cut_clips.py`, `audio_polish.py`, `write_subtitles.py`, `burn_subtitles.py`, `qa_clips.py` (ffprobe), `package_outputs.py`, `prepare_covers.py`, `publish_selection.py`, `prepare_publish_queue.py`, `ensure_dependencies.py`, `ui_server.py`, `broll_*`.

## Проверка после Write

```bash
cd scripts
python validate_agent_artifacts.py <kind> <path>
```

Kinds: `cleanup-plan`, `candidates`, `moments`, `clip-scores`, `editor-review`, `virality-review`, `refined-moments`, `clip-decisions`, `dramaturgy-report`, `montage-plan`, `post-render-review`, `metadata`.

Код выхода: `0` OK, `2` schema fail.

## Local diagnostic

`run_pipeline.py` передаёт `--heuristic` во все decision-скрипты и **не** является agent-пайплайном.
