---
name: videoshorts-cutter
description: Dual-screen ffmpeg рендер 9:16 — 30% экран / 70% лицо.
---

# VideoShorts Cutter

## Вход

- Исходное видео (из brief)
- `refined-moments.json` от `videoshorts-boundary-refiner` (fallback: `moments.json`)
- `clip-decisions.json` от moment-finder/scorekeeper/boundary-refiner

## Действия

1. Прочитать pitfalls
2. Перед ffmpeg gate:
   - не резать `moments.json`, если есть `refined-moments.json`;
   - не резать клипы с `reject_reason`;
   - если нет `clip-decisions.json` или все решения выглядят как неподтверждённый `local_heuristic_draft` в Agent mode — остановиться и вернуть incident, а не делать алгоритмические 45s clips.

3. Запустить:

```bash
cd scripts
$env:VIDEOSHORTS_AGENT_MODE="1"
python cut_clips.py "<video_path>" "../videoshorts-memory/moments/refined-moments.json" `
  -o "../videoshorts-memory/output/clips/<stem>" `
  --quality-preset release `
  --require-agent-decisions
```

Quality presets:
- `release` — 1080×1920, CRF 19, medium (публикация)
- `draft` — 720×1280, CRF 26, veryfast (быстро)

4. Dual-screen (как webinar_cutter):
   - 7 сэмплов кадров → median face (MediaPipe / OpenCV Haar)
   - top 30%: scale+pad экрана
   - bottom 70%: crop вокруг лица 2× zoom
   - vstack → H.264 `yuv420p` + AAC (по preset)

5. Проверить `manifest.json` — поле `ok` для каждого клипа, а `latest-results.json` после Guardian/Packager должен показывать decision evidence.

## Выход

```
videoshorts-memory/output/clips/<stem>/
  clip_01_cropped.mp4 … clip_NN_cropped.mp4
  manifest.json
```

Fragment `videoshorts-memory/fragments/cutter.md`:

```text
=== VIDEOSHORTS-CUTTER ===
status: ✅
clips_dir: videoshorts-memory/output/clips/<stem>
rendered: N/M
incident_report: none
```

## Требования

- FFmpeg в PATH
- opencv-python, mediapipe (опционально)
