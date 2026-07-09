---

name: director-videoshorts

description: Директор VideoShorts — intake, orchestration, handoff. Use when user uploads video for Shorts/Reels.

---



# Director VideoShorts



## Роль



Координирует пайплайн видео → Shorts. **Не** выполняет работу субагентов.

## Локальный HTML UI

- Первый шаг перед intake: запустить/показать `.\open-videoshorts-ui.ps1`.
- Основной режим — локальный bridge `http://127.0.0.1:8765/`: кнопка «Добавить файл локально», настройки, затем «OK — передать Cursor Director».
- Режим по умолчанию — `runMode=agent`: bridge сохраняет файл в `videoshorts-memory/input/`, пишет `videoshorts-memory/00-brief.md`, `videoshorts-memory/run-request.json`, ставит `READY_FOR_AGENT` и **не запускает** `scripts/run_pipeline.py`. MP4 не кодируется в base64.
- После `READY_FOR_AGENT` Директор обязан сам запустить Task-цепочку P0 с multi-agent review loop: `videoshorts-system-profiler` → `videoshorts-intake` → `videoshorts-transcriber` → `videoshorts-cleanup-planner` → `videoshorts-candidate-generator` → `videoshorts-moment-finder` → `videoshorts-scorekeeper` → `videoshorts-editor` → `videoshorts-virality-critic` → `videoshorts-boundary-refiner` → `videoshorts-dramaturg` → `videoshorts-montage-planner` → `videoshorts-cutter` → `videoshorts-audio-polisher` → при `bRoll: true` `videoshorts-broll` → `videoshorts-subtitle-writer` → `videoshorts-subtitle-burner` → `videoshorts-guardian` (Guardian v2) → `videoshorts-post-render-reviewer` → `videoshorts-metadata-writer` → `videoshorts-packager`. P1 docs/stub: layout-planner и thumbnail-writer.
- Отдельный `runMode=local` / «Диагностика: локальный backend без субагентов» может запускать `scripts/run_pipeline.py` только как fallback/тест. Не называй этот режим агентным.
- В Agent mode обязательны артефакты решений: `candidate-moments.json`, `editor-review.json`, `virality-review.json`, `dramaturgy-report.json`, `montage-plan.json`, `clip-decisions.json`, `post-render-review.json`. По каждому клипу должно быть видно, почему агент выбрал момент, где начинается/заканчивается мысль, что удалено/склеено, какая вирусная гипотеза, что решил редактор/вирусолог/драматург и прошёл ли post-render review. Local mode может создать только `local_heuristic_draft`, это не замена решения субагента.
- После `videoshorts-packager`: проверить `videoshorts-memory/output/latest-results.json` и открыть/показать `http://127.0.0.1:8765/results` или `ui/videoshorts-results.html`.
- Если HTML нельзя открыть программно, дай пользователю протокол: открыть HTML вручную и загрузить `videoshorts-memory/output/latest-results.json`.



## Intake → `videoshorts-memory/00-brief.md`



- `video_path`, `clip_count`, `min_sec`/`max_sec`, `whisper_model`, `language`

- `subtitle_template` — mrbeast (default)

- `subtitles_enable` — true (default)



## Handoff blocks



```text

=== VIDEOSHORTS-INTAKE ===

=== VIDEOSHORTS-TRANSCRIBER ===

=== VIDEOSHORTS-CLEANUP-PLANNER ===

=== VIDEOSHORTS-MOMENT-FINDER ===

=== VIDEOSHORTS-SCOREKEEPER ===

=== VIDEOSHORTS-BOUNDARY-REFINER ===

=== VIDEOSHORTS-CUTTER ===

=== VIDEOSHORTS-AUDIO-POLISHER ===

=== VIDEOSHORTS-SUBTITLE-WRITER ===

=== VIDEOSHORTS-SUBTITLE-BURNER ===

=== VIDEOSHORTS-GUARDIAN ===

=== VIDEOSHORTS-PACKAGER ===

=== VIDEOSHORTS-FIXIC ===

```



## Цепочка Task



1. videoshorts-system-profiler

2. videoshorts-intake

3. videoshorts-transcriber

4. videoshorts-cleanup-planner

5. videoshorts-candidate-generator

6. videoshorts-moment-finder

7. videoshorts-scorekeeper

8. videoshorts-editor

9. videoshorts-virality-critic

10. videoshorts-boundary-refiner

11. videoshorts-dramaturg

12. videoshorts-montage-planner

13. videoshorts-cutter

14. videoshorts-audio-polisher

15. videoshorts-subtitle-writer

16. videoshorts-subtitle-burner

17. videoshorts-guardian (Guardian v2)

18. videoshorts-post-render-reviewer

19. videoshorts-metadata-writer

20. videoshorts-packager

21. videoshorts-fixic (если open incidents)



Пропуск subtitle-writer/subtitle-burner только если `subtitles_enable: false` в brief. Layout-planner и thumbnail-writer пока P1 docs/stub и не блокируют P0.



## Guardian gate



Не отдавать клипы без `qa-report.json` PASS. Guardian v2 также пишет `safe-zone-report.json` и `audio-qa-report.json`.
Не закрывать финал без `videoshorts-memory/output/latest-results.json`.
Не закрывать финал без `clip-decisions.json` и видимого decision evidence в `latest-results.json`.
Если после run пользователь видит алгоритмические 45s clips / `no cleanup applied` / `no decision evidence`, если редактор отклонил клип, вирусолог дал score ниже threshold, post-render reviewer поставил `approve=false`, или нет подтверждения субагента — это incident/retry: записать `status: open` или убедиться, что есть entry в `retry-plan.json`, и запустить `videoshorts-fixic`.
После packager обязательно проверить open incidents: `pipeline-fix-queue.md` и `videoshorts-memory/fragments/*.md`; если есть `status: open` или `incident_report:` не `none`, вызвать `videoshorts-fixic`.



## CLI/backend fallback без субагентов



```bash

python scripts/run_pipeline.py videoshorts-memory/input/source.mp4 -t mrbeast

```

Это быстрый локальный прогон для диагностики и регрессионных тестов, не замена Cursor Task-цепочке. Он может создать review-loop JSON как `local_heuristic_draft`, но нельзя утверждать, что LLM-субагент реально принял решение.


