from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from broll_composite import build_overlay_command, composite


class BrollCompositeTests(unittest.TestCase):
    @patch("broll_composite.find_ffmpeg", return_value="ffmpeg")
    def test_overlay_command_preserves_audio_and_limits_time(self, _):
        command = build_overlay_command(Path("clip.mp4"), Path("asset.mp4"), Path("out.mp4"), 4.0, 2.5)
        self.assertIn("-map", command)
        self.assertIn("0:a?", command)
        self.assertIn("between(t,4.000,6.500)", command[command.index("-filter_complex") + 1])

    @patch("broll_composite.find_ffmpeg", return_value="ffmpeg")
    def test_dry_run_never_invokes_ffmpeg(self, _):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clip_01_cropped.mp4").write_bytes(b"x")
            assets = root / "broll-assets"
            assets.mkdir()
            (assets / "clip_01_broll.mp4").write_bytes(b"x")
            report = composite(root, {"inserts": [{
                "clip_index": 1, "asset_file": "clip_01_broll.mp4",
                "at_sec": 3, "duration_sec": 2, "status": "READY",
            }]}, dry_run=True)
            self.assertEqual(report["clips"][0]["status"], "DRY_RUN")


if __name__ == "__main__":
    unittest.main()
