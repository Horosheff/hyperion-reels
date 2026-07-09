<p align="center">
  <img src="assets/hyperion-banner.png" alt="Гиперион — боженька монтажа" width="100%" />
</p>

<h1 align="center">Гиперион</h1>

<p align="center">
  <strong>Субагентская система для нарезки и монтажа Shorts / Reels из длинных видео</strong>
</p>

<p align="center">
  <em>БОЖЕНЬКА МОНТАЖА · 20+ субагентов · Cursor + Whisper + FFmpeg</em>
</p>

<p align="center">
  <a href="#-быстрая-установка">
    <img src="https://img.shields.io/badge/%F0%9F%9A%80%20Установить-Гиперион-111111?style=for-the-badge" alt="Установить" />
  </a>
  &nbsp;
  <a href="https://t.me/maya_pro">
    <img src="https://img.shields.io/badge/Telegram-Maya%20Pro-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Maya Pro" />
  </a>
  &nbsp;
  <a href="docs/ARCHITECTURE.md">
    <img src="https://img.shields.io/badge/%F0%9F%93%8A%20Схема%20работы-docs-C9A227?style=for-the-badge" alt="Схема работы" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-Plugin-000000?logo=cursor&logoColor=white" alt="Cursor Plugin" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FFmpeg-required-007808?logo=ffmpeg&logoColor=white" alt="FFmpeg" />
  <img src="https://img.shields.io/badge/Whisper-faster--whisper-FF6F00" alt="Whisper" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT" />
</p>

---

## Что это

**Гиперион** — плагин для Cursor, который превращает длинное видео (вебинар, эфир, урок, подкаст) в набор вертикальных клипов для YouTube Shorts / Instagram Reels / TikTok.

Система не режет «по таймеру». Сначала субагенты понимают речь, выбирают законченные мысли, отбраковывают слабые моменты, уточняют границы, пишут монтажное ТЗ — и только потом режут, субтитруют и упаковывают.

> **20+ субагентов** работают как монтажная студия: profiler, intake, transcriber, editor, virality critic, dramaturg, cutter, guardian, packager и другие.

---

## Кнопки

<p align="center">
  <a href="#-быстрая-установка"><img src="https://img.shields.io/badge/%E2%9A%A1%20Установить%20плагин-black?style=for-the-badge" alt="Install" /></a>
  &nbsp;
  <a href="https://t.me/maya_pro"><img src="https://img.shields.io/badge/%F0%9F%92%AC%20Telegram%20канал-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram" /></a>
  &nbsp;
  <a href="docs/AGENTS.md"><img src="https://img.shields.io/badge/%F0%9F%A4%96%20Список%20субагентов-6E56CF?style=for-the-badge" alt="Agents" /></a>
  &nbsp;
  <a href="docs/ARCHITECTURE.md"><img src="https://img.shields.io/badge/%F0%9F%97%BA%EF%B8%8F%20Архитектура-C9A227?style=for-the-badge" alt="Architecture" /></a>
</p>

---

## Схема работы

```mermaid
flowchart LR
  A[📹 Длинное видео] --> B[🧠 Whisper + смысл]
  B --> C[✂️ Редакция субагентов]
  C --> D[🎬 Монтаж 9:16]
  D --> E[🔤 Субтитры]
  E --> F[✅ Guardian QA]
  F --> G[📦 Publish bundle]
```

Подробная схема: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)  
Роли агентов: [`docs/AGENTS.md`](docs/AGENTS.md)

### Пайплайн одной строкой

```text
Profiler → Intake → Whisper → Cleanup → Candidates → Moments
→ Scores → Editor → Virality → Boundaries → Dramaturg → Montage
→ Cutter → Audio → Subtitles → Burn → Guardian → Post-render
→ Metadata → Packager → (Fixic при сбоях)
```

---

## ⚡ Быстрая установка

### Windows (рекомендуется)

```powershell
git clone https://github.com/Horosheff/hyperion-reels.git
cd hyperion-reels
.\bootstrap-videoshorts.ps1
.\install-plugin.ps1
```

Затем **перезапустите Cursor**.

### Что делает bootstrap

| Шаг | Действие |
|-----|----------|
| 1 | Проверяет Python 3.10+ |
| 2 | Ставит pip-зависимости (`faster-whisper`, OpenCV, MediaPipe…) |
| 3 | Пытается установить FFmpeg (`winget install Gyan.FFmpeg`) |
| 4 | Пишет отчёт `videoshorts-memory/dependencies-report.json` |

### Запуск UI

```powershell
.\open-videoshorts-ui.ps1
```

Откроется `http://127.0.0.1:8765/`

1. Нажмите **«Добавить файл локально»**
2. Проверьте настройки (или кнопку **«Проверить и применить настройки»**)
3. При необходимости — **«Установить недостающее»**
4. Нажмите **«OK — передать Cursor Director»**
5. В Cursor запустите `/videoshorts-new` или попросите Директора продолжить пайплайн
6. Результаты: `http://127.0.0.1:8765/results` или `/videoshorts-results`

---

## Что на выходе

| Артефакт | Описание |
|----------|----------|
| `clip_XX.mp4` | Вертикальные ролики 9:16 с субтитрами |
| ASS / SRT | Sidecar-субтитры |
| Metadata | Title, description, hashtags |
| Publish folder | Готовый пакет для ручной загрузки |
| QA reports | Guardian, audio, safe-zone, post-render |

---

## Возможности

- **Смысловая нарезка** 30–60 сек, не фиксированные окна
- **Dual-screen webinar** 30/70 с детекцией лица
- **Karaoke-субтитры** (шаблоны mrbeast / hormozi / minimal / neon / fire)
- **Редакционный loop**: editor + virality + dramaturg + boundary refiner
- **Guardian v2**: длина, вертикаль, audio, decision evidence
- **Автопроверка зависимостей** для новых пользователей
- **HTML UI** без base64-гигантов: файл идёт через localhost bridge

---

## Требования

- [Cursor](https://cursor.com)
- Python **3.10+**
- **FFmpeg** + **ffprobe** в PATH
- Windows 10/11 (основной сценарий), macOS/Linux — через те же скрипты

Опционально: NVIDIA GPU для ускорения Whisper.

---

## Команды Cursor

| Команда | Действие |
|---------|----------|
| `/videoshorts-new` | Новая нарезка |
| `/videoshorts-results` | Открыть результаты |

---

## Структура репозитория

```text
hyperion-reels/
├── assets/                 # баннер и визуалы
├── agents/                 # субагенты Task
├── skills/                 # инструкции агентов
├── rules/                  # оркестрация Director
├── scripts/                # Whisper / FFmpeg / QA
├── ui/                     # HTML upload + results
├── docs/                   # схемы и роли
├── bootstrap-videoshorts.ps1
├── install-plugin.ps1
└── open-videoshorts-ui.ps1
```

---

## Telegram

Новости, разборы и обновления системы монтажа:

<p align="center">
  <a href="https://t.me/maya_pro">
    <img src="https://img.shields.io/badge/Подписаться%20на%20канал-Maya%20Pro-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Maya Pro" />
  </a>
</p>

👉 **https://t.me/maya_pro**

---

## Лицензия

MIT — см. [`LICENSE`](LICENSE)

---

<p align="center">
  <strong>Гиперион</strong> · боженька монтажа · сделано для создателей контента
</p>

<p align="center">
  <a href="https://t.me/maya_pro">Telegram</a> ·
  <a href="docs/ARCHITECTURE.md">Архитектура</a> ·
  <a href="docs/AGENTS.md">Субагенты</a>
</p>
