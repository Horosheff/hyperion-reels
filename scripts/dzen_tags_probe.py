# -*- coding: utf-8 -*-
"""Probe: открыть Дзен через bundled dzen_client (черновик)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from publish_dzen import _load_local_env, resolve_config  # noqa: E402

local = _load_local_env(PLUGIN_ROOT)
for k, v in local.items():
    os.environ.setdefault(k, v)

cfg = resolve_config(PLUGIN_ROOT)
os.environ["HEADLESS"] = "false"
os.environ["KEEP_BROWSER_OPEN"] = "false"
os.environ["VIDEOSHORTS_FORCE_CLOSE_BROWSER"] = "1"
os.environ["STORAGE_STATE"] = str(Path(cfg["storage"]).resolve())
if cfg.get("channel"):
    os.environ["DZEN_CHANNEL_NAME"] = str(cfg["channel"])

from dzen_client import DzenClient  # noqa: E402

CLIPS = PLUGIN_ROOT / "videoshorts-memory" / "output" / "clips" / "2026-07-15 19-01-54"
VIDEO = CLIPS / "clip_04.mp4"
COVER = CLIPS / "covers" / "clip_04_cover.jpg"
OUT = CLIPS / "dzen-tags-probe.json"
TAGS = ["нейросети", "технологии", "искусственный интеллект", "обучение", "бизнес"]
TITLE = "Тест тегов VideoShorts — не публиковать"
DESCRIPTION = "Проверка автозаполнения описания и тегов по одному чипу."


async def main() -> int:
    if not VIDEO.is_file():
        print("NO VIDEO", VIDEO)
        return 1
    client = DzenClient()
    report: dict = {"ok": False, "tags_requested": TAGS, "client": str(cfg["client"])}
    try:
        await client.start()
        if not await client.login_yandex():
            report["error"] = "login failed"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1
        ok = await client.upload_short_video(
            video_path=str(VIDEO),
            title=TITLE,
            description=DESCRIPTION,
            tags=TAGS,
            cover_path=str(COVER) if COVER.is_file() else None,
            auto_generate=False,
            publish=False,
        )
        report["ok"] = bool(ok)
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        await client.close(force=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
