---
name: videoshorts-montage-planner
description: LEGACY — не вызывать в slim P0. montage-plan пишет boundary-refiner.
---

# LEGACY: Montage Planner

**Не запускай** в slim P0. См. `videoshorts-boundary-refiner` → `montage-plan.json`.

Если всё же правишь `montage-plan.json` / heuristic `montage_plan.py`:

- `--min-duration` / brief `min_sec` — guard для jump cuts (не хардкод 30 при brief 60).
- `estimated_duration_after_cleanup` ≥ `min_sec − 2` иначе `status: REVIEW`, не `READY_FOR_CUTTER`.
