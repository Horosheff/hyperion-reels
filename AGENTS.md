# Инструкция для нейросетей и агентов Cursor

Этот файл — короткий вход для AI-агентов, которые устанавливают или запускают **Гиперион**.

## Главное

Полные правила установки без ошибок: **[`docs/INSTALL.md`](docs/INSTALL.md)**

Telegram: https://t.me/maya_pro

## Обязательный порядок

```text
1. python --version   (>= 3.10)
2. ffmpeg -version
3. ffprobe -version
4. .\bootstrap-videoshorts.ps1
5. проверить videoshorts-memory/dependencies-report.json → ready: true
6. .\install-plugin.ps1
7. попросить пользователя перезапустить Cursor
8. .\open-videoshorts-ui.ps1
9. дождаться READY_FOR_AGENT
10. только потом /videoshorts-new и Task-цепочку
```

## Запреты

- Не запускать Whisper/cutter при `dependencies.ready=false`
- Не считать `scripts/run_pipeline.py` агентным монтажом
- Не коммитить `videoshorts.local.env`, видео, output-клипы, ключи
- Не ставить Python < 3.10
- Не пропускать перезапуск Cursor после `install-plugin.ps1`

## Успех установки

`videoshorts-memory/dependencies-report.json`:

```json
{ "ready": true, "missing_required": [] }
```

И существуют:

- `%USERPROFILE%\.cursor\plugins\local\hyperion\`
- `%USERPROFILE%\.cursor\agents\videoshorts-*.md`

## Дальше

- Роли субагентов: [`docs/AGENTS.md`](docs/AGENTS.md)
- Архитектура: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Пайплайн: [`AGENT-PIPELINE.md`](AGENT-PIPELINE.md)
