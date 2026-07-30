---
name: videoshorts-audio-polisher
description: LEGACY — не вызывать в slim P0. loudnorm вызывает cutter через audio_polish.py.
---

# LEGACY: Audio Polisher

**Не запускай** в slim P0. См. `videoshorts-cutter` (после cut → `audio_polish.py`).

`audio_polish.py`: two-pass loudnorm (I=-14, TP=-1.5). Если после loudnorm `volumedetect max_volume > -1.0` dB — автоматически `alimiter` (peak ceiling) и re-measure. Поля `peak_limiter_applied` / summary `peak_limiter_applied` в metrics/manifest.