# Конец задачи — все субагенты VideoShorts

**Обязательно** перед завершением любого шага пайплайна.

## 1. Прочитать pitfalls

`shared/agent-pipeline-pitfalls.md`

## 2. Incident memory

Если был blocker, retry, workaround — **append** в:

`{workspace}/videoshorts-memory/pipeline-fix-queue.md`

Формат:

```markdown
## INC-YYYYMMDD-HHMM-<role>-<slug>
- status: open|fixed
- step: transcriber|moment-finder|cutter|guardian
- summary: ...
```

**Без секретов.**

## 3. Fragment

Путь: `videoshorts-memory/fragments/<role>.md`

**Обязательная строка:**

```text
incident_report: none
```

или:

```text
incident_report: videoshorts-memory/pipeline-fix-queue.md#INC-...
```

## 4. Handoff block

Директор переносит fragment в `.cursor/videoshorts-handoff.md`:

```text
=== VIDEOSHORTS-TRANSCRIBER ===
=== VIDEOSHORTS-MOMENT-FINDER ===
=== VIDEOSHORTS-CUTTER ===
=== VIDEOSHORTS-GUARDIAN ===
=== VIDEOSHORTS-METADATA-WRITER ===
=== VIDEOSHORTS-PACKAGER ===
=== VIDEOSHORTS-FIXIC ===
```
