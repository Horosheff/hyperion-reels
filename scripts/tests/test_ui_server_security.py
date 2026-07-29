from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ui_server


class OriginGateTest(unittest.TestCase):
    def test_missing_origin_allowed(self) -> None:
        self.assertTrue(ui_server.origin_host_allowed(""))

    def test_localhost_origins_allowed(self) -> None:
        for origin in (
            "http://127.0.0.1:8765",
            "http://localhost:8765",
            "http://[::1]:8765",
            "http://127.0.0.1:9999/upload",
        ):
            self.assertTrue(ui_server.origin_host_allowed(origin), origin)

    def test_foreign_origins_rejected(self) -> None:
        for origin in (
            "https://evil.example.com",
            "http://192.168.1.50:8765",
            "https://127.0.0.1.evil.com",
            "null",
        ):
            self.assertFalse(ui_server.origin_host_allowed(origin), origin)


class ServeDenyTest(unittest.TestCase):
    def test_secrets_and_env_denied(self) -> None:
        root = ui_server.PLUGIN_ROOT
        for denied in (
            root / "videoshorts.local.env",
            root / "videoshorts-memory" / "secrets" / "vk_storage_state.json",
            root / ".git" / "config",
        ):
            self.assertTrue(ui_server._serve_denied(denied), str(denied))

    def test_regular_ui_files_allowed(self) -> None:
        for allowed in (
            ui_server.UI_DIR / "videoshorts-upload.html",
            ui_server.UI_DIR / "hyperion-mark.png",
        ):
            self.assertFalse(ui_server._serve_denied(allowed), str(allowed))


class PathConfinementTest(unittest.TestCase):
    def test_ui_traversal_parts_detected(self) -> None:
        # do_GET rejects any /ui/ relative path containing ".."
        self.assertIn("..", Path("../videoshorts.local.env").parts)
        self.assertNotIn("..", Path("videoshorts-upload.html").parts)

    def test_traversal_resolves_outside_ui_dir(self) -> None:
        malicious = ui_server.UI_DIR / ".." / "videoshorts.local.env"
        resolved = malicious.resolve()
        self.assertFalse(ui_server._is_relative_to(resolved, ui_server.UI_DIR))

    def test_legit_file_inside_ui_dir(self) -> None:
        legit = ui_server.UI_DIR / "videoshorts-upload.html"
        self.assertTrue(ui_server._is_relative_to(legit.resolve(), ui_server.UI_DIR))

    def test_media_confined_to_memory_root(self) -> None:
        outside = Path("C:/Windows/System32/drivers/etc/hosts")
        self.assertFalse(ui_server._is_relative_to(outside, ui_server.MEMORY_ROOT))
        inside = ui_server.MEMORY_ROOT / "output" / "clips" / "demo" / "clip_01.mp4"
        self.assertTrue(ui_server._is_relative_to(inside, ui_server.MEMORY_ROOT))


class TimeoutConfigTest(unittest.TestCase):
    def test_timeouts_are_positive(self) -> None:
        self.assertGreater(ui_server.PUBLISH_TIMEOUT, 0)
        self.assertGreater(ui_server.LOGIN_TIMEOUT, 0)
        self.assertGreater(ui_server.COVERS_TIMEOUT, 0)
        self.assertGreater(ui_server.QUEUE_TIMEOUT, 0)


if __name__ == "__main__":
    unittest.main()
