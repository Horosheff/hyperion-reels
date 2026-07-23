---
name: videoshorts-cleanup-planner
description: План чистки речи — пишет cleanup-plan.json сам, transcript не трогает.
---

# VideoShorts Cleanup Planner

Прочитай `shared/agent-decision-contract.md`.

## Роль

`cleanup_plan.py` — только local `--heuristic`. Ничего не удаляй из `transcript.json`.

## Действия

1. Найди silence gaps, fillers, false starts, опасные склейки.
2. Раздели `safe_removal_plan` vs `review_only`.
3. **Write**:
   - `transcripts/<stem>/cleanup-plan.json`
   - `transcripts/<stem>/filler-removal-plan.json`
   оба с `decision_source: agent`, `authored_by: videoshorts-cleanup-planner`
4. Validate:

```bash
cd scripts
python validate_agent_artifacts.py cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json"
```

Fragment `fragments/cleanup-planner.md` + `incident_report`.
