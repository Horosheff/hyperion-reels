---
name: videoshorts-cover-writer
description: AI-обложки 9:16 через Kie GPT Image 2 (avatar + style refs + hook) для выбранных клипов.
---

# VideoShorts Cover Writer

## Роль

После выбора клипов в Results UI готовит **AI-обложки 9:16** через Kie (`gpt-image-2-image-to-image`).

## Brand kit

```text
videoshorts-memory/brand/covers/
  brand-urls.json     ← предпочтительно: HTTPS avatar + refs (mayai.ru)
  avatar.png          ← локальный fallback лица
  refs/ref-01-*.png   ← локальные style refs (если нет HTTPS)
  cdn-cache.json      ← кэш upload URL (если грузили локально)
```

Ключ: `videoshorts.local.env` → `KIE_API_KEY` (или env). Не коммитить.

Пример `brand-urls.json`:

```json
{
  "avatar_url": "https://mayai.ru/wp-content/uploads/2026/07/ava.jpg",
  "refs": [
    {"name": "ref-01", "url": "https://mayai.ru/.../ref1.jpg"}
  ]
}
```

## Вход

- `publish-selection.json`
- `metadata/clip_XX.metadata.json` (`hook` / `cover_text` / `title`)
- brand kit выше

## Команда

```bash
cd scripts
python prepare_covers.py "../videoshorts-memory/output/clips/<stem>" --mode kie
```

`auto` (default): Kie если есть ключ + avatar, иначе ffmpeg-кадр.

## Промпт (что делает скрипт)

На каждый клип:

1. Берёт короткий hook из metadata
2. Чередует style ref (01→02→03→04…)
3. Сохраняет лицо с avatar; одежду/позу/эмоцию может менять
4. Kie i2i: `input_urls = [avatar, style_ref]`, `aspect_ratio=9:16`

## Выход

- `covers/clip_XX_cover.jpg` — финальная AI-обложка
- `covers/clip_XX_cover.prompt.txt`
- `covers-manifest.json` (`generator: kie-gpt-image-2-i2i`)

Дальше: `videoshorts-publish-prep` / `prepare_publish_queue.py`.

## Fallback

Если Kie упал на клипе — ffmpeg-кадр из видео (`mode: ffmpeg_fallback`), run не рвётся целиком.
