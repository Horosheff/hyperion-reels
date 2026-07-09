# VideoShorts Packager



Экспорт для публикации: финальные MP4 + **sidecar** ASS/SRT + metadata JSON/Markdown.



В оригинале `shorts_service` нет YouTube Captions API — субтитры вшиваются в видео и сохраняются как `.ass` в `runs/<job>/`. Packager дублирует sidecar для ручной загрузки в YouTube Studio / Reels/CapCut.

Важно: packager должен брать `clip_XX.mp4`, если burn уже создал финальный файл. Fallback на `clip_XX_cropped.mp4` допустим только в режиме `--no-burn`. Перед packager должен пройти `videoshorts-metadata-writer`, чтобы существовал `metadata-manifest.json`.



## Команда



```bash

cd scripts

python package_outputs.py ../videoshorts-memory/output/clips/<stem>/

```



## Выход



- `videoshorts-memory/output/clips/<stem>-publish/`

- `publish-manifest.json` — список файлов, sidecar, metadata и флаг `burned`

- `videoshorts-memory/output/latest-results.json` — стабильный индекс для `ui/videoshorts-results.html` с путями, QA, sidecar, metadata и publish bundle. В индекс не включать base64/содержимое MP4.

После упаковки Директор открывает/показывает `ui/videoshorts-results.html`.



## incident_report



Обязателен.


