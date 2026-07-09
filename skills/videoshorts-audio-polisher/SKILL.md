---
name: videoshorts-audio-polisher
description: Аудио-метрики и безопасная loudnorm-полировка клипов.
---

# VideoShorts Audio Polisher

## Вход

- `videoshorts-memory/output/clips/<stem>/`

## Действия

```bash
cd scripts
python audio_polish.py "../videoshorts-memory/output/clips/<stem>"
```

По умолчанию скрипт пишет метрики и **не заменяет** MP4. Для безопасных копий можно использовать `--write-polished`, тогда создаются `*_polished.mp4`.

## Выход

- `audio-metrics.json`
- `audio-polish-manifest.json`

Guardian v2 читает эти файлы и пишет `audio-qa-report.json`.

Fragment `videoshorts-memory/fragments/audio-polisher.md` с `incident_report`.
