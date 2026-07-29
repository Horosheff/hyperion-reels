#!/usr/bin/env python3
"""Тесты жёстких API-лимитов платформ в validate_metadata."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validate_agent_artifacts import PLATFORM_LIMITS, validate_metadata


def _clip(platforms: dict) -> dict:
    return {
        "index": 1,
        "title": "Hook title",
        "description": "Description",
        "cover_prompt": "studio frame",
        "markdown": "clip_01.metadata.md",
        "json": "clip_01.metadata.json",
        "platforms": platforms,
    }


def _write_manifest(tmp: Path, clips: list[dict]) -> Path:
    manifest = {
        "schema_version": 2,
        "decision_source": "agent",
        "authored_by": "videoshorts-metadata-writer",
        "clips": clips,
    }
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    (tmp / "metadata" / "clip_01.metadata.json").write_text("{}", encoding="utf-8")
    (tmp / "metadata" / "clip_01.metadata.md").write_text("# meta", encoding="utf-8")
    (tmp / "metadata-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return tmp


def _base_platforms() -> dict:
    return {
        "youtube": {"title": "Ok", "description": "Ok", "tags": ["a", "b"]},
        "instagram": {"caption": "Ok"},
        "tiktok": {"caption": "Ok"},
        "telegram": {"caption": "Ok"},
    }


class PlatformLimitsTest(unittest.TestCase):
    def test_valid_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(_base_platforms())])
            ok, errors = validate_metadata(root)
            self.assertTrue(ok, errors)

    def test_youtube_title_over_100_rejected(self) -> None:
        platforms = _base_platforms()
        platforms["youtube"]["title"] = "x" * 101
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(platforms)])
            ok, errors = validate_metadata(root)
            self.assertFalse(ok)
            self.assertTrue(any("youtube.title" in e and "100" in e for e in errors), errors)

    def test_youtube_description_over_5000_rejected(self) -> None:
        platforms = _base_platforms()
        platforms["youtube"]["description"] = "x" * 5001
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(platforms)])
            ok, errors = validate_metadata(root)
            self.assertFalse(ok)
            self.assertTrue(any("youtube.description" in e for e in errors), errors)

    def test_youtube_tags_total_over_500_rejected(self) -> None:
        platforms = _base_platforms()
        platforms["youtube"]["tags"] = ["x" * 60] * 9  # 540 + 8 separators
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(platforms)])
            ok, errors = validate_metadata(root)
            self.assertFalse(ok)
            self.assertTrue(any("tags total" in e for e in errors), errors)

    def test_instagram_caption_over_2200_rejected(self) -> None:
        platforms = _base_platforms()
        platforms["instagram"]["caption"] = "x" * 2201
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(platforms)])
            ok, errors = validate_metadata(root)
            self.assertFalse(ok)
            self.assertTrue(any("instagram.caption" in e for e in errors), errors)

    def test_telegram_caption_over_1024_rejected(self) -> None:
        platforms = _base_platforms()
        platforms["telegram"]["caption"] = "x" * 1025
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(platforms)])
            ok, errors = validate_metadata(root)
            self.assertFalse(ok)
            self.assertTrue(any("telegram.caption" in e for e in errors), errors)

    def test_extra_platform_vk_title_limit_checked(self) -> None:
        platforms = _base_platforms()
        platforms["vk"] = {"title": "x" * 101}
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(platforms)])
            ok, errors = validate_metadata(root)
            self.assertFalse(ok)
            self.assertTrue(any("vk.title" in e for e in errors), errors)

    def test_unknown_platform_ignored(self) -> None:
        platforms = _base_platforms()
        platforms["odnoklassniki"] = {"title": "x" * 9999}
        with tempfile.TemporaryDirectory() as td:
            root = _write_manifest(Path(td), [_clip(platforms)])
            ok, errors = validate_metadata(root)
            self.assertTrue(ok, errors)

    def test_limits_cover_required_platforms(self) -> None:
        for name in ("youtube", "instagram", "tiktok", "telegram"):
            self.assertIn(name, PLATFORM_LIMITS)


if __name__ == "__main__":
    unittest.main()
