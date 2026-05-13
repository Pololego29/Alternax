"""
scrapers/hellowork.py
=====================
Scraper HelloWork France pour les offres d'alternance.

HelloWork charge ses offres côté serveur (HTML statique),
ce qui permet d'utiliser des requêtes HTTP simples via httpx
plutôt que Playwright — plus rapide et moins détectable.

Lancer via : python -m scrapers.run_scraper

Variables d'environnement :
    SCRAPER_QUERY       : Requête de recherche (défaut : "alternance")
    SCRAPER_LOCATION    : Localisation (défaut : "france")
    SCRAPER_MAX_PAGES   : Nombre de pages (défaut : 5)
    HW_DELAY_MIN        : Délai minimum entre pages en secondes (défaut : 3.0)
    HW_DELAY_MAX        : Délai maximum entre pages en secondes (défaut : 6.0)
"""

import asyncio
import os
import random
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime
from urllib.parse import urlencode, quote_plus

import httpx
from bs4 import BeautifulSoup


# =============================================================================
# SECTION 1 – MODÈLE DE DONNÉES
# =============================================================================

@dataclass
class JobOffer:
    """Représente une offre d'alternance normalisée (compatible IndeedScraper)."""
    title:         str
    company:       str
    location:      str
    contract_type: str
    salary:        str
    description:   str
    url:           str
    source:        str
    scraped_at:    str = field(default_factory=lambda: datetime.now().isoformat())


# =============================================================================
# SECTION 2 – CONFIGURATION
# =============================================================================

def _env_str(key: str, default: str) -> str:
    val = os.getenv(key)
    return val if val else default


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    try:
        return int(val) if val else default
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key)
    try:
        return float(val) if val else default
    except ValueError:
        return default


BASE_URL    = "https://www.hellowork.com"
SEARCH_PATH = "/fr-fr/emploi/recherche.html"

QUERY     = _env_str("SCRAPER_QUERY",    "alternance")
LOCATION  = _env_str("SCRAPER_LOCATION", "france")
MAX_PAGES = _env_int("SCRAPER_MAX_PAGES", 5)

DELAY_MIN = _env_float("HW_DELAY_MIN", 3.0)
DELAY_MAX = _env_float("HW_DELAY_MAX", 6.0)

TIMEOUT   = 30.0  # secondes

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


# =============================================================================
# SECTION 3 – FONCTIONS UTILITAIRES
# =============================================================================

def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def build_search_url(query: str, location: str, page: int = 1) -> str:
    """Construit l'URL de recherche HelloWork avec les paramètres."""
    params = {
        "k":  query,
        "l":  location,
        "ray": "50",   # rayon 50 km
    }
    if page > 1:
        params["p"] = str(page)

    return f"{BASE_URL}{SEARCH_PATH}?{urlencode(params)}"


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "DNT":             "1",
    }


# =============================================================================
# SECTION 4 – EXTRACTION D'UNE PAGE
# =============================================================================

def extract_offers_from_html(html: str) -> list[JobOffer]:
    """
    Extrait les offres d'emploi depuis le HTML d'une page de résultats.

    Sélecteurs HelloWork (structure au 2024-05) :
        - Cartes : <li data-testid="job-card">
        - Titre  : <p data-testid="job-title">
        - Société: <p data-testid="job-company">
        - Lieu   : <p data-testid="job-location">
        - Contrat: <p data-testid="job-contract">
        - Salaire: <p data-testid="job-salary">
        - Lien   : <a href="..."> wrapping the card
    """
    soup   = BeautifulSoup(html, "html.parser")
    cards  = soup.find_all("li", attrs={"data-testid": "job-card"})

    if not cards:
        # Fallback sur les divs article en cas de changement de structure
        cards = soup.find_all("article", class_=re.compile(r"job"))

    offers = []
    for card in cards:
        try:
            title_el    = card.find(attrs={"data-testid": "job-title"})
            company_el  = card.find(attrs={"data-testid": "job-company"})
            location_el = card.find(attrs={"data-testid": "job-location"})
            contract_el = card.find(attrs={"data-testid": "job-contract"})
            salary_el   = card.find(attrs={"data-testid": "job-salary"})
            desc_el     = card.find(attrs={"data-testid": "job-description"})
            link_el     = card.find("a", href=True)

            title    = clean_text(title_el.get_text()    if title_el    else "")
            company  = clean_text(company_el.get_text()  if company_el  else "")
            location = clean_text(location_el.get_text() if location_el else "")
            contract = clean_text(contract_el.get_text() if contract_el else "Alternance")
            salary   = clean_text(salary_el.get_text()   if salary_el   else "")
            desc     = clean_text(desc_el.get_text()     if desc_el     else "")

            href = link_el["href"] if link_el else ""
            url  = href if href.startswith("http") else (f"{BASE_URL}{href}" if href else "")

            if not title:
                continue

            offers.append(JobOffer(
                title=title,
                company=company,
                location=location,
                contract_type=contract,
                salary=salary,
                description=desc,
                url=url,
                source="hellowork",
            ))

        except Exception as e:
            print(f"  [warn] HelloWork — erreur extraction card : {e}")
            continue

    return offers


def has_next_page(html: str, current_page: int) -> bool:
    """Vérifie s'il existe une page suivante dans la pagination."""
    soup = BeautifulSoup(html, "html.parser")
    next_el = soup.find("a", attrs={"data-testid": "next-page"})
    if next_el:
        return True
    # Fallback : cherche un lien vers page+1
    return bool(soup.find("a", href=re.compile(rf"[?&]p={current_page + 1}")))


# =============================================================================
# SECTION 5 – SCRAPER PRINCIPAL
# =============================================================================

class HelloWorkScraper:
    """
    Scraper HelloWork basé sur httpx + BeautifulSoup.

    Plus léger qu'un scraper Playwright car HelloWork utilise du rendu
    serveur (SSR). Les offres sont directement dans le HTML initial.
    """

    def __init__(
        self,
        query:     str = QUERY,
        location:  str = LOCATION,
        max_pages: int = MAX_PAGES,
    ):
        self.query     = query
        self.location  = location
        self.max_pages = max_pages
        self.offers:     list[JobOffer] = []
        self._seen_urls: set[str]       = set()
        self.stats: dict = {
            "query":             query,
            "location":          location,
            "started_at":        None,
            "ended_at":          None,
            "duration_seconds":  0.0,
            "pages_scraped":     0,
            "pages_blocked":     0,
            "offers_total":      0,
            "offers_new":        0,
            "offers_duplicates": 0,
        }

    def _add_offers(self, new_offers: list[JobOffer]) -> int:
        added = 0
        for o in new_offers:
            key = o.url or f"{o.title}|{o.company}|{o.location}"
            if key in self._seen_urls:
                continue
            self._seen_urls.add(key)
            self.offers.append(o)
            added += 1
        self.stats["offers_new"]        += added
        self.stats["offers_duplicates"] += len(new_offers) - added
        self.stats["pages_scraped"]     += 1
        return added

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> str | None:
        """Télécharge une page avec gestion des erreurs et retry minimal."""
        for attempt in range(1, 3):
            try:
                response = await client.get(
                    url,
                    headers=_default_headers(),
                    timeout=TIMEOUT,
                    follow_redirects=True,
                )
                if response.status_code == 200:
                    return response.text
                if response.status_code == 429:
                    wait = random.uniform(15, 30)
                    print(f"  [warn] HelloWork rate-limit (429) — attente {wait:.0f}s")
                    await asyncio.sleep(wait)
                    continue
                print(f"  [warn] HelloWork HTTP {response.status_code} sur {url}")
                return None
            except httpx.RequestError as e:
                print(f"  [warn] HelloWork requête échouée (tentative {attempt}/2) : {e}")
                if attempt < 2:
                    await asyncio.sleep(random.uniform(5, 10))
        return None

    async def run(self) -> list[JobOffer]:
        start = datetime.now()
        self.stats["started_at"] = start.isoformat()

        async with httpx.AsyncClient() as client:
            for page_num in range(1, self.max_pages + 1):
                url = build_search_url(self.query, self.location, page_num)
                print(f"[hellowork] Page {page_num}/{self.max_pages} → {url}")

                html = await self._fetch_page(client, url)
                if not html:
                    print(f"  [warn] Page {page_num} non chargée — arrêt")
                    self.stats["pages_blocked"] += 1
                    break

                page_offers = extract_offers_from_html(html)
                added       = self._add_offers(page_offers)
                print(f"  → {len(page_offers)} offres ({added} nouvelles, {len(page_offers) - added} doublons)")

                if not has_next_page(html, page_num):
                    print("  [info] Dernière page atteinte")
                    break

                if page_num < self.max_pages:
                    delay = random.uniform(DELAY_MIN, DELAY_MAX)
                    print(f"  → pause {delay:.1f}s...")
                    await asyncio.sleep(delay)

        end = datetime.now()
        self.stats["ended_at"]         = end.isoformat()
        self.stats["duration_seconds"] = round((end - start).total_seconds(), 2)
        self.stats["offers_total"]     = len(self.offers)

        print(f"\n[hellowork] Terminé : {len(self.offers)} offres en {self.stats['duration_seconds']}s")
        return self.offers
