"""
utils/logger.py
===============
Logger structuré pour les scrapers Alternax.

Fournit un logger coloré en console et optionnellement en fichier.
Chaque scraper instancie son propre logger via get_logger(name).

Usage :
    from utils.logger import get_logger
    log = get_logger("indeed")
    log.info("Démarrage du scraping")
    log.warning("Page bloquée")
    log.error("Timeout sur la page 3")
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


# =============================================================================
# SECTION 1 – COULEURS ANSI
# =============================================================================

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREY   = "\033[90m"
_CYAN   = "\033[96m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_PURPLE = "\033[95m"

_LEVEL_COLORS = {
    "DEBUG":    _GREY,
    "INFO":     _GREEN,
    "WARNING":  _YELLOW,
    "ERROR":    _RED,
    "CRITICAL": _PURPLE,
}


# =============================================================================
# SECTION 2 – FORMATTER COLORÉ
# =============================================================================

class _ColorFormatter(logging.Formatter):
    """Formatte les logs avec couleurs ANSI pour la console."""

    def format(self, record: logging.LogRecord) -> str:
        color  = _LEVEL_COLORS.get(record.levelname, _RESET)
        ts     = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        name   = f"{_CYAN}{record.name:<12}{_RESET}"
        level  = f"{color}{record.levelname:<8}{_RESET}"
        msg    = record.getMessage()

        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)

        return f"{_GREY}{ts}{_RESET} {name} {level} {msg}"


class _PlainFormatter(logging.Formatter):
    """Formatte les logs sans couleurs pour les fichiers."""

    def format(self, record: logging.LogRecord) -> str:
        ts    = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        msg   = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return f"{ts} | {record.name:<12} | {record.levelname:<8} | {msg}"


# =============================================================================
# SECTION 3 – FACTORY PRINCIPALE
# =============================================================================

_loggers: dict[str, logging.Logger] = {}

def get_logger(
    name:       str,
    level:      str  = "INFO",
    log_to_file: bool = False,
    log_dir:    str  = "logs",
) -> logging.Logger:
    """
    Retourne un logger configuré pour le scraper donné.

    Args:
        name        : Identifiant du scraper (ex. "indeed", "hellowork")
        level       : Niveau de log (DEBUG, INFO, WARNING, ERROR)
        log_to_file : Si True, écrit aussi dans logs/<name>_YYYY-MM-DD.log
        log_dir     : Répertoire pour les fichiers de log

    Returns:
        Logger Python standard configuré
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    # Handler console
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_ColorFormatter())
    logger.addHandler(console)

    # Handler fichier (optionnel)
    if log_to_file or os.getenv("SCRAPER_LOG_FILE", "").lower() in ("1", "true"):
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        date_str  = datetime.now().strftime("%Y-%m-%d")
        file_path = Path(log_dir) / f"{name}_{date_str}.log"
        fh = logging.FileHandler(file_path, encoding="utf-8")
        fh.setFormatter(_PlainFormatter())
        logger.addHandler(fh)

    _loggers[name] = logger
    return logger


# =============================================================================
# SECTION 4 – LOGGER DE SESSION (résumé de fin de scrape)
# =============================================================================

def log_session_summary(logger: logging.Logger, stats: dict) -> None:
    """
    Affiche un résumé formaté des statistiques de scraping.

    Args:
        logger : Logger à utiliser
        stats  : Dictionnaire de stats retourné par IndeedScraper.stats
    """
    sep = "─" * 50
    logger.info(sep)
    logger.info("RÉSUMÉ DE SESSION")
    logger.info(f"  Query        : {stats.get('query', '—')}")
    logger.info(f"  Location     : {stats.get('location', '—')}")
    logger.info(f"  Démarré      : {stats.get('started_at', '—')}")
    logger.info(f"  Terminé      : {stats.get('ended_at', '—')}")
    logger.info(f"  Durée        : {stats.get('duration_seconds', 0):.1f}s")
    logger.info(f"  Pages scrapées : {stats.get('pages_scraped', 0)}")
    logger.info(f"  Pages bloquées : {stats.get('pages_blocked', 0)}")
    logger.info(f"  Offres totales : {stats.get('offers_total', 0)}")
    logger.info(f"  Nouvelles      : {stats.get('offers_new', 0)}")
    logger.info(f"  Doublons       : {stats.get('offers_duplicates', 0)}")
    logger.info(sep)
