---
name: videoshorts-audio-polisher
description: Аудио-метрики и two-pass loudnorm в cropped/final клипы.
---

# VideoShorts Audio Polisher

## Вход

- `videoshorts-memory/output/clips/<stem>/`

## Действия

```bash
cd scripts
$env:VIDEOSHORTS_AGENT_MODE="1"
python audio_polish.py "../videoshorts-memory/output/clips/<stem>" --apply-loudnorm --quality-preset release
```

По умолчанию применяется **two-pass loudnorm** (I=-14 LUFS) **in-place** к cropped/final клипам. Видео копируется, аудио перекодируется в AAC.

Только метрики без изменения файлов:

```bash
python audio_polish.py "../videoshorts-memory/output/clips/<stem>" --metrics-only
```

## Выход

- `audio-metrics.json` (`loudnorm_applied: true/false`)
- `audio-polish-manifest.json`

Guardian v2 читает эти файлы и пишет `audio-qa-report.json`.

Fragment `videoshorts-memory/fragments/audio-polisher.md` с `incident_report`.
