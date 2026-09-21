#!/usr/bin/env python3
"""Unit tests for TypeSafe Jev clip scoring (mocked HTTP, no live key)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from jev_score_clips import (  # noqa: E402
    build_clip_questions,
    build_scores_payload,
    map_jev_answers_to_clip,
    score_moments_file,
    score_to_100,
)
from typesafe_client import (  # noqa: E402
    TypeSafeApiError,
    TypeSafeClient,
    jev_scores_enabled,
    load_typesafe_api_key,
)
from validate_agent_artifacts import validate_clip_scores  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _mock_answers(
    *,
    hook: float = 3.0,
    virality: float = 2.8,
    quality: float = 3.2,
    pacing: float = 3.0,
    completeness: float = 3.5,
    reject: float = 0.1,
) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {
            "hook": {"type": "score", "score": hook, "confidence": 0.8},
            "virality": {"type": "score", "score": virality, "confidence": 0.7},
            "quality": {"type": "score", "score": quality, "confidence": 0.75},
            "pacing": {"type": "score", "score": pacing, "confidence": 0.7},
            "completeness": {"type": "score", "score": completeness, "confidence": 0.85},
            "should_reject": {"type": "noul", "noul": reject},
        },
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


class JevScoresEnabledTest(unittest.TestCase):
    def test_env_values(self) -> None:
        for value, expected in (("1", True), ("true", True), ("YES", True), ("0", False), ("", False)):
            self.assertIs(jev_scores_enabled({"VIDEOSHORTS_JEV_SCORES": value}), expected, value)


class ScoreMappingTest(unittest.TestCase):
    def test_score_to_100(self) -> None:
        self.assertEqual(score_to_100(0.0), 0)
        self.assertEqual(score_to_100(4.0), 100)
        self.assertEqual(score_to_100(2.0), 50)
        self.assertEqual(score_to_100(3.2), 80)

    def test_map_pass(self) -> None:
        clip = map_jev_answers_to_clip(
            index=1,
            start=10.0,
            end=50.0,
            duration=40.0,
            min_sec=30.0,
            max_sec=60.0,
            answers=_mock_answers()["answers"],
            model="jev-1.13.0",
        )
        self.assertEqual(clip["status"], "PASS")
        self.assertIsNone(clip["reject_reason"])
        self.assertEqual(clip["hook_score"], 75)
        self.assertGreaterEqual(clip["quality_score"], 40)

    def test_map_low_quality_requires_reject_reason(self) -> None:
        clip = map_jev_answers_to_clip(
            index=1,
            start=0.0,
            end=40.0,
            duration=40.0,
            min_sec=30.0,
            max_sec=60.0,
            answers=_mock_answers(quality=1.2, completeness=1.0, reject=0.8)["answers"],
        )
        self.assertEqual(clip["status"], "REJECT")
        self.assertTrue(clip["reject_reason"])
        self.assertLess(clip["quality_score"], 40)

    def test_questions_shape(self) -> None:
        qs = build_clip_questions()
        self.assertEqual(qs["hook"]["type"], "score")
        self.assertEqual(len(qs["hook"]["criteria"]), 5)
        self.assertEqual(qs["should_reject"]["type"], "noul")


class TypeSafeClientTest(unittest.TestCase):
    def test_system_one_posts_expected_body(self) -> None:
        requests = []
        replies = iter([_mock_answers()])

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse(next(replies))

        client = TypeSafeClient("test-secret-key", opener=opener, base_url="https://example.test")
        result = client.system_one(
            {"transcript_excerpt": "Тест хука и payoff."},
            build_clip_questions(),
        )
        self.assertEqual(result["model"], "jev-1.13.0")
        self.assertIn("hook", result["answers"])
        body = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["questions"]["hook"]["type"], "score")
        self.assertNotIn("test-secret-key", body["state"] if isinstance(body["state"], str) else json.dumps(body))
        auth = requests[0].headers.get("Authorization") or requests[0].headers.get("authorization")
        self.assertTrue(str(auth).startswith("Bearer "))

    def test_401_maps_to_safe_error(self) -> None:
        from urllib.error import HTTPError
        from io import BytesIO

        def opener(request, timeout):
            raise HTTPError(
                url="https://example.test/v1/systemone",
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=BytesIO(b'{"error":"bad key"}'),
            )

        client = TypeSafeClient("bad", opener=opener, base_url="https://example.test")
        with self.assertRaises(TypeSafeApiError) as ctx:
            client.system_one("x", {"a": {"type": "noul", "instructions": "y"}})
        self.assertNotIn("bad", str(ctx.exception).lower())


class EndToEndMockedTest(unittest.TestCase):
    def test_score_moments_validates(self) -> None:
        moments = {
            "clips": [
                {
                    "index": 1,
                    "start": 12.0,
                    "end": 52.0,
                    "hook": "Почему 90% теряют деньги на старте",
                    "payoff_ending": "Поэтому сначала проверьте юнит-экономику.",
                    "transcript_excerpt": (
                        "Почему 90% теряют деньги на старте. "
                        "Они считают выручку, а не маржу. "
                        "Поэтому сначала проверьте юнит-экономику."
                    ),
                    "editorial_rationale": "Сильный мифбаст с payoff.",
                    "semantic_boundary_evidence": {
                        "why_start": "Вопрос-хук.",
                        "why_end": "Чёткий вывод.",
                        "transcript_excerpt": "…",
                    },
                    "cleanup_risks": [],
                    "do_not_cut": [],
                }
            ]
        }
        transcript = {
            "segments": [
                {"start": 12.0, "end": 20.0, "text": "Почему 90% теряют деньги на старте."},
                {"start": 20.0, "end": 35.0, "text": "Они считают выручку, а не маржу."},
                {"start": 35.0, "end": 52.0, "text": "Поэтому сначала проверьте юнит-экономику."},
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            moments_path = root / "moments.json"
            transcript_path = root / "transcript.json"
            out_path = root / "clip-scores.json"
            moments_path.write_text(json.dumps(moments, ensure_ascii=False), encoding="utf-8")
            transcript_path.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

            def opener(request, timeout):
                return FakeResponse(_mock_answers())

            with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "unit-test-key"}):
                payload = score_moments_file(
                    moments_path,
                    transcript_path,
                    min_sec=30.0,
                    max_sec=60.0,
                    opener=opener,
                    authored_by="videoshorts-editor",
                )
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertEqual(payload["decision_source"], "agent")
            self.assertEqual(payload["authored_by"], "videoshorts-editor")
            self.assertEqual(payload["scoring_engine"], "jev")
            ok, errors = validate_clip_scores(out_path)
            self.assertTrue(ok, errors)

    def test_stamp_payload_fields(self) -> None:
        payload = build_scores_payload(
            moments_path=Path("/tmp/m.json"),
            transcript_path=Path("/tmp/t.json"),
            clips_scores=[
                {
                    "index": 1,
                    "hook_score": 70,
                    "virality_score": 65,
                    "quality_score": 72,
                    "pacing_score": 60,
                    "completeness_score": 80,
                    "status": "PASS",
                    "reject_reason": None,
                }
            ],
        )
        self.assertEqual(payload["scoring_engine"], "jev")
        self.assertEqual(payload["decision_source"], "agent")


class LoadKeyTest(unittest.TestCase):
    def test_load_from_local_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "videoshorts.local.env").write_text(
                "TYPESAFE_API_KEY=from-file\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TYPESAFE_API_KEY", None)
                self.assertEqual(load_typesafe_api_key(root), "from-file")


if __name__ == "__main__":
    unittest.main()
