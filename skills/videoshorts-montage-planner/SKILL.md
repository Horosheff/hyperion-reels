---
name: videoshorts-montage-planner
description: Пишет монтажное ТЗ для cutter.
---

# VideoShorts Montage Planner

## Вход

- `refined-moments.json`
- `cleanup-plan.json`
- `dramaturgy-report.json`

## Действия

1. Сформировать монтажное ТЗ: `jump_cuts`, `silence_remove`, `glue_notes`, `zoom_punch`, `do_not_cut_before`, `do_not_cut_after`.
2. Можно запустить draft-инструмент:

```bash
cd scripts
python montage_plan.py "../videoshorts-memory/moments/refined-moments.json" \
  --cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json" \
  --dramaturgy-report "../videoshorts-memory/moments/dramaturgy-report.json" \
  --brief "../videoshorts-memory/run-request.json" \
  -o "../videoshorts-memory/moments/montage-plan.json"
```

Draft читает `zoomPunch`/`progressBar` из brief/`run-request.json` и **не** включает zoom при brief=false даже если `hook_score≥55`. Leading silence в окне hook (~1.2s) и mid-phrase gaps не попадают в auto `jump_cuts`.

3. В Agent mode вручную проверить, что удаление silence/filler не ломает интонацию и причинно-следственную связь.
4. `do_not_cut_before/after` — hard guidance для cutter и post-render reviewer.

## Выход

`videoshorts-memory/moments/montage-plan.json`.

Fragment `videoshorts-memory/fragments/montage-planner.md` с `incident_report`.
