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
    title: str
    company: str
    location: str
    contract_type: str
    salary: str
    description: str
    url: str
    source: str
    # Utilisation de default_factory pour avoir l'heure exacte à l'instanciation
    scraped_at: str = None 

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now().isoformat()


# =============================================================================
# SECTION 2 – CONFIGURATION
# =============================================================================

BASE_URL  = "https://fr.indeed.com"
QUERY     = "alternance"
LOCATION  = "France"
MAX_PAGES = 5           # Nombre de pages à scraper (≈ 15 offres/page)
MAX_RETRY = 2           # Tentatives par page en cas d'échec

# Délais entre pages (en secondes) — plus longs = moins de détection bot
DELAY_MIN = 5.0
DELAY_MAX = 9.0

# Timeouts Playwright (en millisecondes)
TIMEOUT_GOTO     = 60_000   # Chargement d'une page
TIMEOUT_SELECTOR = 30_000   # Attente d'un sélecteur CSS

OUTPUT_DIR = Path(__file__).parent.parent / "data"

# User-Agents réalistes — on en pioche un au hasard à chaque session
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


# =============================================================================
# SECTION 3 – FONCTIONS UTILITAIRES
# =============================================================================

def clean_text(text: str | None) -> str:
    """Nettoie une chaîne HTML : supprime espaces multiples et sauts de ligne."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


async def human_scroll(page, steps: int = 4) -> None:
    """
    Simule un défilement humain sur la page.

    Instead of jumping straight to the bottom, on défile progressivement
    avec des pauses courtes — comportement typique d'un utilisateur qui lit.

    Args:
        page  : Objet Playwright
        steps : Nombre de paliers de défilement
    """
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(300, 600))
        await asyncio.sleep(random.uniform(0.3, 0.8))


async def is_blocked(page) -> bool:
    """
    Détecte si Indeed a affiché une page de blocage / CAPTCHA.

    Indeed peut rediriger vers une page de vérification quand il détecte
    un comportement automatisé. On vérifie le titre et le contenu.

    Returns:
        True si la page semble être un blocage, False sinon
    """
    title = await page.title()
    keywords = ["captcha", "robot", "vérification", "verification", "blocked", "access denied"]
    return any(k in title.lower() for k in keywords)


# =============================================================================
# SECTION 4 – EXTRACTION D'UNE PAGE DE RÉSULTATS
# =============================================================================

async def extract_offers_from_page(page) -> list[JobOffer]:
    """
    Extrait toutes les offres présentes sur la page Indeed actuellement chargée.
    Modifié par Ikram : Ajout de logs de suivi et sécurisation des sélecteurs.
    Note : Indeed change régulièrement ses sélecteurs CSS.
    Si le scraper cesse de fonctionner, inspecter le DOM avec les DevTools
    et mettre à jour les sélecteurs ci-dessous.

    Args:
        page : Objet Playwright représentant l'onglet du navigateur

    Returns:
        Liste d'objets JobOffer extraits de la page
    """
    offers = []

  # Sélecteurs principaux + fallback si Indeed change sa structure
    cards = await page.query_selector_all("div.job_seen_beacon")
    
    # --- DÉBUT MODIFICATION IKRAM : Tracking de l'extraction ---
    if cards:
        print(f"  [debug] {len(cards)} cartes d'offres détectées (sélecteur principal).")
    else:
        cards = await page.query_selector_all("li.css-5lfssm")
        if cards:
            print(f"  [debug] {len(cards)} cartes d'offres détectées (sélecteur secondaire).")
    # --- FIN MODIFICATION ---

    if not cards:
        print("  [warn] Aucune card trouvée — sélecteurs à mettre à jour ou page bloquée")
        return offers

    for card in cards:
        try:
            title_el    = await card.query_selector("h2.jobTitle span[title]")
            company_el  = await card.query_selector("span[data-testid='company-name']")
            location_el = await card.query_selector("div[data-testid='text-location']")
            salary_el   = await card.query_selector("div[data-testid='attribute_snippet_testid']")
            desc_el     = await card.query_selector("div.job-snippet")
            link_el     = await card.query_selector("a[data-jk]")

            title    = clean_text(await title_el.get_attribute("title") if title_el else None)
            company  = clean_text(await company_el.inner_text() if company_el else None)
            location = clean_text(await location_el.inner_text() if location_el else None)
            salary   = clean_text(await salary_el.inner_text() if salary_el else None)
            desc     = clean_text(await desc_el.inner_text() if desc_el else None)

            job_key = await link_el.get_attribute("data-jk") if link_el else ""
            url = f"https://fr.indeed.com/viewjob?jk={job_key}" if job_key else ""

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
            print(f"  [warn] Erreur extraction card : {e}")
            continue

    return offers


# =============================================================================
# SECTION 5 – SCRAPER PRINCIPAL
# =============================================================================

class IndeedScraper:
    """
    Orchestre le scraping complet d'Indeed sur plusieurs pages.

    Stratégie anti-détection :
    - Warm-up sur la page d'accueil avant de chercher
    - Navigation via le bouton "Suivant" (plus naturel que des URLs directes)
    - Scroll humain sur chaque page
    - Délais aléatoires longs entre les pages
    - Retry automatique en cas d'échec
    - Rotation des User-Agents
    """

    def __init__(self, query: str = QUERY, location: str = LOCATION, max_pages: int = MAX_PAGES):
        self.query     = query
        self.location  = location
        self.max_pages = max_pages
        self.offers: list[JobOffer] = []

    async def _warmup(self, page) -> None:
        """
        Visite la page d'accueil d'Indeed avant de lancer la recherche.

        Indeed est plus suspicieux quand un navigateur arrive directement
        sur une URL de recherche sans historique. Ce warm-up simule un
        utilisateur qui ouvre le site normalement.
        """
        print("[indeed] Warm-up sur fr.indeed.com...")
        try:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=TIMEOUT_GOTO)
            await asyncio.sleep(random.uniform(1.5, 3.0))
            await human_scroll(page, steps=2)
        except PlaywrightTimeout:
            print("  [warn] Warm-up timeout – on continue quand même")

    async def _load_page_with_retry(self, page, url: str, page_num: int) -> bool:
        """
        Charge une page de résultats avec retry automatique.

        En cas de timeout ou de page bloquée, attend un délai plus long
        et retente jusqu'à MAX_RETRY fois avant d'abandonner.

        Args:
            page     : Objet Playwright
            url      : URL à charger
            page_num : Numéro de page (pour les logs)

        Returns:
            True si la page est chargée et valide, False si échec définitif
        """
        for attempt in range(1, MAX_RETRY + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_GOTO)
                await page.wait_for_selector(
                    "div.job_seen_beacon, li.css-5lfssm",
                    timeout=TIMEOUT_SELECTOR,
                )

                if await is_blocked(page):
                    print(f"  [warn] Page bloquée (tentative {attempt}/{MAX_RETRY})")
                    await asyncio.sleep(random.uniform(10, 20))
                    continue

                return True

            except PlaywrightTimeout:
                print(f"  [warn] Timeout page {page_num + 1} (tentative {attempt}/{MAX_RETRY})")
                if attempt < MAX_RETRY:
                    wait = random.uniform(8, 15)
                    print(f"  → attente {wait:.1f}s avant retry...")
                    await asyncio.sleep(wait)

        return False

    async def _go_to_next_page(self, page) -> bool:
        """
        Clique sur le bouton "Suivant" de la pagination Indeed.

        Naviguer via le bouton est plus naturel qu'une URL directe.
        Indeed surveille les sauts de pagination trop rapides.

        Returns:
            True si le clic a réussi, False si le bouton n'existe pas (dernière page)
        """
        try:
            next_btn = await page.query_selector('a[data-testid="pagination-page-next"]')
            if not next_btn:
                print("  [info] Pas de bouton Suivant — dernière page atteinte")
                return False

            await next_btn.scroll_into_view_if_needed()
            await asyncio.sleep(random.uniform(0.5, 1.2))
            await next_btn.click()

            await page.wait_for_selector(
                "div.job_seen_beacon, li.css-5lfssm",
                timeout=TIMEOUT_SELECTOR,
            )
            return True

        except PlaywrightTimeout:
            print("  [warn] Timeout après clic Suivant")
            return False
        except Exception as e:
            print(f"  [warn] Erreur navigation Suivant : {e}")
            return False

    async def run(self) -> list[JobOffer]:
        """
        Lance le scraping sur toutes les pages configurées.

        Workflow :
        1. Warm-up sur la page d'accueil
        2. Chargement de la première page de résultats
        3. Extraction + scroll humain
        4. Navigation via bouton Suivant (pages 2 et suivantes)
        5. Répétition jusqu'à MAX_PAGES ou dernière page

        Returns:
            Liste complète des offres collectées
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # False = moins détectable par Indeed
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="fr-FR",
                viewport={
                    "width": random.randint(1200, 1400),
                    "height": random.randint(750, 900),
                },
                # Désactive les headers qui trahissent l'automatisation
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            )
            page = await context.new_page()

            # Masque navigator.webdriver (propriété détectée par les anti-bots)
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            # --- Warm-up ---
            await self._warmup(page)

            # --- Page 1 : chargement via URL directe ---
            first_url = (
                f"{BASE_URL}/jobs?q={self.query.replace(' ', '+')}"
                f"&l={self.location.replace(' ', '+')}&sort=date"
            )
            print(f"\n[indeed] Page 1/{self.max_pages} → {first_url}")

            if not await self._load_page_with_retry(page, first_url, 0):
                print("[indeed] Impossible de charger la page 1 — abandon")
                await browser.close()
                return self.offers

            await human_scroll(page)
            page_offers = await extract_offers_from_page(page)
            print(f"  → {len(page_offers)} offres trouvées")
            self.offers.extend(page_offers)

            # --- Pages 2+ : navigation via bouton Suivant ---
            for page_num in range(1, self.max_pages):
                delay = random.uniform(DELAY_MIN, DELAY_MAX)
                print(f"  → pause {delay:.1f}s...")
                await asyncio.sleep(delay)

                print(f"[indeed] Page {page_num + 1}/{self.max_pages} → clic Suivant")
                success = await self._go_to_next_page(page)
                if not success:
                    break

                if await is_blocked(page):
                    print("  [warn] Page bloquée après navigation — arrêt")
                    break

                await human_scroll(page)
                page_offers = await extract_offers_from_page(page)
                print(f"  → {len(page_offers)} offres trouvées")
                self.offers.extend(page_offers)

            await browser.close()

        print(f"\n[indeed] Collecte terminée : {len(self.offers)} offres au total")
        return self.offers

    # =========================================================================
    # SECTION 6 – EXPORT DES DONNÉES
    # =========================================================================

    def save_csv(self, filename: str = "indeed_offers.csv") -> Path:
        """Sauvegarde les offres en CSV dans OUTPUT_DIR."""
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
        """Sauvegarde les offres en JSON pretty-printed dans OUTPUT_DIR."""
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
    scraper = IndeedScraper(
        query="alternance",
        location="France",
        max_pages=5,
    )
    await scraper.run()
    scraper.save_csv()
    scraper.save_json()


if __name__ == "__main__":
    asyncio.run(main())
