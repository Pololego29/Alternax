"""
scrapers/france_travail.py
==========================
Source d'offres d'alternance via l'API officielle France Travail.

Contrairement aux autres scrapers du projet, ce module n'utilise PAS Playwright.
Il consomme l'API REST officielle de France Travail (ex-Pôle Emploi), qui est :
    - Gratuite et publique
    - Stable (pas de Cloudflare, pas de CAPTCHA)
    - Volumineuse (plusieurs milliers d'offres d'alternance)
    - Structurée (JSON propre)

Enrichissement ROME :
    Chaque offre est catégorisée par grand domaine professionnel à partir
    de son code ROME (1ère lettre du code). Aucun appel API supplémentaire :
    on utilise le mapping officiel des 14 grands domaines, stable depuis 20 ans.

Authentification : OAuth2 client credentials (un token est demandé à chaque run,
durée de vie ~24h).

Variables d'environnement requises :
    FT_CLIENT_ID      : Client ID de ton application France Travail
    FT_CLIENT_SECRET  : Client Secret associé

Création des credentials : https://francetravail.io → Mes applications

Dépendances : httpx (pip install httpx)

Utilisation rapide :
    python -m scrapers.france_travail
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path

import httpx

# On réutilise le modèle commun défini dans indeed.py pour rester cohérent
# avec les autres sources et le pipeline de déduplication.
from scrapers.indeed import JobOffer


# =============================================================================
# SECTION 1 – CONFIGURATION
# =============================================================================

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
API_URL   = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE     = "api_offresdemploiv2 o2dsoffre"

# Credentials chargés depuis l'environnement (jamais en dur dans le code)
CLIENT_ID     = os.environ.get("FT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("FT_CLIENT_SECRET", "")

# L'API renvoie max 150 résultats par requête, max 1000 résultats au total
PAGE_SIZE       = 150
DEFAULT_MAX     = 150
TIMEOUT_AUTH    = 10.0
TIMEOUT_REQUEST = 15.0

# Codes natureContrat pour l'alternance dans le référentiel France Travail :
#   E2 = Contrat d'apprentissage
#   FS = Contrat de professionnalisation
NATURE_CONTRAT_ALTERNANCE = "E2,FS"


# =============================================================================
# SECTION 2 – RÉFÉRENTIEL ROME (GRANDS DOMAINES)
# =============================================================================
# Les codes ROME sont structurés : 1 lettre (grand domaine) + 4 chiffres.
# Les 14 grands domaines sont stables et n'ont pas changé entre ROME v3 et v4.
# Source officielle : https://www.francetravail.org/opendata/repertoire-operationnel
# =============================================================================

ROME_GRANDS_DOMAINES = {
    "A": "Agriculture et espaces naturels",
    "B": "Arts et façonnage d'ouvrages d'art",
    "C": "Banque, assurance, immobilier",
    "D": "Commerce, vente et grande distribution",
    "E": "Communication, média et multimédia",
    "F": "Construction, bâtiment et travaux publics",
    "G": "Hôtellerie-restauration, tourisme, loisirs",
    "H": "Industrie",
    "I": "Installation et maintenance",
    "J": "Santé",
    "K": "Services à la personne et à la collectivité",
    "L": "Spectacle",
    "M": "Support à l'entreprise",
    "N": "Transport et logistique",
}


def get_grand_domaine(rome_code: str) -> str:
    """
    Extrait le grand domaine (libellé) à partir d'un code ROME.

    Ex. "M1802" → "Support à l'entreprise"
        "J1502" → "Santé"
        ""      → ""
    """
    if not rome_code:
        return ""
    return ROME_GRANDS_DOMAINES.get(rome_code[0].upper(), "")


# =============================================================================
# SECTION 3 – SOURCE PRINCIPALE
# =============================================================================

class FranceTravailSource:
    """
    Récupère les offres d'alternance via l'API France Travail.

    Workflow :
    1. Demande un access_token OAuth2 avec les credentials client
    2. Interroge l'endpoint /offres/search avec les filtres alternance
    3. Normalise chaque résultat brut JSON en objet JobOffer
    4. Enrichit chaque offre avec son grand domaine ROME (catégorie)
    """

    def __init__(self, query: str = "alternance", max_results: int = DEFAULT_MAX):
        self.query        = query
        self.max_results  = max_results
        self.offers: list[JobOffer] = []
        self.token: str | None = None

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        """
        Récupère un access_token OAuth2 via le flow client_credentials.
        """
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type":    "client_credentials",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope":         SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT_AUTH,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def _fetch_page(self, client: httpx.AsyncClient, start: int, end: int) -> list[dict]:
        """
        Récupère une tranche de résultats via l'API (range start-end inclusifs).
        """
        params = {
            "motsCles":      self.query,
            "natureContrat": NATURE_CONTRAT_ALTERNANCE,
            "range":         f"{start}-{end}",
        }
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            resp = await client.get(API_URL, params=params, headers=headers, timeout=TIMEOUT_REQUEST)
        except httpx.RequestError as e:
            print(f"  [warn] Erreur réseau : {e}")
            return []

        # L'API renvoie 200 si dernière page, 206 si page partielle, 204 si vide
        if resp.status_code in (200, 206):
            return resp.json().get("resultats", [])
        if resp.status_code == 204:
            return []

        print(f"  [warn] Statut HTTP inattendu : {resp.status_code} — {resp.text[:200]}")
        return []

    def _normalize(self, raw: dict) -> JobOffer:
        """
        Transforme une offre brute (JSON France Travail) en JobOffer enrichi.
        """
        # Salaire : peut être dans 'libelle' ou 'commentaire', ou absent
        salary = ""
        if raw.get("salaire"):
            salary = raw["salaire"].get("libelle") or raw["salaire"].get("commentaire") or ""

        # URL de l'offre : on essaie urlOrigine, sinon on reconstruit avec l'ID
        offer_id = raw.get("id", "")
        url = (raw.get("origineOffre") or {}).get("urlOrigine") or \
              (f"https://candidat.francetravail.fr/offres/recherche/detail/{offer_id}" if offer_id else "")

        # Type de contrat : libellé natureContrat ou typeContrat selon disponibilité
        contract_type = (
            raw.get("natureContratLibelle")
            or raw.get("typeContratLibelle")
            or "Alternance"
        )

        # Description tronquée à 500 caractères pour rester homogène avec les scrapers
        description = (raw.get("description") or "")[:500]

        # Enrichissement ROME : grand domaine à partir du romeCode
        rome_code = raw.get("romeCode", "") or ""
        category = get_grand_domaine(rome_code)

        return JobOffer(
            title=raw.get("intitule", "") or "",
            company=(raw.get("entreprise") or {}).get("nom", "") or "",
            location=(raw.get("lieuTravail") or {}).get("libelle", "") or "",
            contract_type=contract_type,
            salary=salary,
            description=description,
            url=url,
            source="france_travail",
            category=category,
        )

    async def run(self) -> list[JobOffer]:
        """
        Lance la récupération complète. Retourne la liste des JobOffer collectés.
        """
        if not CLIENT_ID or not CLIENT_SECRET:
            print("[france_travail] FT_CLIENT_ID ou FT_CLIENT_SECRET non défini — abandon")
            print("[france_travail] → Inscris-toi sur https://francetravail.io pour obtenir des credentials")
            return []

        print("[france_travail] Récupération du token OAuth2...")
        async with httpx.AsyncClient() as client:
            try:
                self.token = await self._get_token(client)
                print("[france_travail] Token obtenu, début de la récupération")
            except httpx.HTTPStatusError as e:
                print(f"[france_travail] Échec auth (HTTP {e.response.status_code}) : {e.response.text[:200]}")
                return []
            except Exception as e:
                print(f"[france_travail] Échec auth : {e}")
                return []

            # Pagination : on découpe en tranches de PAGE_SIZE jusqu'à max_results
            for start in range(0, self.max_results, PAGE_SIZE):
                end = min(start + PAGE_SIZE - 1, self.max_results - 1)
                print(f"[france_travail] Tranche {start}-{end}...")

                raw_offers = await self._fetch_page(client, start, end)
                if not raw_offers:
                    print(f"  [info] Aucune offre dans cette tranche — fin de la pagination")
                    break

                for raw in raw_offers:
                    try:
                        self.offers.append(self._normalize(raw))
                    except Exception as e:
                        print(f"  [warn] Erreur normalisation d'une offre : {e}")
                        continue

                print(f"  → {len(raw_offers)} offres récupérées")

                # Si on a reçu moins que PAGE_SIZE, on est sur la dernière page
                if len(raw_offers) < PAGE_SIZE:
                    break

        # Stats finales : répartition par grand domaine
        print(f"\n[france_travail] Collecte terminée : {len(self.offers)} offres au total")
        self._print_category_stats()

        return self.offers

    def _print_category_stats(self) -> None:
        """Affiche la répartition des offres par grand domaine ROME."""
        if not self.offers:
            return
        counts: dict[str, int] = {}
        for o in self.offers:
            counts[o.category or "(non catégorisé)"] = counts.get(o.category or "(non catégorisé)", 0) + 1
        print("[france_travail] Répartition par grand domaine :")
        for cat, n in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  - {cat:<50} {n:>4} offres")


# =============================================================================
# SECTION 4 – POINT D'ENTRÉE (test standalone)
# =============================================================================

async def main():
    """Lance la source seule pour tester (sans pipeline ni base)."""
    source = FranceTravailSource(query="alternance", max_results=150)
    offers = await source.run()

    if offers:
        print(f"\nExemple d'offre récupérée :")
        sample = offers[0]
        print(f"  Titre      : {sample.title}")
        print(f"  Entreprise : {sample.company}")
        print(f"  Lieu       : {sample.location}")
        print(f"  Contrat    : {sample.contract_type}")
        print(f"  Catégorie  : {sample.category}")
        print(f"  URL        : {sample.url}")


if __name__ == "__main__":
    asyncio.run(main())