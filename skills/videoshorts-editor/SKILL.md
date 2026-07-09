---
name: videoshorts-editor
description: Редакторское keep/reject ревью кандидатов и моментов.
---

# VideoShorts Editor

## Вход

- `candidate-moments.json`
- `moments/<stem>-moments.json`
- `transcript.json`
- `clip-scores.json` если уже есть

## Действия

1. Отбраковать слабые, контекстные, медленные, повторяющиеся и без payoff фрагменты.
2. Можно запустить draft-инструмент:

```bash
cd scripts
python editor_review.py "../videoshorts-memory/moments/<stem>-moments.json" \
  "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  --candidates "../videoshorts-memory/moments/candidate-moments.json" \
  -o "../videoshorts-memory/moments/editor-review.json"
```

3. В Agent mode вручную подтвердить поля `keep/reject`, `editor_notes`, `needs_context`, `too_slow`, `no_payoff`, `duplicate_theme`.
4. Любой `reject=true` — это причина для retry-plan или open incident, если клип всё равно дошёл до финала.

## Выход

`videoshorts-memory/moments/editor-review.json`.

Fragment `videoshorts-memory/fragments/editor.md` с `incident_report`.
