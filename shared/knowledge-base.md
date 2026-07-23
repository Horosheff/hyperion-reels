# VideoShorts — банк знаний



## Назначение



Плагин Cursor для нарезки вебинаров/длинных видео в вертикальные Shorts/Reels с субтитрами.



## Исходные проекты пользователя



| Путь | Роль |

|------|------|

| `shorts/webinar_cutter/` | CLI + локальный UI (порт 8010): Whisper → hook scoring → dual-screen 30/70 |

| `shorts/shorts_service/backend/` | Полный продакшен-пайплайн: upload/YouTube, scene detect, clip_selector, ASS karaoke, burn, SEO |



## Полный пайплайн (shorts_service — эталон)



```

upload/локальный файл/YouTube → extract_audio

    → parallel(transcribe + scene_detect)

    → select_highlights (Gemini / clip_selector / fallback)

    → per clip: trim → split_screen(webinar|auto) → write ASS/SRT → burn_subtitles → optional zoom/progress

    → SEO metadata → outputs + sidecar .ass в runs/<job>/

```



## Пайплайн webinar_cutter (упрощённый)



```

video → audio.wav → Whisper (subprocess worker) → select_clips (hook 2026)

    → create_webinar_split (ffmpeg vstack 30/70, face median)

```



## Маппинг на субагентов VideoShorts

Контракт: `shared/agent-decision-contract.md` — **агент пишет decision JSON**, скрипт только механика или local `--heuristic`.

| Шаг оригинала | Субагент | Инструмент |
|---------------|----------|------------|
| Upload / brief | videoshorts-intake | — |
| extract_audio + transcribe | videoshorts-transcriber | transcribe.py (механика) |
| cleanup / candidates / moments / scores / editor / virality / boundaries / dramaturgy / montage / decisions / metadata / post-render | соответствующие субагенты | **Write JSON** + `validate_agent_artifacts.py` |
| dual-screen cut | videoshorts-cutter | cut_clips.py |
| ASS/SRT | videoshorts-subtitle-writer | write_subtitles.py |
| burn + package | subtitle-burner + packager | burn_subtitles.py, package_outputs.py |
| QA metrics | videoshorts-guardian | qa_clips.py (ffprobe) |
| Local diagnostic only | — | `run_pipeline.py` + `--heuristic` на decision-скриптах |



**Субтитры «upload»:** в коде нет YouTube Data API captions.upload — субтитры **генерируются** (`.ass`), **вшиваются** в MP4 и **экспортируются** sidecar для ручной загрузки. Packager = этот шаг.



## Параметры по умолчанию



| Параметр | Значение |

|----------|----------|

| Клипов | 10 |

| Длина | из brief `min_sec`–`max_sec` (UI default часто 30–60 или 30–90); переменная, не все ~45s |

| Разрешение | 720×1280 |

| Whisper | base, beam_size=1, VAD on |

| Split | top 30% / bottom 70%, face 2× zoom |

| Субтитры | mrbeast ASS karaoke |



## Env



- `VIDEOSHORTS_WHISPER_DEVICE`, `VIDEOSHORTS_WHISPER_FORCE_CPU`

- `VIDEOSHORTS_WHISPER_LANGUAGE`, `VIDEOSHORTS_WHISPER_BEAM_SIZE`

- `VIDEOSHORTS_WHISPER_WORD_TIMESTAMPS=1` — karaoke ASS

- `VIDEOSHORTS_SUBTITLES_HOOK_STYLE`, `VIDEOSHORTS_SUBTITLES_MAX_CHARS`

- `VIDEOSHORTS_SUBTITLES_TEMPLATE_JSON` — custom JSON template (`fontSize`, `primaryColor`, `wordsPerLine` и т.д.)

- `VIDEOSHORTS_SUBTITLES_EMOJI=1` — локальный rule-based emoji mode. В исходном `shorts_service` emoji завязаны на KIE/Gemini (`SUBTITLES_EMOJI` + ключ); в плагине без ключа используется graceful fallback без сетевых вызовов.


## CLI v0.3.0

```powershell
cd scripts
python run_pipeline.py ..\videoshorts-memory\input\video.mp4 -c 10 --min 30 --max 60 --template mrbeast --subtitle-format both
```

- `--force-cpu`, `--word-timestamps`, `--language`, `--beam-size` управляют faster-whisper worker.

- `--template-json`, `--emoji-subtitles`, `--subtitles-hook-style` управляют ASS/SRT.

- `--no-burn`, `--skip-subtitles`, `--progress-bar`, `--zoom-punch` управляют burn/effects.

- `--no-qa`, `--no-publish-bundle` отключают финальные проверки/упаковку.

## Agent Decision Layer

- VideoShorts не считается просто программой нарезки: `find_moments.py`, `score_clips.py`, `refine_boundaries.py` и `write_agent_decisions.py` — инструменты для субагентов.
- В Agent mode каждый клип обязан иметь `videoshorts-memory/moments/clip-decisions.json`: почему выбран момент, hook/viral hypothesis, evidence начала и конца мысли, cleanup/skлейки, cut instruction, reject criteria и confidence.
- `runMode=local` создаёт только `local_heuristic_draft` для диагностики. Нельзя писать пользователю, что LLM-субагент реально выбрал фрагменты, если запуск был локальным fallback.
- Cleanup связан с пайплайном: scorekeeper учитывает safe/review candidates, boundary-refiner использует silence/filler spans при границах, `latest-results.json` и UI показывают cleanup fields per clip.
- Boundary-refiner не отдаёт cutter клип без finished-thought evidence; scorekeeper ставит `reject_reason` для скучных, контекстных и обрубленных фрагментов.
- Симптомы `~45s fixed windows`, `no cleanup applied`, `no decision evidence` после run — open incident для `videoshorts-fixic`.



## FFmpeg (webinar split)



```text

filter_complex=split[top][bot];

  [top]scale=720:384:force_original_aspect_ratio=decrease,pad=720:384:(ow-iw)/2:(oh-ih)/2:black[t];

  [bot]crop=...,scale=720:896[b];

  [t][b]vstack=inputs=2[v]

```



## Зависимости



- Python 3.10+, FFmpeg в PATH

- `pip install -r scripts/requirements.txt`

- faster-whisper, opencv-python, numpy, tqdm; mediapipe опционально

- GPU: `shorts/shorts_service/backend/.venv310` — предпочтительный интерпретатор worker



## Context7 (2026)



- faster-whisper: `word_timestamps=True`, VAD `min_silence_duration_ms=500`, CUDA `float16` / CPU `int8`

- Материализовать generator: `segments = list(segments)`

- FFmpeg: `subtitles=`/`ass=` требуют libass; на Windows безопаснее копировать `.ass/.srt` во временный ASCII-путь и экранировать `:` как `\:` в filter path.


## Аудит v0.3.0

- Исправлено: `videoshorts_core.transcribe()` больше не теряет `words[]`, поэтому karaoke ASS реально получает word timestamps.

- Исправлено: packager предпочитает финальные `clip_XX.mp4` после burn, а не `_cropped.mp4`.

- Добавлено: custom JSON subtitle templates, hook-style subtitles, локальные emoji, post-burn progress bar и punch zoom.

- Добавлено: fixture `tests/fixtures/synthetic-transcript.json` для быстрых проверок ASS/SRT без Whisper.


