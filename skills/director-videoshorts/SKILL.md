---
name: director-videoshorts
description: Директор VideoShorts — slim orchestration, parallel waves, handoff. Use when user uploads video for Shorts/Reels.
---

# Director VideoShorts

## Роль

Координирует пайплайн видео → Shorts. **Не** выполняет работу субагентов.

## Локальный HTML UI

- `.\open-videoshorts-ui.ps1` → `http://127.0.0.1:8765/`
- После `READY_FOR_AGENT` — **slim P0** с параллельными волнами (см. `rules/videoshorts-orchestrator.mdc`).
- Не вызывать отдельными Task: scorekeeper, virality-critic, dramaturg, montage-planner, audio-polisher, post-render-reviewer.
- Profiler skip если UI уже дал `system_profile` ready.
- После packager — `latest-results.json` + Results UI.

## Slim цепочка Task

0. Write — сброс handoff  
1. **A** intake  
2. **B** transcriber  
3. **C ||** cleanup-planner \|\| candidate-generator  
4. **D** moment-finder  
5. **E** **editor** → `clip-scores` + `editor-review` + `virality-review`  
6. **F** **boundary-refiner** → refined + decisions + **montage-plan**  
7. **G** **cutter** → cut + **loudnorm** (`audio-metrics`)  
8. **H ||** subtitle-writer \|\| metadata-writer (broll до subtitle если нужен)  
9. **I** subtitle-burner  
10. **J** **guardian** → QA + **post-render-review**  
11. **K** packager → Results → fixic при open incidents  

Пропуск subtitle-writer/burner только если `subtitles_enable: false`.

## Guardian gate

Не отдавать клипы без QA PASS и `post-render-review` approve.  
Финал требует `clip-decisions.json` + decision evidence в `latest-results.json`.

## Decision contract

Субагенты пишут JSON сами (`decision_source=agent`). См. `shared/agent-decision-contract.md`.
