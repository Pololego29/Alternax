"""
utils/exporters.py
==================
Utilitaires d'export pour les offres scrapées.

Permet d'exporter en CSV et JSON pour debug, archivage ou analyse.

Usage :
    from utils.exporters import export_csv, export_json
    export_csv(offers, "data/offers_2024-01-15.csv")
    export_json(offers, "data/offers_2024-01-15.json")
"""

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path


# =============================================================================
# SECTION 1 – HELPERS INTERNES
# =============================================================================

def _to_dicts(offers: list) -> list[dict]:
    """Convertit dataclasses ou dicts en liste de dicts."""
    result = []
    for o in offers:
        result.append(asdict(o) if hasattr(o, "__dataclass_fields__") else dict(o))
    return result


def _ensure_dir(filepath: str) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)


def _default_path(ext: str, prefix: str = "offers") -> str:
    """Génère un chemin horodaté dans data/ si aucun chemin fourni."""
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join("data", f"{prefix}_{date_str}.{ext}")


# =============================================================================
# SECTION 2 – EXPORT CSV
# =============================================================================

_CSV_FIELDS = [
    "title", "company", "location", "contract_type",
    "salary", "description", "url", "source", "scraped_at",
]

def export_csv(offers: list, filepath: str = "", delimiter: str = ";") -> str:
    """
    Exporte les offres en fichier CSV.

    Args:
        offers    : Liste de JobOffer ou de dict
        filepath  : Chemin de sortie (auto-généré si vide)
        delimiter : Séparateur CSV (défaut : ";")

    Returns:
        Chemin absolu du fichier créé
    """
    if not filepath:
        filepath = _default_path("csv")

    _ensure_dir(filepath)
    rows = _to_dicts(offers)

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=_CSV_FIELDS,
            delimiter=delimiter,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    abs_path = os.path.abspath(filepath)
    print(f"[exporters] CSV exporté → {abs_path} ({len(rows)} lignes)")
    return abs_path


# =============================================================================
# SECTION 3 – EXPORT JSON
# =============================================================================

def export_json(offers: list, filepath: str = "", indent: int = 2) -> str:
    """
    Exporte les offres en fichier JSON.

    Args:
        offers   : Liste de JobOffer ou de dict
        filepath : Chemin de sortie (auto-généré si vide)
        indent   : Indentation JSON (défaut : 2)

    Returns:
        Chemin absolu du fichier créé
    """
    if not filepath:
        filepath = _default_path("json")

    _ensure_dir(filepath)
    rows = _to_dicts(offers)

    payload = {
        "exported_at": datetime.now().isoformat(),
        "total":       len(rows),
        "offers":      rows,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=indent)

    abs_path = os.path.abspath(filepath)
    print(f"[exporters] JSON exporté → {abs_path} ({len(rows)} offres)")
    return abs_path


# =============================================================================
# SECTION 4 – EXPORT AUTOMATIQUE SELON VARIABLE D'ENVIRONNEMENT
# =============================================================================

def auto_export(offers: list, prefix: str = "offers") -> list[str]:
    """
    Exporte selon SCRAPER_EXPORT_FORMATS (csv, json, ou les deux).

    Variable : SCRAPER_EXPORT_FORMATS=csv,json  (défaut : aucun export)

    Args:
        offers : Liste d'offres à exporter
        prefix : Préfixe du nom de fichier

    Returns:
        Liste des chemins créés
    """
    formats_env = os.getenv("SCRAPER_EXPORT_FORMATS", "")
    formats     = [f.strip().lower() for f in formats_env.split(",") if f.strip()]

    if not formats:
        return []

    created = []
    if "csv" in formats:
        created.append(export_csv(offers, _default_path("csv", prefix)))
    if "json" in formats:
        created.append(export_json(offers, _default_path("json", prefix)))

    return created
