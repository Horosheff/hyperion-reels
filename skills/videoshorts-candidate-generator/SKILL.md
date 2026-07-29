---
name: videoshorts-candidate-generator
description: 30–80 кандидатов — пишет candidate-moments.json сам. Окна переменные по brief min/max.
---

# VideoShorts Candidate Generator

Прочитай `shared/agent-decision-contract.md` (раздел **Duration policy**) и
`shared/editorial-selection-contract.md`.

## Роль

Сырьё для редакции, **не** вход для cutter. `generate_candidates.py` — только local `--heuristic`.

## Вход

- `transcript.json`, опционально `cleanup-plan.json`
- brief / `run-request.json`: **`min_sec`**, **`max_sec`**, `clip_count`

## Duration / windows (жёстко)

1. Читай `min_sec`/`max_sec` из brief. Не хардкодь 30–60 и не делай **все** окна одной длины.
2. Кандидаты должны иметь **переменный** `duration` в `[min_sec, max_sec]`.
3. При `max_sec ≥ 75` распредели пул примерно:
   - ~⅓ short (`min_sec`…mid−10)
   - ~⅓ mid (около midpoint)
   - ~⅓ long (`max_sec−20`…`max_sec`)
4. Запрещено: `duration_min == duration_max` на всём пуле (кроме патологического короткого видео).
5. В `selection_contract` запиши `min_sec`, `max_sec`, `clip_count_brief`.
6. В `summary` — `duration_min`, `duration_max`, `duration_avg` (или эквивалент).

## Действия

1. Выбери 30–80 потенциальных окон (start/end **переменные** по policy выше).
   Это сырьё для редактора: не подменяй смысловой выбор совпадением с ключевыми
   словами.
2. Не добавляй временные клоны: кандидаты с overlap >3 с должны быть одним
   кандидатом или иметь разные `candidate_angle` с явным объяснением.
3. Распредели кандидаты по разным темам/типам: practical method, case/demo,
   contrarian take, mistake/fix, story, live-proof, Q&A. Не заполняй пул одной
   главой вебинара.
4. На каждый: `candidate_reason`, `hook_type`, `audience_pain`, `possible_title`,
   `why_not_cut_yet`, `candidate_angle`, `theme_fingerprint`,
   `cleanup_risks_hint` (если в окне заметны тишина/филлер/повтор).
3. **Write** `moments/candidate-moments.json`:

```json
{
  "schema_version": 1,
  "decision_source": "agent",
  "authored_by": "videoshorts-candidate-generator",
  "selection_contract": {
    "target_candidates": "30-80",
    "min_sec": 30,
    "max_sec": 90,
    "clip_count_brief": 10
  },
  "candidates": [],
  "summary": { "total": 0, "duration_min": 0, "duration_max": 0 }
}
```

5. В `summary` укажи `distinct_theme_count`, `temporal_duplicates_merged` и
   `cleanup_risk_candidates`, чтобы moment-finder понимал качество пула.
6. Validate:

```bash
cd scripts
python validate_agent_artifacts.py candidates "../videoshorts-memory/moments/candidate-moments.json"
```

Fragment `fragments/candidate-generator.md` + `incident_report`. Укажи brief min/max и что окна **не** fixed-midpoint.
