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
