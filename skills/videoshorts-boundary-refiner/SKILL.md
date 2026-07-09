---
name: videoshorts-boundary-refiner
description: Пишет refined-moments.json, сохраняя переменную длительность 30-60 секунд.
---

# VideoShorts Boundary Refiner

## Вход

- `moments.json`
- `transcript.json`
- `cleanup-plan.json`
- `clip-scores.json`

## Действия

1. Работать как редактор границ мысли:
   - `refine_boundaries.py` учитывает segment/word/silence/filler spans, но финальный gate делает агент;
   - **не** trim leading silence в первые ~1.2s после hook/`thought_start` (пауза после хука — punch, не мусор);
   - при `estimated_clean_duration_below_min` **не** expand past finished payoff / segment closer в чужую тему (Тильда после Cursor); предпочитать keep punch silence;
   - клип без доказательства законченной мысли не отдавать cutter даже если длительность нормальная;
   - если `clip-scores.json` содержит `incomplete_thought`, `clipped_ending`, `contextless_start`, `boring_or_low_viral_potential`, `weak_hook_first_3s` — в `rejected_clips[]` (не оставлять в `clips[]`); голый `weak_hook` — soft, агент перепроверяет.

2. Запустить:

```bash
cd scripts
python refine_boundaries.py "../videoshorts-memory/moments/<stem>-moments.json" \
  "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  --cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json" \
  --scores "../videoshorts-memory/moments/clip-scores.json" \
  -o "../videoshorts-memory/moments/refined-moments.json" \
  --min 30 --max 60
```

3. Проверить `refined-moments.json`:
   - `clips[]` содержит только клипы с `semantic_boundary_evidence.finished_thought_gate=pass`;
   - `rejected_clips[]` содержит отклонённые обрывки с `reject_reason`;
   - `boundary_refinement.cleanup_refinement` показывает, какие silence/filler spans повлияли на start/end.

4. Обновить и подтвердить decision artifact:

```bash
cd scripts
python write_agent_decisions.py "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  "../videoshorts-memory/moments/<stem>-moments.json" \
  --cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json" \
  --scores "../videoshorts-memory/moments/clip-scores.json" \
  --refined "../videoshorts-memory/moments/refined-moments.json" \
  -o "../videoshorts-memory/moments/clip-decisions.json"
```

В Agent mode вручную поставить `selected_by_agent=true` только для клипов, где подтверждены `thought_start_evidence` и `thought_end_evidence`.

## Выход

`refined-moments.json` — вход для cutter/subtitle-writer/metadata-writer. Не делать все клипы по 45 секунд: границы должны оставаться переменными и объяснимыми. `rejected_clips[]` — нормальный результат, если агент отбросил обрубки.

`clip-decisions.json` — итоговое агентное объяснение, почему каждый оставшийся клип выбран.

Fragment `videoshorts-memory/fragments/boundary-refiner.md` с `incident_report`.
