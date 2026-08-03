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

Опциональные эффекты (из brief / `settings`):

- `progressBar: true` → `--progress-bar --progress-position bottom`
- `zoomPunch: true` → `--zoom-punch`
- `quality_preset: draft|release` → `--quality-preset …`

Quality presets: `release` (1080p) / `draft` (720p).

## Hook SFX (pop-звук заставки)

Если в ASS есть события стиля `HookKey` (hook-заставка), burner миксует pop-звук
на каждое слово: sine 900 Гц / 90 мс с exp-затуханием, `adelay` по стаггеру
`HOOK_WORD_STAGGER = 0.16` сек из `subtitle_engine.py`, `amix` поверх оригинала
(аудио перекодируется в aac 192k вместо copy). Выключается `VIDEOSHORTS_HOOK_SFX=0`.
Число слов считается по `\fscx150`-маркерам в событиях `HookKey` (`count_hook_words`).

## Windows

ASS/SRT копируются во временный ASCII-путь перед burn (кириллица в path ломает `ass=` фильтр).

Fragment `videoshorts-memory/fragments/subtitle-burner.md` с `incident_report`.
