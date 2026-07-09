# VideoShorts Subtitle Burner



Порт `shorts_service/backend/app/pipeline.py::_burn_subtitles`.



## Команда



```bash

cd scripts

python burn_subtitles.py ../videoshorts-memory/output/clips/<stem>/ \
  --moments ../videoshorts-memory/moments/<stem>-moments.json \
  --transcript ../videoshorts-memory/transcripts/<stem>/transcript.json

```



Читает `clip_XX_cropped.mp4` + `subtitles/clip_XX.ass` → пишет `clip_XX.mp4`.

Фильтрует cropped по keep из `subtitles-manifest.json` / `manifest.json` / `--moments` — не глобит stale `clip_08+` после уменьшения keep.

Опциональные эффекты:

- `--progress-bar --progress-position bottom` — progress bar после burn.

- `--zoom-punch` — один punch-in по первому trigger word (`!`, «важно», «шок», `wow` и т.п.).



## Windows



При Windows/не-ASCII путях субтитры копируются во temp и путь экранируется для `ass=`/`subtitles=` (как в оригинале).



## Env



- `VIDEOSHORTS_SUBTITLES_MAX_CHARS` — для SRT fallback



## incident_report



Обязателен.


