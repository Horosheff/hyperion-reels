---
name: videoshorts-post-render-reviewer
description: Проверяет готовые клипы после рендера и решает approve/rerender.
---

# VideoShorts Post Render Reviewer

## Вход

- `output/clips/<stem>/manifest.json`
- `output/clips/<stem>/qa-report.json`
- `moments/montage-plan.json`
- `moments/clip-scores.json`
- готовые `clip_XX.mp4` или `clip_XX_cropped.mp4`

## Действия

1. После render/burn посмотреть готовые клипы по доступным evidence: metadata, ffprobe, transcript, QA и монтажное ТЗ.
2. Можно запустить draft-инструмент:

```bash
cd scripts
python post_render_review.py "../videoshorts-memory/output/clips/<stem>" \
  --qa-report "../videoshorts-memory/output/clips/<stem>/qa-report.json" \
  --montage-plan "../videoshorts-memory/moments/montage-plan.json" \
  --scores "../videoshorts-memory/moments/clip-scores.json" \
  -o "../videoshorts-memory/output/clips/<stem>/post-render-review.json"
```

3. В Agent mode вручную подтвердить поля `approve`, `rerender_reason`, `subtitle_issue`, `hook_failed`, `audio_issue`, `boundary_issue`.
4. `approve=false` — обязательный retry-plan entry или open incident.

## Выход

`videoshorts-memory/output/clips/<stem>/post-render-review.json`.

Fragment `videoshorts-memory/fragments/post-render-reviewer.md` с `incident_report`.
