# VideoShorts Subtitle Burner

Порт `shorts_service/backend/app/pipeline.py::_burn_subtitles`.

## Команда

```bash
cd scripts
$env:VIDEOSHORTS_AGENT_MODE="1"
python burn_subtitles.py ../videoshorts-memory/output/clips/<stem>/ `
  --moments ../videoshorts-memory/moments/<stem>-moments.json `
  --transcript ../videoshorts-memory/transcripts/<stem>/transcript.json `
  --quality-preset release
```

Читает `clip_XX_cropped.mp4` + `subtitles/clip_XX.ass` → пишет `clip_XX.mp4` **одним encode pass**.

Субтитры + optional zoom/progress собираются в один `-vf` (без повторных перекодирований).

Фильтрует cropped по keep из `subtitles-manifest.json` / `manifest.json` / `--moments` — не глобит stale `clip_08+` после уменьшения keep.

Опциональные эффекты:

- `--progress-bar --progress-position bottom` — progress bar в том же pass
- `--zoom-punch` — один punch-in по первому trigger word (`!`, «важно», «шок», `wow` и т.п.)

Quality presets: `release` (1080p) / `draft` (720p).

## Windows

ASS/SRT копируются во временный ASCII-путь перед burn (кириллица в path ломает `ass=` фильтр).

Fragment `videoshorts-memory/fragments/subtitle-burner.md` с `incident_report`.
