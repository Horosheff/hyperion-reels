---
name: videoshorts-guardian
description: Guardian v2 QA готовых клипов — ffprobe, audio metrics, safe-zone/readability.
---

# VideoShorts Guardian v2

## Вход

- `videoshorts-memory/output/clips/<stem>/`
- `audio-metrics.json` от `videoshorts-audio-polisher`, если уже создан
- `clip-decisions.json`, `clip-scores.json`, `cleanup-plan.json`, `refined-moments.json`

## Действия

1. Прочитать pitfalls
2. Запустить:

```bash
cd scripts
$env:VIDEOSHORTS_AGENT_MODE="1"
python qa_clips.py "../videoshorts-memory/output/clips/<stem>" --min 30 --max 60 --require-agent-decisions
```

3. Проверки:
   - каждый `clip_*.mp4` читается ffprobe
   - duration в диапазоне min–max (+5 сек сверху)
   - height > width (вертикаль)
   - manifest.json согласован с файлами на диске
   - есть audio stream, а `audio-metrics.json` не содержит критичных предупреждений
   - loudnorm применён (или нет `audio_too_quiet`)
   - safe-zone/readability placeholder heuristics: вертикальный canvas, приемлемое разрешение, наличие sidecar/burn субтитров
   - есть `clip-decisions.json` и в Agent mode у клипов есть `selected_by_agent=true`
   - UI/JSON показывает `why_this_moment`, `thought_start_evidence`, `thought_end_evidence`, `viral_hypothesis`, `cleanup_applied`
   - нет симптомов «алгоритмических 45s clips»: все duration ≈ одинаковые, no cleanup applied, no decision evidence
   - `decision_source=local_heuristic_draft` в Agent mode = **FAIL**

4. Скрипт дополнительно пишет `safe-zone-report.json` и `audio-qa-report.json`.

5. При FAIL — `qa_clips.py` пишет open incident в `videoshorts-memory/pipeline-fix-queue.md`; перечислить issues для cutter/audio-polisher/fixic. После QA можно запустить `retry_plan.py`, чтобы получить `retry-plan.json`.

6. Если обнаружен отсутствующий/неподтверждённый decision evidence в Agent mode — это не просто WARN, а incident для `videoshorts-fixic`.

## Выход

`qa-report.json`, `safe-zone-report.json`, `audio-qa-report.json`, обновлённый `videoshorts-memory/output/latest-results.json` + fragment:

```text
=== VIDEOSHORTS-GUARDIAN ===
status: ✅ PASS | ❌ FAIL
passed: N/M
report: videoshorts-memory/output/clips/<stem>/qa-report.json
safe_zone_report: videoshorts-memory/output/clips/<stem>/safe-zone-report.json
audio_qa_report: videoshorts-memory/output/clips/<stem>/audio-qa-report.json
latest_results: videoshorts-memory/output/latest-results.json
incident_report: none
```

Директор не отдаёт клипы пользователю при FAIL без retry cutter. После run Директор проверяет queue/fragments и запускает `videoshorts-fixic`, если остался `status: open`.
