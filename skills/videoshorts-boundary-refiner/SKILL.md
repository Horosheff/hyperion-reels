---
name: videoshorts-boundary-refiner
description: Границы мысли + монтажное ТЗ — пишет refined-moments, clip-decisions и montage-plan.
---

# VideoShorts Boundary Refiner (+ montage)

Прочитай `shared/agent-decision-contract.md`.

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

## Действия

1. Уточни start/end по segment/word/silence/filler; **не** режь punch-pause ~1.2s после hook.
2. В `clips[]` только `finished_thought_gate=pass`. Обрывки → `rejected_clips[]`.
3. Уважай editor REJECT (и согласованный virality/scores REJECT). При конфликте — чини границу word-evidence или reject.
4. Для каждого keep-клипа собери montage: `jump_cuts`, `silence_remove`, `filler_remove`/`glue_notes`, `zoom_punch`, `do_not_cut_before`, `do_not_cut_after`, статус `READY_FOR_CUTTER`. Leading silence после hook не в auto-cut. Уважай brief `zoomPunch`.
5. **Write** `moments/refined-moments.json` (`decision_source: agent`, `authored_by: videoshorts-boundary-refiner`).
6. **Write** финальный `moments/clip-decisions.json` со всеми REQUIRED decision fields, `selected_by_agent: true` только с evidence.
7. **Write** `moments/montage-plan.json` (`authored_by: videoshorts-boundary-refiner`).

## Validate

```bash
cd scripts
python validate_agent_artifacts.py refined-moments "../videoshorts-memory/moments/refined-moments.json"
python validate_agent_artifacts.py clip-decisions "../videoshorts-memory/moments/clip-decisions.json"
python validate_agent_artifacts.py montage-plan "../videoshorts-memory/moments/montage-plan.json"
```

Fragment `fragments/boundary-refiner.md` + `incident_report` (укажи, что montage-plan тоже написан).
