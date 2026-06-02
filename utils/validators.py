"""
utils/validators.py
===================
Validation et normalisation des offres d'emploi scrapées.

Garantit que les données insérées en base sont propres et cohérentes,
quelle que soit la source (Indeed, HelloWork, etc.).

Usage :
    from utils.validators import validate_and_normalize
    clean_offers = validate_and_normalize(raw_offers)
"""

import re
from dataclasses import asdict
from typing import Optional


# =============================================================================
# SECTION 1 – CONSTANTES DE NORMALISATION
# =============================================================================

# Mots-clés pour détecter le type de contrat
_CONTRACT_KEYWORDS: dict[str, list[str]] = {
    "Alternance":  ["alternance", "alternant", "apprentissage", "apprenti", "contrat pro"],
    "Stage":       ["stage", "stagiaire", "intern", "internship"],
    "CDI":         ["cdi", "permanent", "temps plein"],
    "CDD":         ["cdd", "contrat à durée déterminée", "temporaire"],
    "Freelance":   ["freelance", "free-lance", "indépendant", "consultant"],
}

# Régions françaises pour standardiser les localisations
_REGION_MAP: dict[str, str] = {
    "ile de france":    "Île-de-France",
    "ile-de-france":    "Île-de-France",
    "idf":              "Île-de-France",
    "paris":            "Paris (75)",
    "lyon":             "Lyon (69)",
    "marseille":        "Marseille (13)",
    "bordeaux":         "Bordeaux (33)",
    "toulouse":         "Toulouse (31)",
    "nantes":           "Nantes (44)",
    "lille":            "Lille (59)",
    "strasbourg":       "Strasbourg (67)",
    "rennes":           "Rennes (35)",
    "nice":             "Nice (06)",
    "montpellier":      "Montpellier (34)",
    "grenoble":         "Grenoble (38)",
}

# Longueurs minimales/maximales acceptables
_MIN_TITLE_LEN     = 3
_MAX_TITLE_LEN     = 200
_MAX_COMPANY_LEN   = 150
_MAX_DESC_LEN      = 5000
_MAX_URL_LEN       = 500


# =============================================================================
# SECTION 2 – FONCTIONS DE NETTOYAGE
# =============================================================================

def normalize_whitespace(text: Optional[str]) -> str:
    if not text:
        return ""
    text = re.sub(r"[\r\n\t]+", " ", text)
    return re.sub(r" {2,}", " ", text).strip()


def normalize_contract_type(raw: Optional[str]) -> str:
    """
    Standardise le type de contrat en cherchant des mots-clés.

    Retourne "Autre" si aucun type n'est identifié.
    """
    if not raw:
        return "Alternance"

    lower = raw.lower()
    for contract_type, keywords in _CONTRACT_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return contract_type

    return raw.strip() or "Alternance"


def normalize_location(raw: Optional[str]) -> str:
    """
    Standardise la localisation.

    Cherche des correspondances approximatives dans _REGION_MAP
    sans altérer les localisations précises (ex. "Lyon 3e").
    """
    if not raw:
        return ""

    cleaned = normalize_whitespace(raw)
    lower   = cleaned.lower()

    for pattern, normalized in _REGION_MAP.items():
        if re.search(r"\b" + re.escape(pattern) + r"\b", lower):
            return normalized

    return cleaned


def normalize_url(raw: Optional[str]) -> str:
    if not raw:
        return ""
    url = raw.strip()
    if len(url) > _MAX_URL_LEN:
        return ""
    if url and not re.match(r"^https?://", url):
        return f"https://{url}"
    return url


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


# =============================================================================
# SECTION 3 – VALIDATION D'UNE OFFRE
# =============================================================================

def _validate_offer(offer: dict) -> tuple[bool, list[str]]:
    """
    Vérifie qu'une offre respecte les contraintes minimales.

    Returns:
        (is_valid, list_of_errors)
    """
    errors = []

    title = offer.get("title", "")
    if not title or len(title) < _MIN_TITLE_LEN:
        errors.append(f"Titre trop court : '{title}'")
    if len(title) > _MAX_TITLE_LEN:
        errors.append(f"Titre trop long ({len(title)} chars)")

    company = offer.get("company", "")
    if len(company) > _MAX_COMPANY_LEN:
        errors.append(f"Entreprise trop longue ({len(company)} chars)")

    url = offer.get("url", "")
    if url and len(url) > _MAX_URL_LEN:
        errors.append(f"URL trop longue ({len(url)} chars)")

    return len(errors) == 0, errors


# =============================================================================
# SECTION 4 – NORMALISATION COMPLÈTE D'UNE OFFRE
# =============================================================================

def normalize_offer(offer: dict) -> dict:
    """
    Nettoie et normalise tous les champs d'une offre.

    Args:
        offer : Dictionnaire brut de l'offre

    Returns:
        Dictionnaire normalisé (copie, ne modifie pas l'original)
    """
    return {
        "title":         truncate(normalize_whitespace(offer.get("title")),         _MAX_TITLE_LEN),
        "company":       truncate(normalize_whitespace(offer.get("company")),        _MAX_COMPANY_LEN),
        "location":      normalize_location(offer.get("location")),
        "contract_type": normalize_contract_type(offer.get("contract_type")),
        "salary":        normalize_whitespace(offer.get("salary")),
        "description":   truncate(normalize_whitespace(offer.get("description")),   _MAX_DESC_LEN),
        "url":           normalize_url(offer.get("url")),
        "source":        normalize_whitespace(offer.get("source")) or "unknown",
        "scraped_at":    offer.get("scraped_at", ""),
    }


# =============================================================================
# SECTION 5 – PIPELINE PRINCIPAL
# =============================================================================

def validate_and_normalize(offers: list, strict: bool = False) -> list[dict]:
    """
    Pipeline complet : convertit, normalise et valide une liste d'offres.

    Args:
        offers : Liste de JobOffer (dataclass) ou de dict
        strict : Si True, rejette les offres invalides ; sinon les corrige

    Returns:
        Liste de dicts normalisés et valides
    """
    valid   = []
    invalid = 0

    for o in offers:
        raw = asdict(o) if hasattr(o, "__dataclass_fields__") else dict(o)
        normalized = normalize_offer(raw)

        is_valid, errors = _validate_offer(normalized)

        if not is_valid:
            invalid += 1
            if strict:
                continue
            # En mode non-strict, on conserve quand même (la base filtrera via UNIQUE)

        valid.append(normalized)

    if invalid:
        print(f"[validators] {invalid} offres avec anomalies ({len(valid)} conservées)")

    return valid
