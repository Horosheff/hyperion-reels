# VideoShorts Agent Pipeline



```

HTML bridge start: `.\open-videoshorts-ui.ps1` → `http://127.0.0.1:8765/`  
HTML bridge results: `http://127.0.0.1:8765/results`  

UI protocol: стартовая HTML-панель автоматически запускает system profiler, даёт кнопку «Добавить файл локально» и «OK — передать Cursor Director». Локальный Python bridge принимает файл через `localhost`, сохраняет его в `videoshorts-memory/input/`, пишет brief/run-request и в режиме по умолчанию ставит `READY_FOR_AGENT` без запуска `run_pipeline.py`. После этого Cursor Director запускает Task-цепочку ниже. HTML/bridge — только заявка и просмотр результата; агенты принимают решения, а scripts являются их инструментами. Финальная HTML-панель опирается на `videoshorts-memory/output/latest-results.json`, который обновляют `videoshorts-guardian`, `videoshorts-metadata-writer` и `videoshorts-packager`.

Fallback: `runMode=local` / «Диагностика: локальный backend без субагентов» запускает `scripts/run_pipeline.py` напрямую только для локальных тестов. Это не агентный режим: он может создать `clip-decisions.json` как `local_heuristic_draft`, но это не решение LLM-субагента.

Intake (brief)

    ↓

videoshorts-system-profiler → system-profile.json, recommended Whisper/device/render

    ↓

videoshorts-intake          → video in input/, deps OK

    ↓

videoshorts-transcriber     → transcript.json, transcript.srt, audio.wav, words[]

    ↓

videoshorts-cleanup-planner → cleanup-plan.json, filler-removal-plan.json (plan-only)

    ↓

videoshorts-candidate-generator → candidate-moments.json (30-80 candidates: reason, hook type, pain, title, why_not_cut_yet)

    ↓

videoshorts-moment-finder   → moments.json (semantic excerpts, variable duration, boundary evidence)

    ↓

videoshorts-scorekeeper     → clip-scores.json (hook/virality/quality/pacing/completeness)

    ↓

videoshorts-editor          → editor-review.json (keep/reject, context, too_slow, no_payoff, duplicate_theme)

    ↓

videoshorts-virality-critic → virality-review.json (shareability/comment_trigger/curiosity_gap/save_value)

    ↓

videoshorts-boundary-refiner → refined-moments.json (segment/word/silence/filler snap + finished-thought gate)

    ↓

videoshorts-dramaturg       → dramaturgy-report.json (setup -> tension -> insight/result -> clean ending)

    ↓

videoshorts-montage-planner → montage-plan.json (jump cuts, silence_remove, glue_notes, zoom_punch, do_not_cut_before/after)

    ↓

videoshorts-layout-planner  → P1 stub/docs (safe-zone/layout strategy; optional)

    ↓

clip-decisions              → clip-decisions.json (why chosen, hook, viral hypothesis, thought boundaries, cleanup)

    ↓

videoshorts-cutter          → clip_XX_cropped.mp4, manifest.json

    ↓

videoshorts-audio-polisher  → audio-metrics.json, audio-polish-manifest.json

    ↓

videoshorts-broll (when enabled) → GPT Image 2 → Grok Imagine Video → clip_XX_broll.mp4

    ↓

videoshorts-subtitle-writer → subtitles/clip_XX.ass|.srt (custom JSON templates, hook-style, optional emoji)

    ↓

videoshorts-subtitle-burner → clip_XX.mp4 (burned + optional progress/zoom)

    ↓

videoshorts-guardian        → Guardian v2: qa-report.json, safe-zone-report.json, audio-qa-report.json

    ↓

videoshorts-post-render-reviewer → post-render-review.json (approve/rerender_reason/subtitle/hook/audio/boundary)

    ↓

videoshorts-metadata-writer → metadata-manifest.json, clip_XX.metadata.json|md

    ↓

videoshorts-thumbnail-writer → P1 docs (cover/thumbnail package; optional)

    ↓

videoshorts-packager        → <stem>-publish/ + final MP4 + sidecar subs

    ↓

videoshorts-fixic           → auto if pipeline-fix-queue.md/fragments contain open incidents

```



Handoff: `.cursor/videoshorts-handoff.md`  

Memory: `videoshorts-memory/`  

Архитектура: `shared/knowledge-base.md`

Fixic gate: `python scripts/incident_queue.py --project-root .` возвращает `OPEN_INCIDENTS=1` и код `2`, если нужно запускать `videoshorts-fixic`.

## P0 Artifact Contract

- `cleanup-plan.json` и `filler-removal-plan.json` — только план удаления/trim, без изменения `transcript.json`.
- `candidate-moments.json` — 30-80 кандидатов с `candidate_reason`, `hook_type`, `audience_pain`, `possible_title`, `why_not_cut_yet`. Это сырьё, не вход cutter.
- `clip-scores.json` — оценки `hook_score`, `virality_score`, `quality_score`, `pacing_score`, `completeness_score`, `reject_reason`.
- `editor-review.json` — редакторское `keep/reject`, `editor_notes`, `needs_context`, `too_slow`, `no_payoff`, `duplicate_theme`.
- `virality-review.json` — `shareability`, `comment_trigger`, `curiosity_gap`, `save_value` и `status`.
- `refined-moments.json` — единственный вход для cutter/subtitles/metadata после boundary-refiner; длительность остаётся переменной в диапазоне brief, клипы без законченной мысли уходят в `rejected_clips[]`.
- `dramaturgy-report.json` — структура `setup -> tension -> insight/result -> clean ending`.
- `montage-plan.json` — монтажное ТЗ: `jump_cuts`, `silence_remove`, `glue_notes`, `zoom_punch`, `do_not_cut_before/after`.
- `clip-decisions.json` — обязательный агентный артефакт: `selected_by_agent`, `why_this_moment`, `hook_assessment`, `viral_hypothesis`, `thought_start_evidence`, `thought_end_evidence`, `cleanup_applied`, `silence_removed`, `fillers_removed`, `glue_or_transition_notes`, `cut_instruction`, `reject_if`, `confidence`, `agent_notes`.
- `audio-metrics.json` и `audio-polish-manifest.json` — метрики и optional polished copies; оригинальные MP4 не заменяются по умолчанию.
- `safe-zone-report.json`, `audio-qa-report.json`, `qa-report.json` — Guardian v2 gate. При FAIL пишется open incident.
- `post-render-review.json` — post-render gate: `approve`, `rerender_reason`, `subtitle_issue`, `hook_failed`, `audio_issue`, `boundary_issue`.
- `run-state.json`, `retry-plan.json` — минимальный retry/cache каркас для local diagnostic fallback; Agent-режим всё равно управляется Task-цепочкой.
- `latest-results.json` агрегирует старые и новые артефакты без чтения MP4 в память, включая per-clip review loop, decision evidence и cleanup fields.

## Incident Gate

Если после run видны алгоритмические 45s clips, `no cleanup applied`, `no decision evidence`, `editor_rejected`, `virality_below_threshold` или `post_render_rejected`, это open incident/retry для `videoshorts-fixic`. В Agent mode нельзя закрывать финал только на основании local fallback JSON.


