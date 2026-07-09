# Установка Гиперион — без ошибок

Эта инструкция для людей **и для нейросетей / агентов Cursor**, которые помогают установить плагин.

Если вы агент: читайте раздел [Правила для нейросетей и агентов](#правила-для-нейросетей-и-агентов) целиком, затем выполняйте шаги строго по порядку.

---

## Что нужно до установки

| Компонент | Обязательно | Зачем |
|-----------|-------------|--------|
| Cursor | да | плагин и субагенты |
| Git | да | клонирование репозитория |
| Python **3.10+** | да | Whisper, скрипты, UI bridge |
| FFmpeg + ffprobe | да | резка, субтитры, QA |
| NVIDIA GPU / CUDA | нет | ускоряет Whisper; без GPU работает CPU |

Проверка вручную:

```powershell
python --version
git --version
ffmpeg -version
ffprobe -version
```

Ожидаемо:

- Python `3.10` / `3.11` / `3.12` / `3.13` / `3.14` — ок
- Python `3.9` и ниже — **стоп**, обновить Python
- `ffmpeg` и `ffprobe` должны отвечать версией, не «не найдено»

---

## Быстрая установка (Windows)

```powershell
git clone https://github.com/Horosheff/hyperion-reels.git
cd hyperion-reels
.\bootstrap-videoshorts.ps1
.\install-plugin.ps1
```

После этого:

1. **Полностью перезапустите Cursor**
2. Откройте папку `hyperion-reels` как workspace
3. Запустите UI:

```powershell
.\open-videoshorts-ui.ps1
```

4. В Cursor: `/videoshorts-new`

Telegram-поддержка / канал: https://t.me/maya_pro

---

## Что делает каждый скрипт

| Скрипт | Что делает | Когда запускать |
|--------|------------|-----------------|
| `bootstrap-videoshorts.ps1` | Проверяет и ставит зависимости | Первый запуск / чистый ПК |
| `install-plugin.ps1` | Копирует плагин в Cursor local plugins + agents | После bootstrap и после обновлений |
| `open-videoshorts-ui.ps1` | Поднимает HTML bridge `http://127.0.0.1:8765/` | Перед каждой новой нарезкой |
| `scripts/ensure_dependencies.py --install` | Машинная проверка/установка deps | Если bootstrap упал или UI пишет «не хватает» |
| `scripts/profile_system.py` | Профиль CPU/RAM/GPU + рекомендации Whisper | После установки / перед тяжёлым прогоном |

---

## Правила для нейросетей и агентов

### Жёсткие правила (не нарушать)

1. **Не пропускайте bootstrap.** Нельзя сразу запускать Whisper/cutter, если нет `dependencies-report.json` со статусом `ready: true`.
2. **Не выдумывайте пути.** Рабочий корень — клонированный репозиторий. Плагин ставится в `%USERPROFILE%\.cursor\plugins\local\videoshorts`.
3. **Не коммитьте секреты.** `videoshorts.local.env`, API-ключи, видео пользователя, `videoshorts-memory/output/**` — не в git и не в чат.
4. **Не запускайте `run_pipeline.py` как «агентный монтаж».** Это только diagnostic fallback. Основной путь: UI → `READY_FOR_AGENT` → Task-цепочка Director.
5. **Не стартуйте transcriber/cutter при `dependencies.ready=false`.** Сначала `ensure_dependencies.py --install`, потом снова profiler.
6. **После `install-plugin.ps1` просите пользователя перезапустить Cursor.** Иначе skills/agents/rules могут не подхватиться.
7. **После установки FFmpeg через winget** — новый терминал / перезапуск PATH. Иначе `ffmpeg not found`.
8. **Не ставьте пакеты «наугад».** Только `scripts/requirements.txt` или `ensure_dependencies.py --install`.
9. **Не меняйте Python пользователя на 3.9.** Минимум 3.10.
10. **Если GPU/CUDA нестабильна** — ставьте Whisper на CPU: `device=cpu` / `--force-cpu`. Это не ошибка установки.

### Правильный порядок действий агента

```text
1) Проверить: python / git / ffmpeg / ffprobe
2) Если репо нет → git clone
3) cd в корень репо
4) .\bootstrap-videoshorts.ps1
5) Прочитать videoshorts-memory/dependencies-report.json
6) Если ready=false → исправить missing_required → повторить bootstrap
7) .\install-plugin.ps1
8) Сказать пользователю: перезапусти Cursor
9) .\open-videoshorts-ui.ps1
10) Дождаться READY_FOR_AGENT
11) Только потом Task-цепочка /videoshorts-new
```

### Команды, которые агент должен запускать

```powershell
# проверка
python --version
ffmpeg -version
ffprobe -version

# установка
.\bootstrap-videoshorts.ps1
.\install-plugin.ps1

# повторная проверка deps
python scripts\ensure_dependencies.py --install
python scripts\profile_system.py

# UI
.\open-videoshorts-ui.ps1
```

### Что считать успешной установкой

Файл `videoshorts-memory/dependencies-report.json` должен содержать:

```json
{
  "ready": true,
  "missing_required": []
}
```

Обязательные checks:

- `python` available
- `ffmpeg` available (+ ffprobe)
- `opencv-python`
- `numpy`
- `mediapipe`
- `faster-whisper`
- `tqdm`

NVIDIA/`nvidia-smi` — **опционально**. Отсутствие GPU не блокирует установку.

Также после `install-plugin.ps1` должны существовать:

- `%USERPROFILE%\.cursor\plugins\local\videoshorts\`
- `%USERPROFILE%\.cursor\agents\videoshorts-*.md`

---

## Частые ошибки и как чинить

| Симптом | Причина | Решение |
|---------|---------|---------|
| `Python was not found` | Python не в PATH | Установить с python.org, галочка **Add to PATH**, новый терминал |
| `No module named faster_whisper` | Не ставили pip deps | `.\bootstrap-videoshorts.ps1` или `pip install -r scripts\requirements.txt` |
| `FFmpeg not found` | Нет ffmpeg / старый PATH | `winget install Gyan.FFmpeg`, затем **новый терминал** |
| UI не открывается | Bridge не запущен | `.\open-videoshorts-ui.ps1` |
| В Cursor нет субагентов | Не сделали install-plugin / не перезапустили Cursor | `.\install-plugin.ps1` → Restart Cursor |
| Whisper падает на CUDA | Битая CUDA/cuDNN | В UI выбрать CPU или `--force-cpu` |
| `0xC0000409` на Windows Whisper | Известный teardown-глюк | Использовать стабильный Python 3.10+, CPU fallback |
| Агент режет «сам скриптом» | Перепутали local diagnostic с Agent mode | Только `READY_FOR_AGENT` + Task Director |
| После winget ffmpeg всё ещё нет | PATH не обновился | Закрыть Cursor и терминал, открыть заново, проверить `ffmpeg -version` |
| MediaPipe / OpenCV import error | Неполный pip install | Повторить `python scripts\ensure_dependencies.py --install` |

---

## Установка pip вручную (если bootstrap недоступен)

```powershell
cd scripts
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd ..
python scripts\ensure_dependencies.py
```

FFmpeg вручную (Windows):

```powershell
winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
```

macOS:

```bash
brew install ffmpeg
python3 -m pip install -r scripts/requirements.txt
```

Linux (пример Debian/Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
python3 -m pip install -r scripts/requirements.txt
```

---

## Правила для пользователей, которые работают через агента

Напишите агенту примерно так:

```text
Установи Гиперион из https://github.com/Horosheff/hyperion-reels
Строго по docs/INSTALL.md:
1) bootstrap
2) проверить dependencies-report.json ready=true
3) install-plugin
4) сказать мне перезапустить Cursor
5) открыть UI
Не запускай нарезку, пока зависимости не ready.
```

После установки проверьте в UI блок **«Проверка системы»**:

- кнопка **Проверить и применить настройки**
- кнопка **Установить недостающее**

---

## Опционально: B-roll / KIE

B-roll не нужен для базовой нарезки.

Если включаете B-roll:

1. Скопируйте `videoshorts.env.example` → `videoshorts.local.env`
2. Впишите `KIE_API_KEY=...`
3. **Никогда** не коммитьте `videoshorts.local.env`
4. Не вставляйте ключ в brief/handoff/чат

Без ключа обычный пайплайн Shorts/Reels работает.

---

## Чеклист перед первой нарезкой

- [ ] `python --version` ≥ 3.10
- [ ] `ffmpeg -version` ок
- [ ] `ffprobe -version` ок
- [ ] `bootstrap-videoshorts.ps1` завершился без missing_required
- [ ] `dependencies-report.json` → `ready: true`
- [ ] `install-plugin.ps1` выполнен
- [ ] Cursor перезапущен
- [ ] `open-videoshorts-ui.ps1` открыл `http://127.0.0.1:8765/`
- [ ] Видео загружено, статус `READY_FOR_AGENT`
- [ ] Запущен `/videoshorts-new`

---

## Помощь

- Telegram: https://t.me/maya_pro
- Архитектура: [ARCHITECTURE.md](ARCHITECTURE.md)
- Субагенты: [AGENTS.md](AGENTS.md)
- Полный пайплайн: [../AGENT-PIPELINE.md](../AGENT-PIPELINE.md)
