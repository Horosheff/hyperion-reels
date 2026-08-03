# VideoShorts Subtitle Writer



Порт `shorts_service/backend/app/subtitle_engine.py`.



## Команда



```bash

cd scripts

# После boundary-refiner / cutter — ВСЕГДА refined-moments.json (не stem-moments)
python write_subtitles.py ../videoshorts-memory/transcripts/<stem>/transcript.json \

  ../videoshorts-memory/moments/refined-moments.json \

  -o ../videoshorts-memory/output/clips/<stem>/ \

  -t mrbeast --format both

# После retry / частичного re-cut — только затронутые индексы (остальные ASS/SRT + manifest preserve)
python write_subtitles.py ../videoshorts-memory/transcripts/<stem>/transcript.json \
  ../videoshorts-memory/moments/refined-moments.json \
  -o ../videoshorts-memory/output/clips/<stem>/ \
  -t mrbeast --format both --only-indexes 1,2,3,5,8,9,10

```



`write_subtitles.py` **предпочитает** `moments/refined-moments.json`, если он есть рядом с переданным `<stem>-moments.json` или если передан каталог `moments/`. Stem-moments после refiner устаревают: remap по старым start/end ломает таймлайн субтитров (INC-20260725-2038).

`--only-indexes` — частичная регенерация после re-cut (INC-20260725-2100): не затирает субтитры APPROVE-клипов.

## Hook-заголовок (заставка)

По умолчанию включён (`VIDEOSHORTS_HOOK_TITLE=1`, `--no-hook-title` выключает):
первые ~3 сек (`VIDEOSHORTS_HOOK_TITLE_DURATION`) поверх видео pop-in заставка
из поля `hook` момента — CAPS, ≤6 слов, ≤3 строк, **все слова на жёлтых плашках**
(стиль `HookKey` в ASS, per-line `\pos` внутри safe zone). Текст режется
`_hook_clean_words`/`_hook_wrap` в `subtitle_engine.py` — заставка не обязана быть
дословной, лишние слова отбрасываются.

**Pop SFX**: при вшивании (`burn_subtitles.py`) на каждое слово заставки миксуется
короткий pop-звук (sine 900 Гц, exp-затухание 85 мс) с задержкой по стаггеру слов
(`HOOK_WORD_STAGGER = 0.16` сек). Выключается `VIDEOSHORTS_HOOK_SFX=0`.

## Safe zone (UI платформ)

`subtitle_engine` принудительно поднимает MarginV/L/R до safe area Shorts/Reels/TikTok
(низ ~19.5% высоты — название/описание, право ~18% ширины — колонка лайков,
верх ~10.5%, лево ~5%). Замеры: `scripts/safe_zones.py`, отключение — `VIDEOSHORTS_SAFE_ZONE=0`.
Не занижать отступы шаблонов вручную: Guardian (`qa_clips.py`) помечает
`subtitle_margin_*_in_unsafe_zone` и кладёт issue в qa-report.



## Требования



- `transcript.json` с `words` или `_words` (word timestamps от transcriber).

- После cutter: `clip_XX_cropped.mp4` в output dir.
- При уменьшении keep (10→7) скрипт **удаляет** stale `clip_XX.ass/.srt` вне текущего списка и переписывает `subtitles-manifest.json`.



## Brief (обязательно)

Читай `videoshorts-memory/00-brief.md` и `run-request.json` → `settings`:

- `subtitle_template` / `template` — `-t mrbeast|hormozi|minimal|neon|fire`
- `emojiSubtitles: true` → добавь `--emoji`
- `word_timestamps: false` → можно `--no-karaoke` (fallback SRT)
- `quality_preset` — для согласованности с рендером

## Шаблоны



`mrbeast`, `hormozi`, `minimal`, `neon`, `fire` — см. `scripts/subtitle_engine.py`.

Custom JSON как в `shorts_service`: `--template-json path/to/template.json`.

Дополнительно:

- `--emoji` — локальный graceful mode для emoji subtitles без KIE/Gemini ключей.

- `--hook-style --hook-scale 1.3` — первое слово каждой ASS-строки крупнее.

- `--no-karaoke` — fallback на SRT, если word timestamps не нужны.



## Выход



- `subtitles/clip_XX.ass` (karaoke)

- `subtitles/clip_XX.srt` (fallback / both с `--format both`)

- `subtitles-manifest.json`



## incident_report



Обязателен.
