# VideoShorts — контракт автономной редакции

Этот контракт связывает смысловой отбор, чистку речи и фактический монтаж.
Субагент принимает решения; скрипты валидируют и исполняют их.

## Базовая политика

Режим по умолчанию — **умная чистка**:

- удаляй явную тишину, филлеры, false starts и повторы, когда это улучшает
  темп без потери смысла;
- сохраняй паузу, если это реакция, punchline, драматический beat или часть
  естественной интонации;
- не допускай искусственно рубленой речи и не удаляй фрагмент, если склейка
  будет заметнее, чем исходный мусор.

`cleanup-plan.json` — инвентарь найденного. `montage-plan.json` — единственный
исполняемый план. `manifest.json` cutter — единственное доказательство того, что
удаление реально произошло.

## Скорость без потери качества

Контур не должен раздувать прогон:

- не добавляй новые транскрибации, vision-проходы, LLM-вызовы или рендеры ради
  чистки — все решения строятся по уже готовым `transcript.json`, word timestamps
  и cleanup inventory;
- cleanup-planner и candidate-generator остаются параллельной волной;
- moment-finder, editor и boundary-refiner читают готовые артефакты предыдущего
  шага, а не пересчитывают кандидатный пул;
- финальный `editorial-bundle` — лёгкая JSON-проверка перед cutter, не ещё один
  редакторский агент;
- спорный item маркируй `review` и передавай дальше, а не запускай повторный
  анализ всего видео;
- cutter выполняет все одобренные интервалы в одном рендере клипа.

При конфликте приоритет такой: законченная мысль и естественное звучание →
проверяемая чистка → скорость. Нельзя запускать тяжёлый повторный проход, если
проблему можно описать `skip_reason` и выпустить клип без заметного дефекта.

## Владение решениями

| Решение | Владелец | Артефакт |
|---|---|---|
| Инвентарь тишины, филлеров, повторов, false starts | cleanup-planner | `cleanup-plan.json` |
| Пул разноплановых кандидатов | candidate-generator | `candidate-moments.json` |
| Семантический выбор, начальные cleanup risks | moment-finder | `<stem>-moments.json` |
| Финальный keep/reject, тема-дубликаты | editor | `clip-scores.json`, `editor-review.json`, `virality-review.json` |
| Границы, склейки и исполняемый монтаж | boundary-refiner | `refined-moments.json`, `clip-decisions.json`, `montage-plan.json` |
| Физическое вырезание | cutter | `manifest.json` |

## Единая модель cleanup

Каждый cleanup item должен иметь `type`, `start`, `end`, `action` и `reason`.

Допустимые `action`:

- `remove` — вырезать;
- `preserve` — явно сохранить;
- `review` — недостаточно уверенности, решение принимает следующий редактор.

| Тип | Стартовый статус | Когда разрешено `remove` |
|---|---|---|
| `silence_gap` | `remove` | Не является punch/reaction паузой и не ломает минимальную длину |
| `filler_word` | `remove` | Удаление не склеивает два разных смысла |
| `repeated_word` | `review` | Повтор явно случайный и склейка естественна |
| `false_start` | `review` | Начало перезапущено и чистая версия сохраняет мысль |
| `cross_segment_repeat` | `review` | Есть `glue_notes`, объясняющий цель и звучание склейки |

Moment-finder добавляет к выбранному моменту:

```json
{
  "cleanup_risks": [
    {
      "type": "false_start",
      "start": 12.4,
      "end": 14.1,
      "action": "remove",
      "reason": "Спикер перезапускает ту же фразу; вторая версия самостоятельна."
    }
  ],
  "do_not_cut": [
    {
      "start": 18.2,
      "end": 19.1,
      "reason": "punch_pause"
    }
  ]
}
```

Boundary-refiner обязан перенести все `remove` в `montage-plan.json` либо
задокументировать `preserve_reason` / `skip_reason`. Для repeat/false-start
удаление идёт в `jump_cuts` с `agent_reason` и непустым `glue_notes`.

## Дубликаты

Moment-finder делает мягкую дедупликацию и записывает сильные, но невыбранные
моменты в `rejected_notable[]` с причиной `duplicate`, `overlap` или
`same_argument`. Editor принимает финальное решение:

- два keep-клипа не должны пересекаться во времени больше чем на 3 секунды;
- каждый keep получает `theme_fingerprint` — одно предложение с главным тезисом;
- при `duplicate_theme: true` клип должен быть REJECT, кроме явного documented
  override с разными аудиториями/платформенными задачами.

## Gates

До cutter должны выполняться:

1. `finished_thought_gate=pass`;
2. editor согласованно оставил клип во всех трёх review-файлах;
3. `estimated_duration_after_cleanup >= brief.min_sec - 2`;
4. все cleanup `remove` либо попали в montage, либо имеют причину пропуска;
5. `montage-plan.status=READY_FOR_CUTTER`.

После cutter сравни `montage-plan.json` с `manifest.json`:

- `cleanup_planned` — авторизованные интервалы;
- `cleanup_rendered` — фактически применённые интервалы и секунды;
- расхождение допустимо только с `skip_reason` в manifest.
