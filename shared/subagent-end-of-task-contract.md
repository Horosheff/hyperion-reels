# Конец задачи — все субагенты VideoShorts

**Обязательно** перед завершением любого шага пайплайна.

## 0. Decision contract

Если шаг **смысловой** (moments, scores, editor, metadata, decisions…) — сначала:

`shared/agent-decision-contract.md`

Агент **пишет JSON сам** (`decision_source: agent`). Эвристические скрипты без `--heuristic` запрещены.

Проверка:

```bash
cd scripts
python validate_agent_artifacts.py <kind> <path>
```

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

**По умолчанию субагент пишет fragment; handoff склеивает Директор.**

- Если в промпте есть `PARALLEL_WAVE=1` / «параллельная волна» — **запрещено** писать в `.cursor/videoshorts-handoff.md` (только fragment + JSON-артефакты).
- Если шаг строго последовательный и Директор явно просит — можно дописать свой блок в handoff **после** fragment.

Директор переносит fragment в `.cursor/videoshorts-handoff.md`:

```text
=== VIDEOSHORTS-SYSTEM-PROFILER ===
=== VIDEOSHORTS-INTAKE ===
=== VIDEOSHORTS-TRANSCRIBER ===
=== VIDEOSHORTS-CLEANUP-PLANNER ===
=== VIDEOSHORTS-CANDIDATE-GENERATOR ===
=== VIDEOSHORTS-MOMENT-FINDER ===
=== VIDEOSHORTS-SCOREKEEPER ===
=== VIDEOSHORTS-EDITOR ===
=== VIDEOSHORTS-VIRALITY-CRITIC ===
=== VIDEOSHORTS-BOUNDARY-REFINER ===
=== VIDEOSHORTS-DRAMATURG ===
=== VIDEOSHORTS-MONTAGE-PLANNER ===
=== VIDEOSHORTS-CUTTER ===
=== VIDEOSHORTS-AUDIO-POLISHER ===
=== VIDEOSHORTS-SUBTITLE-WRITER ===
=== VIDEOSHORTS-SUBTITLE-BURNER ===
=== VIDEOSHORTS-GUARDIAN ===
=== VIDEOSHORTS-POST-RENDER-REVIEWER ===
=== VIDEOSHORTS-METADATA-WRITER ===
=== VIDEOSHORTS-PACKAGER ===
=== VIDEOSHORTS-FIXIC ===
```
