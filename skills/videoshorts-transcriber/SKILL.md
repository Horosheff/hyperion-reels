---
name: videoshorts-transcriber
description: Транскрипция видео через faster-whisper. JSON + SRT с таймкодами.
---

# VideoShorts Transcriber

## Вход

- `videoshorts-memory/00-brief.md` — путь к видео, модель Whisper
- `.cursor/videoshorts-handoff.md`

## Действия

1. Прочитать `shared/agent-pipeline-pitfalls.md`
2. Скопировать/проверить видео в `videoshorts-memory/input/` если нужно
3. Запустить:

```bash
cd scripts
python transcribe.py "<video_path>" -o "../videoshorts-memory/transcripts/<stem>" -m <model>
```

4. Проверить артефакты:
   - `transcript.json` — segments + опционально `words[]` / `_words` (karaoke ASS)
   - `transcript.srt`
   - `audio.wav`

## Env / language

- `VIDEOSHORTS_WHISPER_WORD_TIMESTAMPS=1` (default) — word-level для субтитров
- `VIDEOSHORTS_WHISPER_LANGUAGE=ru` — только реальный ISO-код (`ru`, `en`, …)
- Brief / UI `language: auto` → **не** передавать `--language auto` и **не** ставить env в `auto`/`detect`/`none`
- Автоопределение = `language=None` в faster-whisper (omit `--language` / unset env)
- Worker нормализует `auto`/`detect`/пустую строку → `None` (не падает ValueError)

## Ошибки

При падении Whisper — записать INC в `pipeline-fix-queue.md`, `incident_report` со ссылкой.
