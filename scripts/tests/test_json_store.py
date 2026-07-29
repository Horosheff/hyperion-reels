from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import json_store


class JsonStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="vs_json_store_"))
        self.target = self.tmpdir / "state.json"

    def test_write_then_read_roundtrip(self) -> None:
        payload = {"status": "PASS", "clips": [1, 2, 3], "title": "клип"}
        json_store.write_json(self.target, payload)
        self.assertEqual(json_store.read_json(self.target), payload)
        self.assertFalse((self.tmpdir / f"{self.target.name}.{0}.tmp").exists())

    def test_read_missing_returns_default(self) -> None:
        self.assertEqual(json_store.read_json(self.target), {})
        self.assertEqual(json_store.read_json(self.target, default=None), None)

    def test_read_corrupted_returns_default_not_raises(self) -> None:
        self.target.write_text("{broken json", encoding="utf-8")
        self.assertEqual(json_store.read_json(self.target), {})
        self.assertEqual(json_store.read_json(self.target, default={"fallback": True}), {"fallback": True})

    def test_write_creates_parent_dirs(self) -> None:
        nested = self.tmpdir / "a" / "b" / "state.json"
        json_store.write_json(nested, {"ok": True})
        self.assertTrue(nested.is_file())

    def test_update_json_concurrent_increment(self) -> None:
        json_store.write_json(self.target, {"counter": 0})

        def bump(_: dict) -> dict:
            data = json_store.read_json(self.target)
            data["counter"] = int(data.get("counter") or 0) + 1
            return data

        threads = [threading.Thread(target=json_store.update_json, args=(self.target, bump)) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        final = json_store.read_json(self.target)
        self.assertEqual(final["counter"], 20)

    def test_update_json_mutator_none_keeps_in_place_edit(self) -> None:
        json_store.write_json(self.target, {"items": []})

        def append_item(data: dict) -> None:
            data.setdefault("items", []).append("clip_01")

        json_store.update_json(self.target, append_item)
        self.assertEqual(json_store.read_json(self.target)["items"], ["clip_01"])

    def test_write_text_atomic(self) -> None:
        md = self.tmpdir / "note.md"
        json_store.write_text_atomic(md, "# привет\n")
        self.assertEqual(md.read_text(encoding="utf-8"), "# привет\n")

    def test_lock_file_created_and_reusable(self) -> None:
        with json_store.file_lock(self.target):
            pass
        lock_path = self.tmpdir / f"{self.target.name}.lock"
        self.assertTrue(lock_path.is_file())
        with json_store.file_lock(self.target, timeout=5):
            pass


if __name__ == "__main__":
    unittest.main()
