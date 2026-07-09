# Установка Гиперион

## 1. Клонировать репозиторий

```powershell
git clone https://github.com/Horosheff/hyperion-reels.git
cd hyperion-reels
```

## 2. Bootstrap зависимостей

```powershell
.\bootstrap-videoshorts.ps1
```

Скрипт:

1. Проверит Python 3.10+
2. Установит пакеты из `scripts/requirements.txt`
3. Попытается поставить FFmpeg через winget
4. Запишет `videoshorts-memory/dependencies-report.json`

Если FFmpeg поставился, но команда `ffmpeg` не находится — **перезапустите терминал**.

## 3. Установить плагин в Cursor

```powershell
.\install-plugin.ps1
```

Перезапустите Cursor.

## 4. Запустить UI

```powershell
.\open-videoshorts-ui.ps1
```

Откроется локальный bridge: `http://127.0.0.1:8765/`

## 5. Передать задачу Директору

1. Добавьте видео
2. Нажмите **OK — передать Cursor Director**
3. В Cursor: `/videoshorts-new`

## Кнопки помощи

- Telegram: https://t.me/maya_pro
- Архитектура: [ARCHITECTURE.md](ARCHITECTURE.md)
- Субагенты: [AGENTS.md](AGENTS.md)
