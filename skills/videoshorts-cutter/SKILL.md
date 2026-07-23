---
name: videoshorts-cutter
description: Рендер 9:16 (regular / webinar / podcast tracking / sales) + loudnorm в одном шаге.
---

# VideoShorts Cutter (+ audio)

## Роль

Нарезка 9:16 по `layout` из brief **и** loudnorm. Отдельный Task `audio-polisher` в slim-пайплайне **не вызывается**.

## Вход

- Исходное видео (brief)
- `refined-moments.json`, `montage-plan.json`, `clip-decisions.json`
- brief: `layout` (`regular`|`webinar`|`podcast`|`sales`, default `regular`), `quality_preset`, `loudnorm` (default true)

## Действия

1. Прочитать pitfalls. Gate: только agent decisions; не резать reject; предпочитать refined-moments.
2. Cut — **обязательно** передать `--layout` из brief:

```bash
cd scripts
$env:VIDEOSHORTS_AGENT_MODE="1"
python cut_clips.py "<video_path>" "../videoshorts-memory/moments/refined-moments.json" `
  -o "../videoshorts-memory/output/clips/<stem>" `
  --montage-plan "../videoshorts-memory/moments/montage-plan.json" `
  --layout regular `
  --quality-preset release `
  --require-agent-decisions
```

Подставьте `layout` из `00-brief.md` (`layout: ...`). Не хардкодьте webinar, если в brief `regular` / `podcast` / `sales`.

3. Сразу после успешного cut — audio polish (механика-скрипт ок):

```bash
cd scripts
python audio_polish.py "../videoshorts-memory/output/clips/<stem>" --apply-loudnorm --quality-preset release
```

Пишет `audio-metrics.json` + `audio-polish-manifest.json` в clips dir. Если brief `loudnorm: false` — только metrics (`--no-apply-loudnorm`).

4. Layouts:
   - `regular` / `sales` — один кадр 9:16, кроп по лицу
   - `webinar` — dual-screen 30/70 (экран / лицо)
   - `podcast` — tracking-камера по лицу
   - release 1080×1920

## Выход

```
output/clips/<stem>/
  clip_XX_cropped.mp4
  manifest.json
  audio-metrics.json
  audio-polish-manifest.json
```

Fragment `fragments/cutter.md` — статус cut + loudnorm summary + `incident_report`.
