#!/usr/bin/env python3
"""Тесты agent_gate: gate-решения, uniform durations, env-флаги."""

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

import agent_gate


def _full_decision(index: int, *, selected: bool = True) -> dict:
    return {
        "index": index,
        "selected_by_agent": selected,
        "why_this_moment": "Тезис",
        "hook_assessment": {"score": 80},
        "viral_hypothesis": "Инсайт",
        "thought_start_evidence": "Старт",
        "thought_end_evidence": "Конец",
        "cleanup_applied": False,
        "cut_instruction": {"start": 0, "end": 60},
        "reject_if": ["нет payoff"],
        "confidence": 0.8,
    }


def _write_decisions(root: Path, payload: dict) -> None:
    path = agent_gate.decisions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class AgentModeEnabledTest(unittest.TestCase):
    def test_flag_overrides_env(self) -> None:
        with mock.patch.dict(os.environ, {"VIDEOSHORTS_AGENT_MODE": "0"}):
            self.assertTrue(agent_gate.agent_mode_enabled(True))
        with mock.patch.dict(os.environ, {"VIDEOSHORTS_AGENT_MODE": "1"}):
            self.assertFalse(agent_gate.agent_mode_enabled(False))

    def test_env_values(self) -> None:
        for value, expected in (("1", True), ("true", True), ("agent", True), ("0", False), ("", False)):
            with mock.patch.dict(os.environ, {"VIDEOSHORTS_AGENT_MODE": value}):
                self.assertIs(agent_gate.agent_mode_enabled(None), expected, value)


class EvaluateAgentDecisionsTest(unittest.TestCase):
    def test_agent_payload_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_decisions(root, {
                "decision_source": "agent",
                "clips": [_full_decision(1)],
                "summary": {"needs_agent_confirmation": False},
            })
            report = agent_gate.evaluate_agent_decisions(root, require_agent=True)
            self.assertTrue(report["ok"], report["issues"])
            self.assertEqual(report["selected_by_agent"], 1)

    def test_missing_file_fails_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report = agent_gate.evaluate_agent_decisions(Path(td), require_agent=True)
            self.assertFalse(report["ok"])
            self.assertIn("clip_decisions_missing", report["issues"])

    def test_local_heuristic_draft_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_decisions(root, {
                "decision_source": "local_heuristic_draft",
                "clips": [_full_decision(1)],
            })
            report = agent_gate.evaluate_agent_decisions(root, require_agent=True)
            self.assertFalse(report["ok"])
            self.assertIn("decision_source_local_heuristic_draft", report["issues"])

    def test_no_selection_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_decisions(root, {
                "decision_source": "agent",
                "clips": [_full_decision(1, selected=False)],
            })
            report = agent_gate.evaluate_agent_decisions(root, require_agent=True)
            self.assertFalse(report["ok"])
            self.assertIn("no_selected_by_agent", report["issues"])

    def test_missing_fields_fail(self) -> None:
        decision = _full_decision(1)
        decision.pop("confidence")
        decision.pop("cut_instruction")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_decisions(root, {"decision_source": "agent", "clips": [decision]})
            report = agent_gate.evaluate_agent_decisions(root, require_agent=True)
            self.assertFalse(report["ok"])
            self.assertTrue(any(i.startswith("missing_decision_fields") for i in report["issues"]))
            self.assertTrue(any("confidence" in f for f in report["missing_fields"]))

    def test_needs_confirmation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_decisions(root, {
                "decision_source": "agent",
                "clips": [_full_decision(1)],
                "summary": {"needs_agent_confirmation": True},
            })
            report = agent_gate.evaluate_agent_decisions(root, require_agent=True)
            self.assertFalse(report["ok"])
            self.assertIn("needs_agent_confirmation", report["issues"])

    def test_not_required_always_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report = agent_gate.evaluate_agent_decisions(Path(td), require_agent=False)
            self.assertTrue(report["ok"])


class UniformDurationsTest(unittest.TestCase):
    def test_few_clips_ok(self) -> None:
        clips = [{"duration": 60.0}] * 4
        report = agent_gate.evaluate_uniform_durations(clips, min_count=5)
        self.assertTrue(report["ok"])
        self.assertFalse(report["uniform"])

    def test_uniform_detected(self) -> None:
        clips = [{"duration": 60.0}, {"duration": 60.5}, {"duration": 59.5},
                 {"duration": 60.2}, {"duration": 59.8}]
        report = agent_gate.evaluate_uniform_durations(clips, min_count=5, tolerance=2.0)
        self.assertTrue(report["uniform"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["issue"], "uniform_algorithmic_durations")

    def test_varied_ok(self) -> None:
        clips = [{"duration": 30.0}, {"duration": 45.0}, {"duration": 62.0},
                 {"duration": 55.0}, {"duration": 38.0}]
        report = agent_gate.evaluate_uniform_durations(clips, min_count=5)
        self.assertFalse(report["uniform"])
        self.assertTrue(report["ok"])

    def test_bad_duration_values_skipped(self) -> None:
        # "bad" пропускается (ValueError), None/отсутствие -> 0.0 (or 0)
        clips = [{"duration": "bad"}, {"duration": None}, {}, {"duration": 60.0}]
        report = agent_gate.evaluate_uniform_durations(clips, min_count=5)
        self.assertTrue(report["ok"])
        self.assertEqual(report["durations"], [0.0, 0.0, 60.0])


class GateMessageTest(unittest.TestCase):
    def test_message_mentions_contract(self) -> None:
        message = agent_gate.gate_message({"issues": ["x"]})
        self.assertIn("clip-decisions.json", message)
        self.assertIn("x", message)


if __name__ == "__main__":
    unittest.main()
