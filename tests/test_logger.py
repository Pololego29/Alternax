"""Tests unitaires pour utils/logger.py"""

import logging

import pytest
from utils.logger import get_logger, log_session_summary, _loggers


# =============================================================================
# get_logger
# =============================================================================

class TestGetLogger:
    def setup_method(self):
        # Nettoie le cache de loggers entre chaque test
        _loggers.clear()
        # Supprime les handlers des loggers Python existants
        for name in list(logging.Logger.manager.loggerDict):
            if name.startswith("test_"):
                logging.getLogger(name).handlers.clear()

    def test_returns_logger_instance(self):
        logger = get_logger("test_basic")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_matches(self):
        logger = get_logger("test_name")
        assert logger.name == "test_name"

    def test_default_level_is_info(self):
        logger = get_logger("test_level_default")
        assert logger.level == logging.INFO

    def test_custom_level_debug(self):
        logger = get_logger("test_level_debug", level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_same_name_returns_same_instance(self):
        a = get_logger("test_singleton")
        b = get_logger("test_singleton")
        assert a is b

    def test_different_names_return_different_instances(self):
        a = get_logger("test_diff_a")
        b = get_logger("test_diff_b")
        assert a is not b

    def test_has_console_handler(self):
        logger = get_logger("test_handlers")
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_no_propagation(self):
        logger = get_logger("test_propagate")
        assert logger.propagate is False

    def test_file_handler_created(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        logger = get_logger("test_file", log_to_file=True, log_dir="logs")
        has_file = any(isinstance(h, logging.FileHandler) for h in logger.handlers)
        assert has_file

    def test_log_file_exists_on_disk(self, tmp_path, monkeypatch):
        import os
        monkeypatch.chdir(tmp_path)
        get_logger("test_disk", log_to_file=True, log_dir="logs")
        log_dir = tmp_path / "logs"
        assert log_dir.exists()
        log_files = list(log_dir.glob("test_disk_*.log"))
        assert len(log_files) == 1


# =============================================================================
# log_session_summary
# =============================================================================

class TestLogSessionSummary:
    def test_does_not_raise(self):
        logger = get_logger("test_summary")
        stats = {
            "query":             "alternance",
            "location":          "France",
            "started_at":        "2024-01-01T10:00:00",
            "ended_at":          "2024-01-01T10:02:00",
            "duration_seconds":  120.0,
            "pages_scraped":     5,
            "pages_blocked":     0,
            "offers_total":      50,
            "offers_new":        45,
            "offers_duplicates": 5,
        }
        log_session_summary(logger, stats)

    def test_handles_empty_stats(self):
        logger = get_logger("test_empty_summary")
        log_session_summary(logger, {})

    def test_handles_partial_stats(self):
        logger = get_logger("test_partial_summary")
        log_session_summary(logger, {"query": "test", "offers_total": 10})
