from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_agent_artifacts import validate_editorial_bundle, validate_moments


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _agent(clips: list[dict], author: str) -> dict:
    return {
        "schema_version": 1,
        "decision_source": "agent",
        "authored_by": author,
        "clips": clips,
    }


def _moment(index: int, start: float, end: float) -> dict:
    return {
        "index": index,
        "start": start,
        "end": end,
        "hook": "Сильный хук",
        "payoff_ending": "Чёткий вывод",
        "transcript_excerpt": "Самостоятельная мысль с полезным выводом.",
        "editorial_rationale": "Зритель сразу понимает пользу и получает payoff.",
        "semantic_boundary_evidence": {
            "why_start": "Первое самостоятельное предложение.",
            "why_end": "Мысль завершена.",
            "finished_thought_gate": "pass",
        },
        "cleanup_risks": [],
        "do_not_cut": [],
        "estimated_duration_after_cleanup": end - start,
    }


def _decision(index: int) -> dict:
    return {
        "index": index,
        "selected_by_agent": True,
        "why_this_moment": "Самостоятельный полезный тезис.",
        "hook_assessment": {"score": 80},
        "viral_hypothesis": "Практический инсайт сохраняют коллегам.",
        "thought_start_evidence": "Старт на самостоятельном предложении.",
        "thought_end_evidence": "Финальный вывод.",
        "cleanup_applied": False,
        "cut_instruction": {"start": 0, "end": 60},
        "reject_if": ["нет payoff"],
        "confidence": 0.8,
    }


class EditorialContractTests(unittest.TestCase):
    def test_moments_require_cleanup_intent(self) -> None:
        payload = _agent([_moment(1, 0, 60)], "videoshorts-moment-finder")
        payload["clips"][0].pop("cleanup_risks")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source-moments.json"
            _write(path, payload)
            ok, errors = validate_moments(path)
        self.assertFalse(ok)
        self.assertTrue(any("cleanup_risks" in error for error in errors))

    def test_editorial_bundle_accepts_coherent_keep(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            moment = _moment(1, 0, 62)
            _write(root / "source-moments.json", _agent([moment], "videoshorts-moment-finder"))
            _write(root / "refined-moments.json", _agent([moment], "videoshorts-boundary-refiner"))
            _write(root / "clip-scores.json", _agent([{
                "index": 1, "hook_score": 80, "virality_score": 75, "quality_score": 80,
                "pacing_score": 75, "completeness_score": 90, "status": "PASS",
            }], "videoshorts-editor"))
            _write(root / "editor-review.json", _agent([{
                "index": 1, "keep": True, "editor_notes": "Уникальный тезис.",
                "duplicate_theme": False, "theme_fingerprint": "Практический метод.",
            }], "videoshorts-editor"))
            _write(root / "virality-review.json", _agent([{
                "index": 1, "shareability": 70, "comment_trigger": 60, "curiosity_gap": 70,
                "save_value": 80, "virality_score": 75, "status": "PASS",
            }], "videoshorts-editor"))
            _write(root / "clip-decisions.json", _agent([_decision(1)], "videoshorts-boundary-refiner"))
            _write(root / "montage-plan.json", _agent([{
                "index": 1, "jump_cuts": [], "silence_remove": {"items": []},
                "filler_remove": {"items": []}, "glue_notes": "",
                "do_not_cut_before": 0, "estimated_duration_after_cleanup": 62,
                "status": "READY_FOR_CUTTER",
            }], "videoshorts-boundary-refiner"))
            ok, errors = validate_editorial_bundle(root)
        self.assertTrue(ok, errors)

    def test_editorial_bundle_rejects_temporal_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = _moment(1, 0, 62)
            duplicate = _moment(2, 30, 90)
            for name, author, clips in (
                ("source-moments.json", "videoshorts-moment-finder", [base, duplicate]),
                ("refined-moments.json", "videoshorts-boundary-refiner", [base, duplicate]),
            ):
                _write(root / name, _agent(clips, author))
            scores = [{"index": index, "hook_score": 80, "virality_score": 75, "quality_score": 80,
                       "pacing_score": 75, "completeness_score": 90, "status": "PASS"} for index in (1, 2)]
            editor = [{"index": index, "keep": True, "editor_notes": "Уникальный.",
                       "duplicate_theme": False, "theme_fingerprint": f"Тезис {index}"} for index in (1, 2)]
            viral = [{"index": index, "shareability": 70, "comment_trigger": 60, "curiosity_gap": 70,
                      "save_value": 80, "virality_score": 75, "status": "PASS"} for index in (1, 2)]
            montage = [{"index": index, "jump_cuts": [], "silence_remove": {"items": []},
                        "filler_remove": {"items": []}, "glue_notes": "", "do_not_cut_before": 0,
                        "estimated_duration_after_cleanup": 60, "status": "READY_FOR_CUTTER"} for index in (1, 2)]
            _write(root / "clip-scores.json", _agent(scores, "videoshorts-editor"))
            _write(root / "editor-review.json", _agent(editor, "videoshorts-editor"))
            _write(root / "virality-review.json", _agent(viral, "videoshorts-editor"))
            _write(root / "clip-decisions.json", _agent([_decision(1), _decision(2)], "videoshorts-boundary-refiner"))
            _write(root / "montage-plan.json", _agent(montage, "videoshorts-boundary-refiner"))
            ok, errors = validate_editorial_bundle(root)
        self.assertFalse(ok)
        self.assertTrue(any("overlap exceeds 3s" in error for error in errors))

    def test_editorial_bundle_requires_cleanup_risk_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            moment = _moment(1, 0, 62)
            moment["cleanup_risks"] = [{
                "type": "false_start", "start": 20, "end": 22,
                "action": "remove", "reason": "Повтор фразы.",
            }]
            _write(root / "source-moments.json", _agent([moment], "videoshorts-moment-finder"))
            _write(root / "refined-moments.json", _agent([moment], "videoshorts-boundary-refiner"))
            _write(root / "clip-scores.json", _agent([{
                "index": 1, "hook_score": 80, "virality_score": 75, "quality_score": 80,
                "pacing_score": 75, "completeness_score": 90, "status": "PASS",
            }], "videoshorts-editor"))
            _write(root / "editor-review.json", _agent([{
                "index": 1, "keep": True, "editor_notes": "Уникальный тезис.",
                "duplicate_theme": False, "theme_fingerprint": "Практический метод.",
            }], "videoshorts-editor"))
            _write(root / "virality-review.json", _agent([{
                "index": 1, "shareability": 70, "comment_trigger": 60, "curiosity_gap": 70,
                "save_value": 80, "virality_score": 75, "status": "PASS",
            }], "videoshorts-editor"))
            _write(root / "clip-decisions.json", _agent([_decision(1)], "videoshorts-boundary-refiner"))
            _write(root / "montage-plan.json", _agent([{
                "index": 1, "jump_cuts": [], "silence_remove": {"items": []},
                "filler_remove": {"items": []}, "glue_notes": "",
                "do_not_cut_before": 0, "estimated_duration_after_cleanup": 62,
                "status": "READY_FOR_CUTTER",
            }], "videoshorts-boundary-refiner"))
            ok, errors = validate_editorial_bundle(root)
        self.assertFalse(ok)
        self.assertTrue(any("cleanup remove risk not resolved" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
