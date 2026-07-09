# VideoShorts — типичные сбои пайплайна



## Whisper / Windows



- **0xC0000409 при teardown:** worker завершается `os._exit(0)`; использовать Py3.10 из `shorts_service/backend/.venv310`.

- **CUDA не видит cuDNN:** `_prepend_nvidia_wheel_bins_to_path()` — nvidia/*/bin в PATH.

- **Пустая транскрипция на длинном вебинаре:** проверить VAD coverage в логе; `beam_size=1` быстрее, для качества — 5.



## Субтитры



- **Нет karaoke ASS:** включить `VIDEOSHORTS_WHISPER_WORD_TIMESTAMPS=1` и перезапустить transcriber.

- **Burn failed на Windows с кириллицей в пути:** burn_subtitles копирует `.ass/.srt` во временный путь и экранирует `:` в FFmpeg filter path. Не передавать сырой Windows-путь в `ass=`/`subtitles=` вручную.

- **Путаница clip_XX vs clip_XX_cropped:** cutter пишет `_cropped`; burner → финальный `clip_XX.mp4`; QA смотрит финальные.

- **Packager взял клип без субтитров:** `publish-manifest.json` должен указывать `burned: true`, если есть `clip_XX.mp4`. Fallback на `_cropped` допустим только при `--no-burn`.

- **Custom template не применился:** использовать `--template-json path\template.json` или `VIDEOSHORTS_SUBTITLES_TEMPLATE_JSON`; JSON поддерживает camelCase поля из `shorts_service` (`fontSize`, `primaryColor`, `wordsPerLine`).

- **Emoji требуют ключ:** в оригинальном `shorts_service` emoji через KIE/Gemini. В плагине `--emoji-subtitles` работает локально rule-based; платный API не обязателен.



## Моменты



- **Слишком мало клипов:** видео короче `clips × min_sec`; sanitizer в shorts_service урезает count.

- **basic vs advanced:** `--basic` = только webinar_cutter hooks; default = `clip_selector` из shorts_service.

- **ClipSelector без words → все ~45s sliding window:** `select_clips_advanced` обязан получать top-level `words` из `transcript.json` через `words_from_transcript_json` → `segments_to_selector_dicts(..., words=)` (кладёт в `segments[0]["_words"]`). Без этого `find_sentence_boundaries` = 0 и кандидаты фиксируются около mid-range. В логе ждать `words_for_selector=N` (N>0) и variable durations, не 10×~45s.

- **Алгоритм не должен быть финальным редактором:** `find_moments.py`/`clip_selector` — только генератор кандидатов. Финальный `moments.json` утверждает `videoshorts-moment-finder` по транскрипту: законченная микротема, понятный вход, payoff/вывод, естественная длительность 30-60. Если все клипы снова 43-48 сек, значит агент принял midpoint-window вместо редакторского выбора.

- **Пунктуация не равна завершённой теме:** хвосты `Второе.`, `Первое.`, `Дальше.`, `Сейчас объясню`, `Сейчас покажу`, `Так.` не являются payoff. Такой клип надо расширить/сдвинуть или заменить до cutter.

- **Scorekeeper не автор смысла:** `weak_hook` от regex — повод для редакторской проверки, а не автоматическое уничтожение хорошей завершённой Q&A-микротемы. Жёстко блокируют `incomplete_thought`, `too_short`, `too_long`, обрывки начала/конца.



## Рендер



- **Нет лица в кадре:** fallback center crop на bottom 70%.

- **FFmpeg not found:** установить и добавить в PATH.

- **Post-burn effects сломали клип:** `--progress-bar` и `--zoom-punch` опциональны. Если эффект не применился, должен остаться базовый burned MP4.



## Handoff



- Параллельные субагенты не пишут в handoff одновременно — fragments в `videoshorts-memory/fragments/`.

- **Ложный OPEN_INCIDENTS:** (1) regex `incident_report:\s*(?!none\b).+` из‑за backtracking матчит `none`; (2) упоминание `incident_report:` внутри prose durable_fix тоже триггерит. В `scripts/incident_queue.py` считать только field-строки `(?m)^(?:\s*[-*]\s*)?incident_report:\s*(\S+)` и value != `none`; `status: open` — только целая строка.



## Не тестировалось автоматически



- Полный Whisper на видео >1 GB зависит от локального железа и модели.

- YouTube download (только в shorts_service backend, не в плагине CLI).


