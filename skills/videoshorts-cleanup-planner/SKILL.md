---
name: videoshorts-cleanup-planner
description: Планирует безопасную чистку транскрипта без destructive edit.
---

# VideoShorts Cleanup Planner

## Вход

- `videoshorts-memory/transcripts/<stem>/transcript.json`

## Действия

1. Сначала работать как **монтажёр чистки речи**, а не как скрипт:
   - найти паузы, filler/default words, повторы, false starts и места, где склейка может сломать смысл;
   - `cleanup_plan.py` даёт машинный draft, но финальную пригодность safe/review items оценивает агент;
   - ничего не удалять из `transcript.json`; все решения должны быть объяснимы для scorekeeper/refiner/decision artifact.

2. Запустить:

```bash
cd scripts
python cleanup_plan.py "../videoshorts-memory/transcripts/<stem>/transcript.json"
```

3. Проверить, что скрипт пишет только планы:
   - `cleanup-plan.json`
   - `filler-removal-plan.json`

4. Не редактировать `transcript.json`. Silence gaps и filler words — кандидаты, повторы и false starts — review-only по умолчанию.

5. В fragment кратко указать:
   - сколько safe silence/filler кандидатов найдено;
   - какие типы cleanup должны влиять на boundary-refiner;
   - где нужна осторожная склейка (`glue_or_transition_notes` для будущего `clip-decisions.json`).

## Выход

Fragment `videoshorts-memory/fragments/cleanup-planner.md`:

```text
=== VIDEOSHORTS-CLEANUP-PLANNER ===
status: ✅ PASS | ❌ FAIL
cleanup_plan: videoshorts-memory/transcripts/<stem>/cleanup-plan.json
filler_plan: videoshorts-memory/transcripts/<stem>/filler-removal-plan.json
agent_cleanup_notes: какие удаления безопасны, какие только review-only
incident_report: none
```
