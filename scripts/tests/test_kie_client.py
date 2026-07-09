from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kie_client import KieClient


class Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class KieClientTests(unittest.TestCase):
    def test_image_task_uses_expected_model_and_result(self):
        requests = []
        replies = iter([
            {"code": 200, "msg": "success", "data": {"taskId": "image-task"}},
            {"code": 200, "msg": "success", "data": {"state": "success", "resultJson": '{"resultUrls":["https://example.test/a.png"]}'}},
        ])

        def opener(request, timeout):
            requests.append(request)
            return Response(next(replies))

        task_id, urls = KieClient("secret", opener=opener, sleep=lambda _: None).generate_image("diagram")
        self.assertEqual(task_id, "image-task")
        self.assertEqual(urls, ["https://example.test/a.png"])
        created = json.loads(requests[0].data.decode())
        self.assertEqual(created["model"], "gpt-image-2-text-to-image")
        self.assertEqual(created["input"]["aspect_ratio"], "9:16")
        self.assertNotIn("secret", created["input"]["prompt"])


if __name__ == "__main__":
    unittest.main()
