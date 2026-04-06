"""
scrapers/indeed.py
==================
Scraper Indeed France pour les offres d'alternance.

Ce module utilise Playwright (navigateur headless) plutôt que requests/BeautifulSoup
car Indeed charge ses offres via JavaScript. Un simple GET HTTP ne retourne pas
les annonces — il faut un vrai navigateur.

Auteurs      : Groupax
Dépendances  : playwright (pip install playwright && playwright install chromium)
Sortie       : data/indeed_offers.csv  +  data/indeed_offers.json

Utilisation rapide :
    python scrapers/indeed.py
"""

import asyncio
import csv
import json
import random
import re
from dataclasses import dataclass, asdict, fields
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


# =============================================================================
# SECTION 1 – MODÈLE DE DONNÉES
# =============================================================================
# Ce dataclass est le format commun à TOUS les scrapers du projet.
# Chaque source (Indeed, HelloWork, APEC…) doit retourner des objets JobOffer.
# Cela facilite la déduplication et le traitement en pipeline.
# =============================================================================

@dataclass
class JobOffer:
    """Représente une offre d'alternance normalisée, quelle que soit la source."""
    title: str          # Intitulé du poste
    company: str        # Nom de l'entreprise
    location: str       # Ville / région
    contract_type: str  # Type de contrat (toujours "Alternance" ici)
    salary: str         # Rémunération si disponible, sinon ""
    description: str    # Extrait de la description
    url: str            # Lien vers l'offre complète
    source: str         # Identifiant de la source ("indeed", "hellowork"…)
    scraped_at: str     # Horodatage ISO 8601 de la collecte


# =============================================================================
# SECTION 2 – CONFIGURATION
# =============================================================================

BASE_URL  = "https://fr.indeed.com/jobs"
QUERY     = "alternance"      # Terme de recherche principal
LOCATION  = "France"          # Zone géographique
MAX_PAGES = 5                 # Nombre de pages à scraper (≈ 15 offres/page)

# Délai aléatoire entre chaque page (en secondes).
# Indispensable pour éviter d'être bloqué par Indeed.
DELAY_MIN = 2.0
DELAY_MAX = 4.5

# Dossier de sortie des fichiers CSV/JSON (relatif à la racine du projet)
OUTPUT_DIR = Path(__file__).parent.parent / "data"


# =============================================================================
# SECTION 3 – FONCTIONS UTILITAIRES
# =============================================================================

def build_search_url(query: str, location: str, page: int) -> str:
    """
    Construit l'URL de recherche Indeed pour une page donnée.

    Indeed utilise le paramètre `start` pour la pagination :
    page 0 → start=0, page 1 → start=15, page 2 → start=30, etc.

    Args:
        query    : Terme de recherche (ex: "alternance data")
        location : Ville ou région (ex: "Paris", "France")
        page     : Numéro de page (commence à 0)

    Returns:
        URL complète prête à être ouverte dans le navigateur
    """
    start = page * 15
    q = query.replace(" ", "+")
    l = location.replace(" ", "+")
    return f"{BASE_URL}?q={q}&l={l}&sort=date&start={start}"


def clean_text(text: str | None) -> str:
    """
    Nettoie une chaîne de caractères extraite du HTML.
    Supprime les espaces multiples, tabulations et sauts de ligne superflus.

    Args:
        text : Texte brut (peut être None si le sélecteur n'a rien trouvé)

    Returns:
        Texte nettoyé, ou "" si l'entrée est None/vide
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


# =============================================================================
# SECTION 4 – EXTRACTION D'UNE PAGE DE RÉSULTATS
# =============================================================================

async def extract_offers_from_page(page) -> list[JobOffer]:
    """
    Extrait toutes les offres présentes sur la page Indeed actuellement chargée.

    Indeed affiche les offres dans des "cards" (div.job_seen_beacon).
    Chaque card contient le titre, l'entreprise, la localisation, etc.

    Note : Indeed change régulièrement ses sélecteurs CSS.
    Si le scraper cesse de fonctionner, inspecter le DOM avec les DevTools
    et mettre à jour les sélecteurs ci-dessous.

    Args:
        page : Objet Playwright représentant l'onglet du navigateur

    Returns:
        Liste d'objets JobOffer extraits de la page
    """
    offers = []

    # --- Récupération des cards ---
    # Indeed structure ses résultats sous forme de cards indépendantes.
    # On essaie le sélecteur principal, puis un fallback si la mise en page a changé.
    cards = await page.query_selector_all("div.job_seen_beacon")
    if not cards:
        cards = await page.query_selector_all("li.css-5lfssm")

    if not cards:
        print("  [warn] Aucune card trouvée — sélecteurs à mettre à jour ou page bloquée")
        return offers

    # --- Traitement de chaque card ---
    for card in cards:
        try:
            # Extraction des éléments individuels de la card
            # query_selector retourne None si l'élément n'existe pas → géré par clean_text
            title_el    = await card.query_selector("h2.jobTitle span[title]")
            company_el  = await card.query_selector("span[data-testid='company-name']")
            location_el = await card.query_selector("div[data-testid='text-location']")
            salary_el   = await card.query_selector("div[data-testid='attribute_snippet_testid']")
            desc_el     = await card.query_selector("div.job-snippet")
            link_el     = await card.query_selector("a[data-jk]")  # data-jk = job key unique

            # Lecture des valeurs textuelles
            title    = clean_text(await title_el.get_attribute("title") if title_el else None)
            company  = clean_text(await company_el.inner_text() if company_el else None)
            location = clean_text(await location_el.inner_text() if location_el else None)
            salary   = clean_text(await salary_el.inner_text() if salary_el else None)
            desc     = clean_text(await desc_el.inner_text() if desc_el else None)

            # Construction de l'URL via le job key (plus stable que le href direct)
            job_key = await link_el.get_attribute("data-jk") if link_el else ""
            url = f"https://fr.indeed.com/viewjob?jk={job_key}" if job_key else ""

            # On ignore les cards sans titre (encarts publicitaires)
            if not title:
                continue

            offers.append(JobOffer(
                title=title,
                company=company,
                location=location,
                contract_type="Alternance",
                salary=salary,
                description=desc,
                url=url,
                source="indeed",
                scraped_at=datetime.now().isoformat(),
            ))

        except Exception as e:
            # On ne lève pas l'exception pour ne pas stopper le scraping
            # sur une seule card défaillante
            print(f"  [warn] Erreur extraction card : {e}")
            continue

    return offers


# =============================================================================
# SECTION 5 – SCRAPER PRINCIPAL
# =============================================================================

class IndeedScraper:
    """
    Orchestre le scraping complet d'Indeed sur plusieurs pages.

    Utilisation :
        scraper = IndeedScraper(query="alternance data", location="Paris", max_pages=3)
        offers  = await scraper.run()
        scraper.save_csv()
        scraper.save_json()
    """

    def __init__(self, query: str = QUERY, location: str = LOCATION, max_pages: int = MAX_PAGES):
        self.query     = query
        self.location  = location
        self.max_pages = max_pages
        self.offers: list[JobOffer] = []

    async def run(self) -> list[JobOffer]:
        """
        Lance le scraping sur toutes les pages configurées.

        Ouvre un navigateur Chromium headless, navigue page par page,
        attend le chargement des cards, puis extrait les offres.

        Returns:
            Liste complète des offres collectées (aussi stockée dans self.offers)
        """
        async with async_playwright() as p:
            # --- Lancement du navigateur ---
            # headless=True : pas d'interface graphique (plus rapide)
            # AutomationControlled désactivé : réduit la détection bot
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

            # --- Contexte navigateur réaliste ---
            # Un User-Agent générique + locale française réduit les blocages
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="fr-FR",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            # --- Boucle de pagination ---
            for page_num in range(self.max_pages):
                url = build_search_url(self.query, self.location, page_num)
                print(f"[indeed] Page {page_num + 1}/{self.max_pages} → {url}")

                try:
                    # Chargement de la page (timeout 30s)
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

                    # Attente explicite des cards avant d'extraire
                    # Si rien n'apparaît en 15s → Indeed bloque probablement la requête
                    await page.wait_for_selector(
                        "div.job_seen_beacon, li.css-5lfssm",
                        timeout=15_000,
                    )
                except PlaywrightTimeout:
                    print(f"  [warn] Timeout page {page_num + 1} – page ignorée")
                    continue

                # Extraction des offres de cette page
                page_offers = await extract_offers_from_page(page)
                print(f"  → {len(page_offers)} offres trouvées")
                self.offers.extend(page_offers)

                # Pause aléatoire entre les pages (sauf après la dernière)
                if page_num < self.max_pages - 1:
                    delay = random.uniform(DELAY_MIN, DELAY_MAX)
                    print(f"  → pause {delay:.1f}s...")
                    await asyncio.sleep(delay)

            await browser.close()

        print(f"\n[indeed] Collecte terminée : {len(self.offers)} offres au total")
        return self.offers

    # =========================================================================
    # SECTION 6 – EXPORT DES DONNÉES
    # =========================================================================

    def save_csv(self, filename: str = "indeed_offers.csv") -> Path:
        """
        Sauvegarde les offres dans un fichier CSV.

        Le CSV utilise les noms de champs du dataclass JobOffer comme en-têtes,
        ce qui garantit la cohérence avec les autres scrapers.

        Args:
            filename : Nom du fichier (créé dans OUTPUT_DIR)

        Returns:
            Chemin absolu du fichier créé
        """
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / filename
        fieldnames = [f.name for f in fields(JobOffer)]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(asdict(o) for o in self.offers)

        print(f"[indeed] CSV sauvegardé → {path}")
        return path

    def save_json(self, filename: str = "indeed_offers.json") -> Path:
        """
        Sauvegarde les offres dans un fichier JSON (pretty-printed, UTF-8).

        Utile pour l'inspection manuelle ou l'intégration avec d'autres outils.

        Args:
            filename : Nom du fichier (créé dans OUTPUT_DIR)

        Returns:
            Chemin absolu du fichier créé
        """
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(o) for o in self.offers], f, ensure_ascii=False, indent=2)

        print(f"[indeed] JSON sauvegardé → {path}")
        return path


# =============================================================================
# SECTION 7 – POINT D'ENTRÉE
# =============================================================================

async def main():
    """
    Point d'entrée principal du scraper.
    Modifiez les paramètres ici pour adapter la recherche.
    """
    scraper = IndeedScraper(
        query="alternance",   # Affinez avec "alternance data", "alternance web", etc.
        location="France",
        max_pages=5,          # 5 pages ≈ 75 offres
    )
    await scraper.run()
    scraper.save_csv()
    scraper.save_json()


if __name__ == "__main__":
    asyncio.run(main())
