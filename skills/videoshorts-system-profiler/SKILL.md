# VideoShorts System Profiler

## Роль

Перед стартом пайплайна проверяет машину пользователя, **все обязательные зависимости** и выставляет безопасные настройки под ресурсы:

- CPU logical cores
- RAM
- NVIDIA/CUDA и VRAM через `nvidia-smi`
- видеоконтроллеры Windows
- Python 3.10+
- `ffmpeg` / `ffprobe`
- Python-пакеты: `opencv-python`, `numpy`, `mediapipe`, `faster-whisper`, `tqdm`

## Команды

```powershell
python scripts/ensure_dependencies.py --install
python scripts/profile_system.py
```

Или один раз для нового пользователя:

```powershell
.\bootstrap-videoshorts.ps1
```

## Выход

```text
videoshorts-memory/system-profile.json
videoshorts-memory/dependencies-report.json
```

## Правила

- Если обязательные зависимости отсутствуют — сначала `ensure_dependencies.py --install`.
- Если после автоустановки что-то всё ещё отсутствует (обычно Python < 3.10 или FFmpeg не попал в PATH) — статус **FAIL**, пайплайн не стартует.
- Если профайлер не смог проверить GPU, это не блокер: использовать CPU/int8 fallback и записать причину в incident_report.

## Правила рекомендаций

- Если есть NVIDIA GPU 12GB+ VRAM: Whisper `turbo`, GPU, `float16`.
- Если есть NVIDIA GPU 8GB+ VRAM: Whisper `small`, GPU, `float16`.
- Если есть NVIDIA GPU 3-8GB VRAM: Whisper `base`, GPU, `float16`.
- Если CUDA нет: CPU/int8, Whisper `base`.
- Если RAM меньше 8GB и CUDA нет: Whisper `tiny`, меньше клипов.
- Если RAM меньше 12GB или CPU слабый: уменьшить параллельность рендера.

## Handoff fragment

```text
=== VIDEOSHORTS-SYSTEM-PROFILER ===
status: ✅ PASS | ❌ FAIL
profile: videoshorts-memory/system-profile.json
dependencies_report: videoshorts-memory/dependencies-report.json
dependencies_ready: true|false
recommended_whisper: base|small|turbo|tiny
device: gpu|cpu
force_cpu: true|false
render_workers: N
incident_report: none
```

Если `dependencies_ready=false`, Director **не** запускает transcriber/cutter.
