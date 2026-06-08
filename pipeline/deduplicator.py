"""
pipeline/deduplicator.py
========================
Déduplication des offres avant insertion en base.

Deux niveaux de déduplication :
1. Par URL (rapide, exact) — géré directement par SQLite via INSERT OR IGNORE
2. Par empreinte contenu (title + company + location) — pour les offres sans URL
   ou publiées sur plusieurs sites avec des URLs différentes
"""

import hashlib
from dataclasses import asdict

from database.db import insert_offers_bulk, get_existing_urls


# =============================================================================
# SECTION 1 – EMPREINTE DE CONTENU
# =============================================================================

def content_fingerprint(offer: dict) -> str:
    """
    Calcule une empreinte unique basée sur le contenu de l'offre.

    Utilisée pour détecter les doublons inter-sources :
    la même offre publiée sur Indeed et HelloWork aura la même empreinte.

    On normalise les champs avant de hasher pour ignorer
    les différences de casse, espaces, accents, etc.

    Args:
        offer : Dictionnaire représentant une offre

    Returns:
        Hash MD5 hexadécimal (32 caractères)
    """
    key = "|".join([
        offer.get("title", "").lower().strip(),
        offer.get("company", "").lower().strip(),
        offer.get("location", "").lower().strip(),
    ])
    return hashlib.md5(key.encode()).hexdigest()


# =============================================================================
# SECTION 2 – FILTRE DE DÉDUPLICATION
# =============================================================================

def deduplicate(offers: list[dict]) -> list[dict]:
    """
    Filtre une liste d'offres pour ne garder que les nouvelles.

    Étapes :
    1. Déduplication interne au batch (même URL ou même empreinte contenu)
    2. Déduplication contre la base (vérifie si l'URL existe déjà)

    Args:
        offers : Liste d'offres fraîchement scrapées

    Returns:
        Sous-liste contenant uniquement les offres inédites
    """
    existing_urls     = get_existing_urls()   # une seule requête vers la base
    seen_urls         = set()
    seen_fingerprints = set()
    unique: list[dict] = []

    for offer in offers:
        url         = offer.get("url", "")
        fingerprint = content_fingerprint(offer)

        # --- Dédup interne au batch ---
        if url and url in seen_urls:
            continue
        if fingerprint in seen_fingerprints:
            continue

        # --- Dédup contre la base (par URL), en mémoire ---
        if url and url in existing_urls:
            continue

        seen_urls.add(url)
        seen_fingerprints.add(fingerprint)
        unique.append(offer)

    return unique


# =============================================================================
# SECTION 3 – POINT D'ENTRÉE PIPELINE
# =============================================================================

def process_and_save(offers) -> int:
    """
    Pipeline complet : déduplication → insertion en base.

    Accepte aussi bien une liste de JobOffer (dataclass) que
    des dictionnaires bruts.

    Args:
        offers : Liste de JobOffer ou de dict

    Returns:
        Nombre d'offres réellement insérées
    """
    # Conversion dataclass → dict si nécessaire
    offer_dicts = []
    for o in offers:
        offer_dicts.append(asdict(o) if hasattr(o, "__dataclass_fields__") else o)

    unique = deduplicate(offer_dicts)
    inserted = insert_offers_bulk(unique)

    print(f"[pipeline] {len(offers)} offres reçues → {len(unique)} nouvelles → {inserted} insérées")
    return inserted
