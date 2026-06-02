"""
scrapers/letudiant.py
=====================
Source d'offres d'alternance via l'API tRPC interne de L'Étudiant.fr.

Repérée dans le Network tab du navigateur, l'API est publique (aucune
authentification requise) et retourne directement le JSON des offres,
sans avoir à parser du HTML ni à exécuter du JavaScript. C'est :
    - Rapide      (~200ms par appel)
    - Stable      (l'API change moins souvent que le HTML)
    - Riche       (titre, entreprise, lieu, catégorie déjà structurés)
    - Sans Playwright

Endpoint  : GET /api/trpc/jobInfinite.getMediaJobsInfinite
Format    : tRPC batch (?batch=1&input={"0":{"json":{...}}})
Pagination: par curseur, via le champ `nextCursor` de la réponse.

Utilisation rapide :
    python -m scrapers.letudiant
"""

import asyncio
import json
from collections import Counter

import httpx

from scrapers.indeed import JobOffer


# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_URL = "https://jobs-stages.letudiant.fr"
API_PATH = "/api/trpc/jobInfinite.getMediaJobsInfinite"

# Identifiants repérés dans la requête réelle du site
MEDIA_ID            = "66229d6f878dc9f2bf192806"   # L'Étudiant chez Piloty
CONTRACT_ALTERNANCE = "627d16c172f9aba0dccfb00d"   # contrat alternance

DEFAULT_LIMIT     = 50    # le site utilise 6, mais 50 marche aussi
DEFAULT_MAX_PAGES = 20    # 20 × 50 = ~1000 offres max
TIMEOUT_REQUEST   = 20.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


# =============================================================================
# CONSTRUCTION DU PAYLOAD tRPC
# =============================================================================

def build_input(cursor: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """
    Construit le dict `input` au format tRPC batch.
    Le cursor n'est passé qu'à partir de la 2ème page.
    """
    payload = {
        "limit": limit,
        "media_id": MEDIA_ID,
        "language": "fr",
        "pertinence": True,
        "contracts": [CONTRACT_ALTERNANCE],
        "direction": "forward",
    }
    if cursor:
        payload["cursor"] = cursor
    return {"0": {"json": payload}}


# =============================================================================
# NORMALISATION VERS JobOffer
# =============================================================================

def normalize_offer(raw: dict) -> JobOffer:
    """Convertit une offre brute de l'API en JobOffer."""
    name    = raw.get("name", "")
    company = raw.get("companyName", "")

    # Lieu : ville + région (quand dispo)
    loc = raw.get("location") or {}
    if isinstance(loc, dict):
        city   = loc.get("city", "") or ""
        region = loc.get("administrative_area_region", "") or ""
        parts  = [p for p in (city, region) if p]
        location = ", ".join(parts)
    else:
        location = ""

    contract_type = raw.get("contract") or "Alternance"
    category      = raw.get("category", "") or ""

    salary = raw.get("salary") or ""
    if not isinstance(salary, str):
        salary = ""

    # URL : reconstruite depuis le public_id (slug de l'offre)
    public_id = raw.get("public_id", "")
    url = f"{BASE_URL}/offres/{public_id}" if public_id else ""

    # Description : l'API ne renvoie pas la description complète sur la liste.
    # On synthétise depuis les métadonnées disponibles.
    desc_parts = []
    if category:
        desc_parts.append(f"Catégorie : {category}")
    if raw.get("experience"):
        desc_parts.append(f"Expérience : {raw['experience']}")
    if raw.get("education"):
        desc_parts.append(f"Niveau : {raw['education']}")
    description = " | ".join(desc_parts)

    return JobOffer(
        title=name,
        company=company,
        location=location,
        contract_type=contract_type,
        salary=salary,
        description=description,
        url=url,
        source="letudiant",
        category=category,
    )


# =============================================================================
# SOURCE
# =============================================================================

class LEtudiantSource:
    """
    Source L'Étudiant.fr — utilise l'API tRPC publique du site, avec pagination
    par curseur. Aucune authentification requise.
    """

    def __init__(self, max_pages: int = DEFAULT_MAX_PAGES, limit: int = DEFAULT_LIMIT):
        self.max_pages = max_pages
        self.limit     = limit
        self.offers: list[JobOffer] = []

    async def _fetch_page(self, client: httpx.AsyncClient, cursor: str | None) -> dict | None:
        """Récupère une page de l'API tRPC."""
        # json.dumps compact (sans espaces) pour matcher le format du site
        input_json = json.dumps(
            build_input(cursor=cursor, limit=self.limit),
            separators=(",", ":"),
        )

        try:
            resp = await client.get(
                f"{BASE_URL}{API_PATH}",
                params={"batch": "1", "input": input_json},
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                    "Accept-Language": "fr-FR,fr;q=0.9",
                    "Referer": f"{BASE_URL}/offres/contrat-alternance",
                },
                timeout=TIMEOUT_REQUEST,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            print(f"  [warn] Erreur HTTP : {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"  [warn] Réponse non-JSON : {e}")
            return None

    @staticmethod
    def _extract_payload(response) -> dict:
        """
        Récupère le bloc utile dans la réponse tRPC batch.
        Structure attendue :
            [{"result": {"data": {"json": {"items": [...], "nextCursor": ..., "total": ...}}}}]
        """
        if not isinstance(response, list) or not response:
            return {}
        try:
            return response[0]["result"]["data"]["json"] or {}
        except (KeyError, TypeError):
            return {}

    async def run(self) -> list[JobOffer]:
        print(f"[letudiant] Démarrage (max {self.max_pages} pages × {self.limit} offres)")

        cursor: str | None = None
        async with httpx.AsyncClient() as client:
            for page in range(1, self.max_pages + 1):
                print(f"[letudiant] Page {page}/{self.max_pages}...")

                response = await self._fetch_page(client, cursor)
                if not response:
                    print(f"  [warn] Pas de réponse, arrêt")
                    break

                payload = self._extract_payload(response)
                items   = payload.get("items", [])
                cursor  = payload.get("nextCursor")
                total   = payload.get("total", 0)

                if not items:
                    print(f"  [info] Aucun item, fin de la pagination")
                    break

                # Normalisation
                normalized = []
                for raw in items:
                    try:
                        normalized.append(normalize_offer(raw))
                    except Exception as e:
                        print(f"  [warn] Normalisation : {e}")
                        continue

                self.offers.extend(normalized)
                print(f"  → {len(normalized)} offres (accumulé : {len(self.offers)} / {total} disponibles)")

                # Plus de cursor = on a tout vidé
                if not cursor:
                    print(f"  [info] Pas de nextCursor, fin de la pagination")
                    break

                # politesse : on évite de marteler l'API
                await asyncio.sleep(0.5)

        print(f"\n[letudiant] Collecte terminée : {len(self.offers)} offres")

        # Stats par catégorie (diversité)
        if self.offers:
            cats = Counter(o.category or "(non catégorisé)" for o in self.offers)
            print(f"[letudiant] Top 10 catégories :")
            for cat, n in cats.most_common(10):
                print(f"  - {cat:<40} {n} offres")

        return self.offers


# =============================================================================
# POINT D'ENTRÉE (test standalone)
# =============================================================================

async def main():
    source = LEtudiantSource(max_pages=5)
    offers = await source.run()

    if offers:
        print(f"\nExemple d'offre récupérée :")
        s = offers[0]
        print(f"  Titre      : {s.title}")
        print(f"  Entreprise : {s.company}")
        print(f"  Lieu       : {s.location}")
        print(f"  Contrat    : {s.contract_type}")
        print(f"  Catégorie  : {s.category}")
        print(f"  URL        : {s.url}")


if __name__ == "__main__":
    asyncio.run(main())