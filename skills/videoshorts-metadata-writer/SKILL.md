---
name: videoshorts-metadata-writer
description: Публикационная упаковка клипов — title, description, hashtags, pinned comment, cover prompt.
---

# VideoShorts Metadata Writer

## Роль

Готовит публикационные поля для каждого готового short. Это отдельный агентный этап: скрипт является инструментом агента, а не заменой решения Директора.

## Вход

- `videoshorts-memory/transcripts/<stem>/transcript.json`
- `videoshorts-memory/moments/<stem>-moments.json`
- `videoshorts-memory/output/clips/<stem>/manifest.json`
- semantic boundary evidence из `moments.json`/`manifest.json`

## Команда

```bash
cd scripts
python write_metadata.py "../videoshorts-memory/transcripts/<stem>/transcript.json" \
  "../videoshorts-memory/moments/<stem>-moments.json" \
  "../videoshorts-memory/output/clips/<stem>" \
  --profile webinar
```

Профили: `webinar`, `sales`, `education`, `podcast`.

## Выход

- `videoshorts-memory/output/clips/<stem>/metadata/clip_XX.metadata.json`
- `videoshorts-memory/output/clips/<stem>/metadata/clip_XX.metadata.md`
- `videoshorts-memory/output/clips/<stem>/metadata-manifest.json`

Каждый клип содержит:

```json
{
  "title": "...",
  "description": "...",
  "hashtags": ["#shorts"],
  "pinned_comment": "...",
  "cover_prompt": "...",
  "copy_block": "..."
}
```

## Критерии качества

- Title до 70 символов из hook, **phrase-aware** (не mid-phrase / не mid-word) и без `...` в конце.
- Description 2–4 строки: hook + payoff + **один** complete supporting beat (не сырой dump / не mid-thought «то есть…»).
- Уникальный `pinned_comment` на каждый клип; topic — целыми словами, без dangling «ещё не».
- `cover_hook` — phrase-aware ≤42, целыми словами.
- Hashtags 5–8, обязательно `#shorts`; topical `#cursor`/`#teya`/`#vscode` если есть в тексте.
- Не выдумывать факты вне transcript/moments.
- Fragment: `videoshorts-memory/fragments/metadata-writer.md` с `incident_report`.
