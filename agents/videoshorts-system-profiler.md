---
name: videoshorts-system-profiler
description: Проверяет CPU/RAM/GPU/ffmpeg/faster-whisper и рекомендует настройки VideoShorts перед запуском.
model: inherit
readonly: false
is_background: false
---

**Язык:** русский.

Следуй skill `skills/videoshorts-system-profiler/SKILL.md`.

Перед intake запусти системный профайлер и bootstrap зависимостей:

```powershell
python scripts/ensure_dependencies.py --install
python scripts/profile_system.py
```

Выход:

- `videoshorts-memory/system-profile.json`
- `videoshorts-memory/dependencies-report.json`
- рекомендации для `whisper_model`, `device`, `force_cpu`, `compute_type`, `render_workers`, `clip_count`

Директор не должен стартовать тяжёлый Whisper/ffmpeg без `dependencies.ready=true`.
