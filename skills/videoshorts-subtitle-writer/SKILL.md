# VideoShorts Subtitle Writer



Порт `shorts_service/backend/app/subtitle_engine.py`.



## Команда



```bash

cd scripts

python write_subtitles.py ../videoshorts-memory/transcripts/<stem>/transcript.json \

  ../videoshorts-memory/moments/<stem>-moments.json \

  -o ../videoshorts-memory/output/clips/<stem>/ \

  -t mrbeast --format both

```



## Требования



- `transcript.json` с `words` или `_words` (word timestamps от transcriber).

- После cutter: `clip_XX_cropped.mp4` в output dir.
- При уменьшении keep (10→7) скрипт **удаляет** stale `clip_XX.ass/.srt` вне текущего списка и переписывает `subtitles-manifest.json`.



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


