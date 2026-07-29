#!/usr/bin/env python3
"""Тесты vs_logging: файловый логгер, идемпотентность, env-настройки."""

from __future__ import annotations

import logging
import logging.handlers
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import vs_logging


class VsLoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._names: list[str] = []
        self._dirs: list[str] = []
        self._patchers: list[mock._patch] = []

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        for name in self._names:
            logger = logging.getLogger(f"videoshorts.{name}")
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            vs_logging._CONFIGURED.discard(logger.name)
        for directory in self._dirs:
            shutil.rmtree(directory, ignore_errors=True)

    def _logger(self, name: str, *, level: str | None = None) -> logging.Logger:
        directory = tempfile.mkdtemp(prefix="vs-log-test-")
        self._dirs.append(directory)
        env = {"VIDEOSHORTS_LOG_DIR": directory}
        if level is not None:
            env["VIDEOSHORTS_LOG_LEVEL"] = level
        patcher = mock.patch.dict("os.environ", env)
        patcher.start()
        self._patchers.append(patcher)
        self._names.append(name)
        return vs_logging.get_logger(name)

    def test_writes_to_file(self) -> None:
        logger = self._logger("t_write")
        logger.info("hello-file")
        for handler in logger.handlers:
            handler.flush()
        content = (Path(self._dirs[0]) / "t_write.log").read_text(encoding="utf-8")
        self.assertIn("hello-file", content)
        self.assertIn("videoshorts.t_write", content)

    def test_idempotent_no_duplicate_handlers(self) -> None:
        name = "t_idem"
        directory = tempfile.mkdtemp(prefix="vs-log-test-")
        self._dirs.append(directory)
        patcher = mock.patch.dict("os.environ", {"VIDEOSHORTS_LOG_DIR": directory})
        patcher.start()
        self._patchers.append(patcher)
        self._names.append(name)
        first = vs_logging.get_logger(name)
        second = vs_logging.get_logger(name)
        self.assertIs(first, second)
        self.assertEqual(len(first.handlers), 2)

    def test_namespaced_and_no_propagation(self) -> None:
        logger = self._logger("t_ns")
        self.assertEqual(logger.name, "videoshorts.t_ns")
        self.assertFalse(logger.propagate)

    def test_log_level_env(self) -> None:
        logger = self._logger("t_level", level="DEBUG")
        self.assertEqual(logger.level, logging.DEBUG)

    def test_invalid_level_falls_back_to_info(self) -> None:
        logger = self._logger("t_badlevel", level="bogus")
        self.assertEqual(logger.level, logging.INFO)

    def test_console_handler_warning_only(self) -> None:
        logger = self._logger("t_console")
        stream_handlers = [
            h for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        self.assertEqual(len(stream_handlers), 1)
        self.assertEqual(stream_handlers[0].level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
