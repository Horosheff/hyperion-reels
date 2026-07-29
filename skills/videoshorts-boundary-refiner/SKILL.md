---
name: videoshorts-boundary-refiner
description: Границы мысли + монтажное ТЗ — пишет refined-moments, clip-decisions и montage-plan.
---

# VideoShorts Boundary Refiner (+ montage)

Прочитай `shared/agent-decision-contract.md` и
`shared/editorial-selection-contract.md`.

## Роль

Финальные границы для cutter **и** монтажное ТЗ. Отдельный Task `montage-planner` в slim-пайплайне **не вызывается**.

`refine_boundaries.py` / `montage_plan.py` / `write_agent_decisions.py` — только local `--heuristic`.

## Вход

- moments, transcript, cleanup-plan
- `editor-review.json` + `clip-scores.json` + `virality-review.json` (все от `videoshorts-editor`)
- brief: `min_sec`, `max_sec`, `zoomPunch`, `progressBar`, `layout` / profile

## Duration (из brief)

- Читай `min_sec` / `max_sec` из brief. Финальный `duration` keep-клипа должен остаться в диапазоне (допуск word-snap ±2 с).
- **Не** укорачивай long-клипы (70–`max_sec`) «под привычный шорт 45–55», если payoff ещё не закрыт или закрыт только что — оставляй полный payoff.
- Обрезай хвост **только** когда начинается новая микротема / editor явно просил trim.
- Не раздувай клип паузами сверх `max_sec`.
- В `duration_policy` / notes пиши фактический диапазон brief (например `variable_30_90_sec`), не хардкод `30_60`.

### Post-cleanup gate (обязательно, INC-20260725-2041)

Guardian QA меряет **финальный** MP4 после jump-cut/silence cleanup, не сырое окно.

- Для каждого keep-клипа посчитай `estimated_duration_after_cleanup` (= `estimated_clean_duration` = raw − planned removals).
- **Gate:** `estimated_duration_after_cleanup ≥ brief.min_sec − 2`.
- Если ниже — **расширь** raw start/end (пока не упрёшься в topic-shift / max_sec) или **смягчи** jump_cuts / silence_remove; иначе → `rejected_clips[]` / montage `status: REVIEW`, **не** `READY_FOR_CUTTER`.
- Поля пиши в clip и в `boundary_refinement` / montage clip.

## Действия

1. Уточни start/end по segment/word/silence/filler; **не** режь punch-pause ~1.2s после hook.
2. В `clips[]` только `finished_thought_gate=pass` **и** post-cleanup gate pass. Обрывки / слишком короткий clean → `rejected_clips[]`.
3. Уважай editor REJECT (и согласованный virality/scores REJECT). При конфликте — чини границу word-evidence или reject.
4. Для каждого keep-клипа прочитай `cleanup_risks` и `do_not_cut` от moment-finder
   вместе с `cleanup-plan.json`. Каждый item с `action: remove` должен:
   - попасть в `silence_remove.items` или `filler_remove.items` с `safe: true`; либо
   - для repeat/false-start попасть в `jump_cuts` с `agent_reason` и
     непустым `glue_notes`; либо
   - получить `preserve_reason` / `skip_reason` в montage-plan.
   Никогда не удаляй `do_not_cut` и не удаляй reaction/punch паузу только потому,
   что она длиннее порога.
5. Для каждого keep-клипа собери исполнимый montage: `jump_cuts`,
   `silence_remove`, `filler_remove`, `glue_notes`, `zoom_punch`,
   `do_not_cut_before`, `do_not_cut_after`, `estimated_duration_after_cleanup`,
   `cleanup_planned`. `READY_FOR_CUTTER` только если clean ≥ min_sec−2. Leading
   silence после hook не в auto-cut. Уважай brief `zoomPunch`.
6. **Write** `moments/refined-moments.json` (`decision_source: agent`, `authored_by: videoshorts-boundary-refiner`).
7. **Write** финальный `moments/clip-decisions.json` со всеми REQUIRED decision fields, `selected_by_agent: true` только с evidence.
8. **Write** `moments/montage-plan.json` (`authored_by: videoshorts-boundary-refiner`).


## Validate

```bash
cd scripts
python validate_agent_artifacts.py refined-moments "../videoshorts-memory/moments/refined-moments.json"
python validate_agent_artifacts.py clip-decisions "../videoshorts-memory/moments/clip-decisions.json"
python validate_agent_artifacts.py montage-plan "../videoshorts-memory/moments/montage-plan.json"
```

**Editorial-bundle gate (обязательно после записи всех трёх артефактов):**

```bash
python validate_agent_artifacts.py editorial-bundle "../videoshorts-memory/moments"
```

Если bundle не прошёл — исправь расхождения (keep-индексы, READY_FOR_CUTTER, cleanup remove→montage, overlap > 3s) **до** передачи cutter. Без bundle PASS cutter не запускать.

Fragment `fragments/boundary-refiner.md` + `incident_report` (укажи, что montage-plan тоже написан).
