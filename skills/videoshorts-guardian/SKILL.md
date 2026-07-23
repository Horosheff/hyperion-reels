---
name: videoshorts-guardian
description: Guardian v2 QA + post-render approve — один финальный gate перед packager.
---

# VideoShorts Guardian v2 (+ post-render)

## Роль

Технический QA **и** post-render approve. Отдельный Task `post-render-reviewer` в slim-пайплайне **не вызывается**.

## Вход

- `output/clips/<stem>/` (финальные `clip_XX.mp4` после burn, либо `_cropped` если без субтитров)
- `audio-metrics.json`, `clip-decisions.json`, scores/editor/virality, refined-moments, cleanup-plan

## Действия

1. Pitfalls + QA:

```bash
cd scripts
$env:VIDEOSHORTS_AGENT_MODE="1"
# --min/--max ОБЯЗАТЕЛЬНО из brief (00-brief.md / run-request settings), не хардкод 30/60
python qa_clips.py "../videoshorts-memory/output/clips/<stem>" --min <brief.min_sec> --max <brief.max_sec> --require-agent-decisions
```

Проверки: ffprobe, duration в диапазоне brief (±5 с допуск), 9:16, audio, safe-zone, agent decisions, нет «все ~45s / no cleanup / no evidence». При brief `max_sec=90` клип 70–90 с — **PASS**, не fail.

2. По результатам QA + ffprobe/manifest **сам Write** `post-render-review.json`:

```json
{
  "schema_version": 1,
  "decision_source": "agent",
  "authored_by": "videoshorts-guardian",
  "clips": [
    {
      "index": 1,
      "approve": true,
      "rerender_reason": null,
      "subtitle_issue": false,
      "hook_failed": false,
      "audio_issue": false,
      "boundary_issue": false
    }
  ],
  "summary": { "approved": 1, "rejected": 0 }
}
```

`approve=false` → open incident / retry-plan.

3. Validate post-render:

```bash
cd scripts
python validate_agent_artifacts.py post-render-review "../videoshorts-memory/output/clips/<stem>/post-render-review.json"
```

## Выход

`qa-report.json`, `safe-zone-report.json`, `audio-qa-report.json`, `post-render-review.json`, обновлённый `latest-results.json` + fragment:

```text
=== VIDEOSHORTS-GUARDIAN ===
status: ✅ PASS | ❌ FAIL
passed: N/M
post_render_approved: N
incident_report: none
```
