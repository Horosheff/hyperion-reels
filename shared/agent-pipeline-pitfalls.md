# VideoShorts — типичные сбои пайплайна



## Whisper / Windows



- **0xC0000409 при teardown:** worker завершается `os._exit(0)`; использовать Py3.10 из `shorts_service/backend/.venv310`.

- **CUDA не видит cuDNN:** `_prepend_nvidia_wheel_bins_to_path()` — nvidia/*/bin в PATH.

- **Пустая транскрипция на длинном вебинаре:** проверить VAD coverage в логе; `beam_size=1` быстрее, для качества — 5.

- **`ValueError: 'auto' is not a valid language code`:** brief/UI `language=auto` нельзя передавать в faster-whisper как код. Нужен `language=None` (omit `--language` / unset `VIDEOSHORTS_WHISPER_LANGUAGE`). Worker/transcribe.py/run_pipeline нормализуют `auto`/`detect`/`none`/пустую строку → autodetect.



## Субтитры



- **Нет karaoke ASS:** включить `VIDEOSHORTS_WHISPER_WORD_TIMESTAMPS=1` и перезапустить transcriber.

- **Burn failed на Windows с кириллицей в пути:** burn_subtitles копирует `.ass/.srt` во временный путь и экранирует `:` в FFmpeg filter path. Не передавать сырой Windows-путь в `ass=`/`subtitles=` вручную.

- **Путаница clip_XX vs clip_XX_cropped:** cutter пишет `_cropped`; burner → финальный `clip_XX.mp4`; QA смотрит финальные.

- **Subtitle writer на stem-moments после refiner:** после boundary-refiner / cutter bounds живут в `moments/refined-moments.json`. `write_subtitles.py` предпочитает refined; skill default — refined path. Stem `<stem>-moments.json` даёт stale start/end → сломанный remap (8/10 клипов).

- **Частичный re-cut затирает чужие субтитры:** после retry используй `write_subtitles.py --only-indexes 1,2,5` — preserve ASS/SRT + manifest для остальных KEEP.

- **Packager stale `*-publish/`:** каталог переиспользуется; без prune остаются clip_02…N от прошлого прогона. `package_outputs.py` удаляет файлы вне текущего packaged set.

- **Packager взял клип без субтитров:** `publish-manifest.json` должен указывать `burned: true`, если есть `clip_XX.mp4`. Fallback на `_cropped` допустим только при `--no-burn`.

- **jump_cuts с `from`/`to` не резались:** cutter читает и `start`/`end`, и `from`/`to` (montage jump_cuts). Без alias silence/filler ок, а jump_cuts молча пропускались.

- **Custom template не применился:** использовать `--template-json path\template.json` или `VIDEOSHORTS_SUBTITLES_TEMPLATE_JSON`; JSON поддерживает camelCase поля из `shorts_service` (`fontSize`, `primaryColor`, `wordsPerLine`).

- **Emoji требуют ключ:** в оригинальном `shorts_service` emoji через KIE/Gemini. В плагине `--emoji-subtitles` работает локально rule-based; платный API не обязателен.



## Моменты



- **Слишком мало клипов:** видео короче `clips × min_sec`; sanitizer в shorts_service урезает count.

- **basic vs advanced:** `--basic` = только webinar_cutter hooks; default = `clip_selector` из shorts_service.

- **ClipSelector без words → все ~45s sliding window:** `select_clips_advanced` обязан получать top-level `words` из `transcript.json` через `words_from_transcript_json` → `segments_to_selector_dicts(..., words=)` (кладёт в `segments[0]["_words"]`). Без этого `find_sentence_boundaries` = 0 и кандидаты фиксируются около mid-range. В логе ждать `words_for_selector=N` (N>0) и variable durations, не 10×~45s.

- **Алгоритм не должен быть финальным редактором:** `find_moments.py`/`clip_selector` — только генератор кандидатов. Финальный `moments.json` утверждает `videoshorts-moment-finder` по транскрипту: законченная микротема, понятный вход, payoff/вывод, длительность **строго из brief `min_sec`–`max_sec`** (не хардкод 30–60). Если brief `30–90`, а все клипы снова 43–55 сек или все кандидаты одной длины (например 75×N) — агент игнорирует Duration policy: нужен spread short/mid/long и long-окна до `max_sec`.

- **Guardian QA min/max:** `qa_clips.py --min/--max` брать из brief. Хардкод `--max 60` при brief `max_sec=90` ложно валит длинные клипы.

- **Raw window ≥ min_sec, финал короче:** jump cuts / silence_remove укорачивают MP4. Boundary + montage обязаны гейтить `estimated_duration_after_cleanup` (≥ `brief.min_sec − 2`), не только raw `duration`. Иначе Guardian валит 7/10 «out of range». `validate_agent_artifacts` refined-moments / montage-plan проверяет поле; heuristic `refine_boundaries` / `montage_plan` expand или REJECT/REVIEW.

- **Пунктуация не равна завершённой теме:** хвосты `Второе.`, `Первое.`, `Дальше.`, `Сейчас объясню`, `Сейчас покажу`, `Так.` не являются payoff. Такой клип надо расширить/сдвинуть или заменить до cutter.

- **Scorekeeper не автор смысла:** `weak_hook` от regex — повод для редакторской проверки, а не автоматическое уничтожение хорошей завершённой Q&A-микротемы. Жёстко блокируют `incomplete_thought`, `too_short`, `too_long`, обрывки начала/конца.



## Рендер



- **Нет лица в кадре:** fallback center crop на bottom 70%.

- **FFmpeg not found:** установить и добавить в PATH.

- **Post-burn effects сломали клип:** `--progress-bar` и `--zoom-punch` опциональны. Если эффект не применился, должен остаться базовый burned MP4.



## Обложки (Kie)



- **`400 Image fetch failed` / 3× «обложка отвалилась»:** `brand-urls.json` на mayai.ru с ПК открывается, но **Kie cloud не может fetch**. Нужен File Upload API: локальный `avatar.png` + refs → `tempfile.redpandaai.co`. `prepare_covers` предпочитает local upload; remote URLs — только без локального avatar. Иначе silent `ffmpeg_fallback` и UI думает, что AI-обложка готова.



## Handoff / параллель



- Параллельные субагенты не пишут в handoff одновременно — fragments в `videoshorts-memory/fragments/`. Директор склеивает handoff после волны.

- **Строго последовательный run без волн:** замедляет пайплайн. Обязательны Wave C/H из slim orchestrator.

- **Вызов legacy Task в slim P0:** scorekeeper / virality / dramaturg / montage-planner / audio-polisher / post-render-reviewer — лишние минуты. Их работа в editor / boundary / cutter / guardian.

- **`jump_cuts` с `from`/`to` не резались:** montage-plan пишет jump cuts как `from`/`to`, а `cut_clips.py` раньше читал только `start`/`end` → silent skip всех jump cuts. Fix: принимать оба варианта ключей; после фикса перерезать KEEP.

- **Ложный OPEN_INCIDENTS:** (1) regex `incident_report:\s*(?!none\b).+` из‑за backtracking матчит `none`; (2) упоминание `incident_report:` внутри prose durable_fix тоже триггерит. В `scripts/incident_queue.py` считать только field-строки `(?m)^(?:\s*[-*]\s*)?incident_report:\s*(\S+)` и value != `none`; `status: open` — только целая строка.



## Metadata / Packager



- **`metadata-manifest.json` с `json`, но `markdown: null`:** агент забыл путь к `.metadata.md`. `package_outputs.py` раньше копировал только ключи из manifest → publish без md. Fix: metadata-writer всегда пишет `"markdown": "clip_XX.metadata.md"` + файл; packager делает fallback на convention рядом с `.json`; validate требует оба файла и ключ `markdown`.



## Не тестировалось автоматически



- Полный Whisper на видео >1 GB зависит от локального железа и модели.

- YouTube download (только в shorts_service backend, не в плагине CLI).


