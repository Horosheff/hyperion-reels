---
name: videoshorts-candidate-generator
description: 30–80 кандидатов — пишет candidate-moments.json сам. Окна переменные по brief min/max.
---

# VideoShorts Candidate Generator

Прочитай `shared/agent-decision-contract.md` (раздел **Duration policy**).

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
2. На каждый: `candidate_reason`, `hook_type`, `audience_pain`, `possible_title`, `why_not_cut_yet`.
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

4. Validate:

```bash
cd scripts
python validate_agent_artifacts.py candidates "../videoshorts-memory/moments/candidate-moments.json"
```

Fragment `fragments/candidate-generator.md` + `incident_report`. Укажи brief min/max и что окна **не** fixed-midpoint.
