---
name: videoshorts-scorekeeper
description: Считает clip-scores.json по moments/transcript/cleanup-plan.
---

# VideoShorts Scorekeeper

## Вход

- `videoshorts-memory/moments/<stem>-moments.json`
- `videoshorts-memory/transcripts/<stem>/transcript.json`
- `videoshorts-memory/transcripts/<stem>/cleanup-plan.json`

## Действия

1. Оценивать как редактор Shorts, а не как формальную метрику. `score_clips.py` — инструмент первичного gate, но субагент обязан проверить:
   - не скучный ли фрагмент в первые 3 секунды;
   - есть ли самостоятельная мысль и payoff;
   - не начинается ли клип с контекстного обрывка;
   - не заканчивается ли он открытием следующего пункта;
   - не превращает ли cleanup клип в заметную склейку.

2. Запустить:

```bash
cd scripts
python score_clips.py "../videoshorts-memory/moments/<stem>-moments.json" \
  "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  --cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json" \
  -o "../videoshorts-memory/moments/clip-scores.json" \
  --min 30 --max 60
```

3. Для слабых/скучных/обрубленных клипов `reject_reason` обязателен. Нельзя оставлять PASS только потому, что длительность попала в 30–60 сек. Голый regex `weak_hook` на завершённой RU Q&A/mythbust/**live_proof**/procedural-микротеме — **не** авто-REJECT: перепроверить текст («О, сработало», install checklist). Жёстко режут `incomplete_thought`, `clipped_ending`, `contextless_start`, `boring_or_low_viral_potential`, `weak_hook_first_3s` (first 3s вода/реклама без punch).

4. Обновить `clip-decisions.json` после scoring:

```bash
cd scripts
python write_agent_decisions.py "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  "../videoshorts-memory/moments/<stem>-moments.json" \
  --cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json" \
  --scores "../videoshorts-memory/moments/clip-scores.json" \
  -o "../videoshorts-memory/moments/clip-decisions.json"
```

В Agent mode после запуска агент вручную подтверждает/правит `hook_assessment`, `viral_hypothesis`, `reject_if`, `confidence`; local fallback оставляет только heuristic draft.

## Выход

`clip-scores.json` с полями `hook_score`, `virality_score`, `quality_score`, `pacing_score`, `completeness_score`, `reject_reason`.

`clip-decisions.json` должен отражать риски scorekeeper по каждому клипу.

Fragment `videoshorts-memory/fragments/scorekeeper.md` с `incident_report`.
