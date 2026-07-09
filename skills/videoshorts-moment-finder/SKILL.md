---
name: videoshorts-moment-finder
description: Выбор лучших смысловых excerpts для Shorts по транскрипту — variable duration, semantic boundaries, hook/payoff evidence.
---

# VideoShorts Moment Finder

## Вход

- `transcript.json` из шага transcriber
- brief: clip_count, min_sec, max_sec

## Действия

1. Прочитать pitfalls
2. Сначала работать как **редактор смысловых Shorts**, а не как кнопка запуска алгоритма:
   - алгоритм (`find_moments.py` / `clip_selector`) даёт только черновые кандидаты;
   - финальный выбор делает агент по транскрипту и контексту;
   - если алгоритм выбрал незавершённый фрагмент или однотипные окна около 45 сек — агент обязан пересобрать моменты вручную;
   - лучше честно выбрать меньше клипов, чем добить `clip_count` мусором.

3. Черновой запуск кандидатов:

```bash
cd scripts
python find_moments.py "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  -o "../videoshorts-memory/moments/<stem>-moments.json" \
  -c <clip_count> --min <min_sec> --max <max_sec>
```

4. Алгоритм по умолчанию — **`clip_selector.select_best_clips`** из `shorts_service` (hook + emotion + coherence + webinar value), затем обязательный semantic boundary enrichment по transcript segment edges.
   - Fallback: `python find_moments.py ... --basic` — только webinar_cutter hooks
   - **Обязательно:** `find_moments.py` передаёт `words=words_from_transcript_json(data)` в `select_clips_advanced` (см. `videoshorts_core.segments_to_selector_dicts`). Без words ClipSelector не видит sentence boundaries → все кандидаты ~45s sliding window. В stdout ждать `words_for_selector=N` с N>0.

5. Не выбирать «10 клипов по 45 секунд» как самоцель. Длительность должна быть переменной в пределах brief: 31, 36, 43, 52, 58 сек — нормально, если есть законченная мысль. Если все клипы ≈ mid-range (±3s) при наличии `words[]` в transcript — регрессия: алгоритм снова рулит вместо редактора.

6. Проверить, что каждый клип содержит:
   - `semantic_boundary_evidence.why_start`
   - `semantic_boundary_evidence.why_end`
   - `hook`
   - `payoff_ending`
   - `transcript_excerpt`
   - `semantic_boundary_evidence.variable_duration`
   - `editorial_rationale`
   - `duration_reason`

7. Создать/обновить агентное решение:

```bash
cd scripts
python write_agent_decisions.py "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  "../videoshorts-memory/moments/<stem>-moments.json" \
  --cleanup-plan "../videoshorts-memory/transcripts/<stem>/cleanup-plan.json" \
  -o "../videoshorts-memory/moments/clip-decisions.json"
```

Это только draft. В Agent mode ты обязан открыть `clip-decisions.json` и редакторски заполнить/подтвердить по каждому выбранному клипу:
`selected_by_agent=true`, `why_this_moment`, `hook_assessment`, `viral_hypothesis`, `thought_start_evidence`, `thought_end_evidence`, `reject_if`, `confidence`, `agent_notes`.
Если не можешь объяснить, почему фрагмент цепляет и где мысль закончилась, клип не проходит.

7. Запрещённые границы:
   - старт с обрывка: «у кого нет», «нейросетью, то все», «если вылезает», «и вот», «так вот» без контекста;
   - конец, который открывает следующий пункт: «Второе.», «Первое.», «Дальше.», «Сейчас объясню», «Сейчас покажу», «Так.»;
   - фрагмент без ответа/вывода/payoff, даже если там есть вопросительный знак или формальная точка.

8. После скоринга:
   - `scorekeeper` — gate рисков, но не автор смыслового выбора;
   - если reject только из-за regex `weak_hook`, агент должен перепроверить текст редакторски, а не автоматически выбрасывать хорошую завершённую микротему;
   - если reject из-за `incomplete_thought`, `too_short`, `too_long` или обрывка границы — исправить таймкоды до cutter.

## Выход

`videoshorts-memory/moments/<stem>-moments.json`:

```json
{
  "clips": [{
    "start": 120.5,
    "end": 163.7,
    "score": 72,
    "reason": "curiosity_gap, optimal_hook_length",
    "hook": "Вот почему этот подход работает",
    "payoff_ending": "Так ролик заканчивается готовым выводом.",
    "transcript_excerpt": "...",
    "semantic_boundary_evidence": {
      "why_start": "Начало поставлено после паузы...",
      "why_end": "Конец поставлен на явном пунктуационном завершении...",
      "variable_duration": 43.2
    }
  }],
  "count": 10
}
```

`videoshorts-memory/moments/clip-decisions.json` — агентный decision artifact. В Agent mode это не должен быть чистый `local_heuristic_draft`: субагент подтверждает или переписывает решения.

Fragment `videoshorts-memory/fragments/moment-finder.md` с `incident_report`.

## Критерии качества

- score ≥ 40 — конкурентный хук (порог 2026)
- длительность после snap: min_sec ≤ duration ≤ max_sec (+5 сек допуск на QA)
- старт/конец объяснены по transcript evidence; нет обрыва на середине мысли
- редакторская завершённость важнее механического `optimal_hook_length`
