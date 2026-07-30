#!/usr/bin/env python3
"""Тесты финишных видео-фильтров Q1/Q2: lanczos, unsharp, HDR tonemap, fps-cap, encode args."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import quality_presets as qp
import videoshorts_core as vsc


class ScaleSharpenTest(unittest.TestCase):
    def test_scale_uses_lanczos(self) -> None:
        self.assertEqual(qp.scale_filter(1080, 1920), "scale=1080:1920:flags=lanczos")

    def test_sharpen_default_on(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertIn("unsharp=5:5:0.6", qp.sharpen_filter())

    def test_sharpen_disabled_by_env(self) -> None:
        with mock.patch.dict("os.environ", {"VIDEOSHORTS_SHARPEN": "0"}):
            self.assertEqual(qp.sharpen_filter(), "")


class ColorGradeTest(unittest.TestCase):
    def test_sdr_mild_grade(self) -> None:
        chain = qp.color_grade_filter(hdr=False)
        self.assertIn("eq=contrast=1.02:saturation=1.05", chain)
        self.assertNotIn("zscale", chain)

    def test_hdr_tonemap_chain(self) -> None:
        chain = qp.color_grade_filter(hdr=True)
        self.assertIn("zscale=tin=smpte2084", chain)
        self.assertIn("tonemap=hable", chain)
        self.assertIn("t=bt709", chain)
        self.assertTrue(chain.endswith("format=yuv420p"))

    def test_color_grade_disabled_by_env(self) -> None:
        with mock.patch.dict("os.environ", {"VIDEOSHORTS_COLOR_GRADE": "0"}):
            self.assertEqual(qp.color_grade_filter(hdr=True), "")
            self.assertEqual(qp.color_grade_filter(hdr=False), "")


class FpsCapTest(unittest.TestCase):
    def test_no_cap_below_limit(self) -> None:
        self.assertEqual(qp.fps_cap_filter(30.0), "")
        self.assertEqual(qp.fps_cap_filter(60.0), "")
        self.assertEqual(qp.fps_cap_filter(None), "")

    def test_cap_slowmo_source(self) -> None:
        self.assertEqual(qp.fps_cap_filter(120.0), "fps=60")
        self.assertEqual(qp.fps_cap_filter(240.0), "fps=60")


class FinishingChainTest(unittest.TestCase):
    def test_order_color_sharpen_fps(self) -> None:
        chain = qp.finishing_filters(hdr=True, fps=120.0)
        self.assertEqual(len(chain), 3)
        self.assertIn("tonemap", chain[0])
        self.assertIn("unsharp", chain[1])
        self.assertEqual(chain[2], "fps=60")

    def test_sdr_no_fps(self) -> None:
        chain = qp.finishing_filters(hdr=False, fps=30.0)
        self.assertEqual(chain, ["eq=contrast=1.02:saturation=1.05", "unsharp=5:5:0.6:5:5:0.0"])


class EncodeArgsTest(unittest.TestCase):
    def test_level_51(self) -> None:
        args = qp.video_encode_args("release")
        self.assertEqual(args[args.index("-level") + 1], "5.1")

    def test_release_bitrate_ceiling(self) -> None:
        args = qp.video_encode_args("release")
        self.assertIn("12M", args)
        self.assertIn("24M", args)

    def test_draft_bitrate_ceiling(self) -> None:
        args = qp.video_encode_args("draft")
        self.assertIn("5M", args)

    def test_faststart_present(self) -> None:
        args = qp.video_encode_args("release")
        self.assertIn("+faststart", args)


class ParseFpsTest(unittest.TestCase):
    def test_fraction(self) -> None:
        self.assertAlmostEqual(vsc._parse_fps("30000/1001"), 29.97, places=2)

    def test_plain_number(self) -> None:
        self.assertEqual(vsc._parse_fps("60"), 60.0)

    def test_zero_denominator(self) -> None:
        self.assertIsNone(vsc._parse_fps("0/0"))

    def test_garbage(self) -> None:
        self.assertIsNone(vsc._parse_fps("abc"))
        self.assertIsNone(vsc._parse_fps(None))
        self.assertIsNone(vsc._parse_fps(""))


class ProbeVideoInfoTest(unittest.TestCase):
    def _mock_proc(self, payload: dict) -> mock.Mock:
        proc = mock.Mock()
        proc.returncode = 0
        proc.stdout = json.dumps(payload)
        return proc

    def test_sdr_30fps(self) -> None:
        payload = {"streams": [{
            "avg_frame_rate": "30/1",
            "color_transfer": "bt709",
            "color_space": "bt709",
        }]}
        with mock.patch.object(subprocess, "run", return_value=self._mock_proc(payload)):
            info = vsc.probe_video_info(Path("fake.mp4"))
        self.assertEqual(info["fps"], 30.0)
        self.assertFalse(info["hdr"])

    def test_hdr_smpte2084(self) -> None:
        payload = {"streams": [{
            "avg_frame_rate": "60000/1001",
            "color_transfer": "smpte2084",
            "color_space": "bt2020nc",
        }]}
        with mock.patch.object(subprocess, "run", return_value=self._mock_proc(payload)):
            info = vsc.probe_video_info(Path("hdr.mp4"))
        self.assertTrue(info["hdr"])
        self.assertAlmostEqual(info["fps"], 59.94, places=2)

    def test_hlg_transfer(self) -> None:
        payload = {"streams": [{
            "avg_frame_rate": "25/1",
            "color_transfer": "arib-std-b67",
        }]}
        with mock.patch.object(subprocess, "run", return_value=self._mock_proc(payload)):
            info = vsc.probe_video_info(Path("hlg.mp4"))
        self.assertTrue(info["hdr"])

    def test_ffprobe_failure_safe_defaults(self) -> None:
        proc = mock.Mock()
        proc.returncode = 1
        proc.stdout = ""
        with mock.patch.object(subprocess, "run", return_value=proc):
            info = vsc.probe_video_info(Path("bad.mp4"))
        self.assertIsNone(info["fps"])
        self.assertFalse(info["hdr"])

    def test_timeout_safe(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("ffprobe", 60)):
            info = vsc.probe_video_info(Path("hang.mp4"))
        self.assertIsNone(info["fps"])
        self.assertFalse(info["hdr"])

    def test_empty_streams(self) -> None:
        with mock.patch.object(subprocess, "run", return_value=self._mock_proc({"streams": []})):
            info = vsc.probe_video_info(Path("audio_only.mp4"))
        self.assertIsNone(info["fps"])
        self.assertFalse(info["hdr"])


if __name__ == "__main__":
    unittest.main()
