---
name: videoshorts-scorekeeper
description: LEGACY — не вызывать в slim P0. Оценки пишет videoshorts-editor (опционально через Jev).
---

# LEGACY: Scorekeeper

**Не запускай** этот Task в обычном VideoShorts run.

Работа перенесена в `skills/videoshorts-editor/SKILL.md` (единый editor пишет `clip-scores.json`).

## Jev pilot (clip-scores only)

При ручном repair, если `VIDEOSHORTS_JEV_SCORES=1` и есть `TYPESAFE_API_KEY`:

```bash
cd scripts
python jev_score_clips.py "<moments.json>" "<transcript.json>" -o "<clip-scores.json>" --min 30 --max 60
# или: python score_clips.py … --jev
python validate_agent_artifacts.py clip-scores "<clip-scores.json>"
```

Jev читает только текст (excerpt/hook/payoff), ставит 0–100 scores + optional reject.
`editor-review` / `virality-review` по-прежнему пишет editor.

Оставь skill только для ручного repair / старых чатов.
