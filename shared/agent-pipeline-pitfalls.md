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

- **Cleanup найден, но не вырезан:** `cleanup-plan.json` — только инвентарь. Реальные
  cuts появляются только в `montage-plan.json`, а доказательство — в
  `manifest.json.cleanup_applied`. Не называй overlap с cleanup-plan «удалённой
  паузой». Для `repeated_word` / `false_start` нужен явный `jump_cuts` с
  `agent_reason` и `glue_notes`; иначе они остаются review-only.

- **Агрессивная чистка ломает речь:** default — умная чистка: удалять явную тишину,
  филлеры, повторы и false starts, но сохранять punch/reaction паузы и естественную
  интонацию. Не режь «всё подряд» и не обходи `min_sec−2` gate ради темпа.

- **Filler попал в montage, но не применился:** cutter исполняет только
  `filler_remove.items` с `safe: true` (или с агентной авторизацией после фикса).
  Boundary-refiner обязан указывать `safe: true`, `reason` и проверить manifest.

- **Дубли клипов прошли в publish:** `duplicate_theme` — не декоративный флаг.
  Editor должен reject один из клипов при том же тезисе или temporal overlap >3 с,
  если нет documented override.

- **Пунктуация не равна завершённой теме:** хвосты `Второе.`, `Первое.`, `Дальше.`, `Сейчас объясню`, `Сейчас покажу`, `Так.` не являются payoff. Такой клип надо расширить/сдвинуть или заменить до cutter.

- **Scorekeeper не автор смысла:** `weak_hook` от regex — повод для редакторской проверки, а не автоматическое уничтожение хорошей завершённой Q&A-микротемы. Жёстко блокируют `incomplete_thought`, `too_short`, `too_long`, обрывки начала/конца.



## Рендер



- **Нет лица в кадре:** fallback center crop на bottom 70%.

- **FFmpeg not found:** установить и добавить в PATH.

- **loudnorm → possible_clipping (max ≈ −0.9 dB):** two-pass loudnorm (TP=-1.5) + AAC иногда оставляет sample peak выше −1.0 dB. Не one-off hand-fix одного клипа. `audio_polish.py` после loudnorm меряет volumedetect; при `max_volume > -1.0` применяет `alimiter` (ceiling ≈ TP) и пересчитывает метрики. Soft WARN без limiter — исторический INC-20260730-2319.

- **Post-burn effects сломали клип:** `--progress-bar` и `--zoom-punch` опциональны. Если эффект не применился, должен остаться базовый burned MP4.



## Обложки (Kie)



- **`400 Image fetch failed` / 3× «обложка отвалилась»:** `brand-urls.json` на mayai.ru с ПК открывается, но **Kie cloud не может fetch**. Нужен File Upload API: локальный `avatar.png` + refs → `tempfile.redpandaai.co`. `prepare_covers` / UI (`--mode kie --force-upload`) всегда заливают локальный brand; remote URLs alone запрещены как единственный путь. `ffmpeg_fallback` больше не маскирует ошибку как SUCCESS (нужен явный `--allow-ffmpeg-fallback`).



## Handoff / параллель



- Параллельные субагенты не пишут в handoff одновременно — fragments в `videoshorts-memory/fragments/`. Директор склеивает handoff после волны.

- **Строго последовательный run без волн:** замедляет пайплайн. Обязательны Wave C/H из slim orchestrator.

- **Вызов legacy Task в slim P0:** scorekeeper / virality / dramaturg / montage-planner / audio-polisher / post-render-reviewer — лишние минуты. Их работа в editor / boundary / cutter / guardian.

- **`jump_cuts` с `from`/`to` не резались:** montage-plan пишет jump cuts как `from`/`to`, а `cut_clips.py` раньше читал только `start`/`end` → silent skip всех jump cuts. Fix: принимать оба варианта ключей; после фикса перерезать KEEP.

- **VK две вкладки / «взлом»:** `_open_upload_popup` кликал «Добавить ролик», ловил popup; при сбое `expect_popup` кликал **ещё раз** → вторая вкладка cabinet. Антифрод VK это воспринимает плохо. Fix: same-tab `cabinet...?showUploader=1`, один клик max, закрытие лишних вкладок, humanize-паузы (`VK_HUMANIZE=1`).

- **RuTube: диалог «Сохранить часть изменений» / ранний уход:** (1) `_select_category` жал `Escape` → модалка upload схлопывалась в виджет «Загрузка видео», форма категории/обложки пропадала; (2) `_wait_processing_ready` считал `pct is None` = ready → Publish на середине «Загрузка N%» / когда «Обработка» на мгновение пропала с DOM. Fix в `rutube_client.py`: без Escape на форме; парсить и `Загрузка N%`, и `Обработка N%`; ready только после реального ≥100% (+ 2 стабильных тика); ждать после Publish; dialog handler dismiss leave-site; перед `close()` — `_wait_safe_to_leave`.

- **Instagram не стартует «вместе со всеми»:** в parallel `publish-platforms` 5 Chromium открывались в одной `--window-position` → IG оказывался под Дзен/VK; плюс 5× `list_monitors()` через PowerShell на старте. Fix: Instagram первым в порядке запуска; `VIDEOSHORTS_WINDOW_SLOT` cascade; кэш мониторов; IG `viewport=None`; лог `START instagram` в ui_server.

- **YouTube Studio Shorts:** `youtube_client.py` / `publish_youtube.py` / `youtube_login_save.py` + codegen. Cookies: `secrets/youtube_storage_state.json`. Results UI: YouTube в галочках по умолчанию; «Опубликовать (по галочкам)» шлёт YouTube в `/api/publish-platforms` **параллельно** с IG/TikTok/VK/RuTube/Дзен. Title-хештеги — клики по **«Рекомендуемые хештеги»** (не ручной `#` + autocomplete). Поле **Теги** — `type` + **Shift+Enter** (не смешивать с хештегами, не стирать через Ctrl+A). **Не** кликать `#checkbox-container` на Checks — это paid promotion / прямая реклама (ролики без рекламы). **Не** жать Escape на форме загрузки — закрывает модалку → черновик. Значок Shorts на части каналов только в приложении; после Publish пробуем `…/video/{id}/edit`. Обязателен клик «Поставить оценку».

- **Ложный OPEN_INCIDENTS:** (1) regex `incident_report:\s*(?!none\b).+` из‑за backtracking матчит `none`; (2) упоминание `incident_report:` внутри prose durable_fix тоже триггерит. В `scripts/incident_queue.py` считать только field-строки `(?m)^(?:\s*[-*]\s*)?incident_report:\s*(\S+)` и value != `none`; `status: open` — только целая строка.



## Metadata / Packager



- **`metadata-manifest.json` с `json`, но `markdown: null`:** агент забыл путь к `.metadata.md`. `package_outputs.py` раньше копировал только ключи из manifest → publish без md. Fix: metadata-writer всегда пишет `"markdown": "clip_XX.metadata.md"` + файл; packager делает fallback на convention рядом с `.json`; validate требует оба файла и ключ `markdown`.



## Не тестировалось автоматически



- Полный Whisper на видео >1 GB зависит от локального железа и модели.

- YouTube download (только в shorts_service backend, не в плагине CLI).


