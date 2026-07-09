---
name: videoshorts-virality-critic
description: Оценивает вирусный потенциал выбранных моментов.
---

# VideoShorts Virality Critic

## Вход

- `moments/<stem>-moments.json`
- `transcript.json`
- `clip-scores.json`
- `editor-review.json`

## Действия

1. Оценить каждый клип по `shareability`, `comment_trigger`, `curiosity_gap`, `save_value`.
2. Можно запустить draft-инструмент:

```bash
cd scripts
python virality_review.py "../videoshorts-memory/moments/<stem>-moments.json" \
  "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  --scores "../videoshorts-memory/moments/clip-scores.json" \
  --editor-review "../videoshorts-memory/moments/editor-review.json" \
  -o "../videoshorts-memory/moments/virality-review.json"
```

3. В Agent mode вручную поднять/снизить оценки только с объяснением. Если `virality_score` ниже threshold — `status=REJECT` и причина обязательна.
4. Низкая вирусность — retry-plan или open incident, если клип не заменён.

## Выход

`videoshorts-memory/moments/virality-review.json`.

Fragment `videoshorts-memory/fragments/virality-critic.md` с `incident_report`.
