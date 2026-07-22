# VideoShorts Packager

Экспорт для публикации: финальные MP4 + **sidecar** ASS/SRT + metadata JSON/Markdown.

Важно:
- брать `clip_XX.mp4`, если burn уже создал финальный файл
- fallback на `clip_XX_cropped.mp4` только при `--no-burn`
- перед packager: `videoshorts-metadata-writer` + Guardian **PASS**
- в Agent mode: `VIDEOSHORTS_AGENT_MODE=1` и подтверждённые decisions

## Команда

```bash
cd scripts
$env:VIDEOSHORTS_AGENT_MODE="1"
python package_outputs.py ../videoshorts-memory/output/clips/<stem>/ --require-agent-decisions --require-qa-pass
```

Блокирует publish если:
- `qa-report.json` отсутствует или `status != PASS`
- `decision_source=local_heuristic_draft` / нет `selected_by_agent`
- post-render `approve=false` (в Agent mode)

## Выход

- `videoshorts-memory/output/clips/<stem>-publish/`
- `publish-manifest.json`
- `videoshorts-memory/output/latest-results.json`

## incident_report

Обязателен.
