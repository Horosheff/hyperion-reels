---
name: videoshorts-candidate-generator
description: Выбирает 30-80 кандидатов из transcript и пишет candidate-moments.json.
---

# VideoShorts Candidate Generator

## Вход

- `videoshorts-memory/transcripts/<stem>/transcript.json`
- `videoshorts-memory/transcripts/<stem>/cleanup-plan.json` как контекст темпа/пауз

## Действия

1. Работать как агент отбора сырья: найти 30-80 потенциальных моментов, но **не** отдавать их cutter.
2. Можно запустить draft-инструмент:

```bash
cd scripts
python generate_candidates.py "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  -o "../videoshorts-memory/moments/candidate-moments.json" \
  --min 30 --max 60 --target 60
```

3. В Agent mode вручную проверить кандидатов и заполнить для каждого: `candidate_reason`, `hook_type`, `audience_pain`, `possible_title`, `why_not_cut_yet`.
4. Не называть local heuristic draft агентным решением.

## Выход

`videoshorts-memory/moments/candidate-moments.json` с 30-80 кандидатами.

Fragment `videoshorts-memory/fragments/candidate-generator.md` с `incident_report`.
