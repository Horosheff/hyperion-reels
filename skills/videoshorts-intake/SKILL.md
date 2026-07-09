# VideoShorts Intake







## Роль







Проверить входное видео, **готовность зависимостей** и зафиксировать brief перед Whisper.







## Шаги







1. Прочитать `videoshorts-memory/00-brief.md` и `.cursor/videoshorts-handoff.md`.



2. Убедиться, что `videoshorts-memory/system-profile.json` и `dependencies-report.json` существуют и `dependencies.ready=true`.



3. Если зависимости не готовы:



```powershell

python scripts/ensure_dependencies.py --install

python scripts/profile_system.py

```



4. Проверить путь к видео; при необходимости скопировать в `videoshorts-memory/input/<stem>.mp4`.



5. Проверить: `ffmpeg -version`, `ffprobe`, Python 3.10+, импорт `faster_whisper`, `cv2`, `mediapipe`.



6. Записать во fragment `=== VIDEOSHORTS INTAKE ===` пути, размер файла, параметры brief, статус зависимостей.







## Выход







- `videoshorts-memory/input/<stem>.<ext>`



- Обновлённый handoff с путём к видео для transcriber.







## Блокеры







- `dependencies.ready=false` после `--install` → **FAIL**, не передавать transcriber.



- FFmpeg/ffprobe не в PATH → **FAIL**.



- Видео не найдено или битый контейнер → **FAIL**.







## incident_report







Обязателен по `shared/subagent-end-of-task-contract.md`.





