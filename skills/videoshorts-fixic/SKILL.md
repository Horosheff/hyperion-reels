---
name: videoshorts-fixic
description: Post-run durable fixes из pipeline-fix-queue в skills/scripts/pitfalls.
---

# VideoShorts Fixic

## Когда

Директор вызывает автоматически после run, если в `videoshorts-memory/pipeline-fix-queue.md` есть `status: open` или любой `videoshorts-memory/fragments/*.md` содержит `incident_report:` не `none`.

Проверка:

```bash
python scripts/incident_queue.py --project-root .
```

Код `2` / `OPEN_INCIDENTS=1` означает: вызвать `videoshorts-fixic`.

## Действия

1. Прочитать все open INC
2. Классифицировать: script bug / skill gap / env / user setup
3. Внести **минимальный** durable fix:
   - `shared/agent-pipeline-pitfalls.md` — новый урок
   - `scripts/*.py` — баг
   - `skills/*/SKILL.md` — уточнение шага
4. Пометить INC `status: fixed` с ссылкой на коммит/файл
5. Fragment `videoshorts-memory/fragments/fixic.md`

## Не делать

- Не перезапускать весь пайплайн самому
- Не хранить секреты в queue
