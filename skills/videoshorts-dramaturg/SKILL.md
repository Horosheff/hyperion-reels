---
name: videoshorts-dramaturg
description: Проверяет драматургию клипа: setup -> tension -> insight/result -> clean ending.
---

# VideoShorts Dramaturg

## Вход

- `refined-moments.json`
- `transcript.json`
- `editor-review.json`
- `virality-review.json`

## Действия

1. Проверить структуру каждого клипа: `setup -> tension -> insight/result -> clean ending`.
2. Можно запустить draft-инструмент:

```bash
cd scripts
python dramaturgy_report.py "../videoshorts-memory/moments/refined-moments.json" \
  "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  --editor-review "../videoshorts-memory/moments/editor-review.json" \
  --virality-review "../videoshorts-memory/moments/virality-review.json" \
  -o "../videoshorts-memory/moments/dramaturgy-report.json"
```

3. В Agent mode вручную подтвердить `setup`, `tension`, `insight_or_result`, `clean_ending`.
   Draft `has_payoff()` ловит RU Q&A **и** procedural closers («по триггеру», «идём проверять», установка/Extensions) — ложный `weak_insight_or_result` на таких хвостах перепроверять, не авто-REJECT.
4. Если дуга мысли разваливается, вернуть на boundary-refiner/editor, не отдавать cutter.

## Выход

`videoshorts-memory/moments/dramaturgy-report.json`.

Fragment `videoshorts-memory/fragments/dramaturg.md` с `incident_report`.
