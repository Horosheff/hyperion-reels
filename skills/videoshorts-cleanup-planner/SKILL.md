---
name: videoshorts-cleanup-planner
description: План чистки речи — пишет cleanup-plan.json сам, transcript не трогает.
---

# VideoShorts Cleanup Planner

Прочитай `shared/agent-decision-contract.md` и
`shared/editorial-selection-contract.md`.

## Роль

`cleanup_plan.py` — только local `--heuristic`. Ничего не удаляй из
`transcript.json`. Ты создаёшь полный инвентарь и первую редакторскую гипотезу,
а не выдаёшь скриптовый список за финальный монтаж.

## Политика умной чистки

- Явная техническая тишина, лишние `эээ/ну/типа` и случайный повтор — кандидаты
  на удаление.
- Punch-пауза, реакция, смех, вдох перед важной мыслью и пауза для восприятия —
  `preserve`, даже если они длиннее обычного.
- False start / repeat / overlap между сегментами не удаляй автоматически:
  назначь `review`, процитируй контекст и объясни, почему это можно или нельзя
  склеить.

Каждый item обязан иметь `type`, `start`, `end`, `action` (`remove|preserve|review`)
и `reason`. Для удаляемых items укажи `safe: true`; для review/preserve —
`safe: false`.

## Silero VAD (точная тишина)

Если установлен пакет `silero-vad` (есть в requirements.txt), перед планом
сгенерируй акустическую карту речи/тишины по исходному видео:

```bash
cd scripts
python vad_spans.py "../videoshorts-memory/input/<source>.mp4" `
  -o "../videoshorts-memory/transcripts/<stem>/vad-speech-spans.json"
```

`cleanup_plan.py --heuristic` подхватит `vad-speech-spans.json` автоматически
(или передай `--vad-spans`) и возьмёт silence gaps из VAD — это акустическая
истина, а не разрывы word-timestamps Whisper (~77% word-gap «пауз» — дыхание,
шум, дрейф таймстампов, резать по ним нельзя). В cleanup-plan.json поле
`silence_source: silero_vad | word_gap_heuristic`. Если пакета нет или
`VIDEOSHORTS_VAD=0` — fallback на word-gap эвристику.

## Действия

1. Прочитай transcript с ближайшим контекстом, найди silence gaps, fillers,
   repeated words, false starts, cross-segment repeats и опасные склейки.
2. Сформируй:
   - `safe_removal_plan`: только `action: remove`, `safe: true`;
   - `review_only`: все `action: review`;
   - `preserve_plan`: все `action: preserve`;
   - исходные arrays по типам, чтобы boundary-refiner мог сверить контекст.
3. В `summary` добавь `remove_count`, `review_count`, `preserve_count` и
   `repeat_false_start_candidates`.
4. **Write**:
   - `transcripts/<stem>/cleanup-plan.json`
   - `transcripts/<stem>/filler-removal-plan.json`
   оба с `decision_source: agent`, `authored_by: videoshorts-cleanup-planner`
5. Validate:

```bash
cd scripts
python validate_agent_artifacts.py cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json"
```

Fragment `fragments/cleanup-planner.md` + `incident_report`. В fragment укажи
количество remove/review/preserve и все спорные false starts/repeats, которые
должен решить boundary-refiner.
