"""
scrapers/indeed.py
==================
Scraper Indeed France pour les offres d'alternance.

Ce module utilise Playwright (navigateur headless) plutôt que requests/BeautifulSoup
car Indeed charge ses offres via JavaScript. Un simple GET HTTP ne retourne pas
les annonces — il faut un vrai navigateur.

Stratégie multi-requêtes : plutôt qu'une seule recherche "alternance France"
(qui renvoie toujours les mêmes ~16 résultats sponsorisés en haut), on lance
plusieurs requêtes ciblées (par métier + par ville) dans la même session
Chromium. Volume attendu : ~80-130 offres uniques par run.

Auteurs      : Alternax
Dépendances  : playwright (pip install playwright && playwright install chromium)
               playwright-stealth (pip install playwright-stealth)
Sortie       : data/indeed_offers.csv  +  data/indeed_offers.json

Utilisation rapide :
    python scrapers/indeed.py

Variables d'environnement (debug) :
    INDEED_HEADLESS=0   → ouvre Chromium en mode visible (pour observer)
    INDEED_SLOW_MO=500  → ralentit chaque action de N millisecondes
"""

import asyncio
import csv
import json
import os
import random
import re
from dataclasses import dataclass, asdict, fields, field
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# --- Import optionnel de playwright-stealth ---
try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    print("[indeed] playwright-stealth non installé — fonctionnement dégradé.")
    print("[indeed] Pour l'installer : pip install playwright-stealth")


# =============================================================================
# SECTION 1 – MODÈLE DE DONNÉES
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
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    category: str = ""

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now().isoformat()


# =============================================================================
# SECTION 2 – CONFIGURATION
# =============================================================================

BASE_URL = "https://fr.indeed.com"

# Liste des requêtes lancées par défaut. Couvre tous les profils étudiants
# (tech + commerce + marketing + RH + finance) + 3 grandes villes.
# Chaque requête renvoie ~16 offres en page 1.
DEFAULT_QUERIES = [
    # Par métier
    "alternance développeur",
    "alternance data",
    "alternance marketing",
    "alternance commerce",
    "alternance ingénieur",
    "alternance communication",
    "alternance finance",
    "alternance ressources humaines",
    # Par ville (pour la diversité géographique)
    "alternance Paris",
    "alternance Lyon",
    "alternance Toulouse",
]
DEFAULT_LOCATION = "France"
MAX_RETRY = 2

# Délais entre requêtes (en secondes)
DELAY_MIN = 4.0
DELAY_MAX = 7.0

# Timeouts Playwright (en millisecondes)
TIMEOUT_GOTO       = 60_000
TIMEOUT_SELECTOR   = 30_000
TIMEOUT_CLOUDFLARE = 30_000

OUTPUT_DIR = Path(__file__).parent.parent / "data"
DEBUG_DIR  = Path(__file__).parent.parent / "debug"

HEADLESS = os.environ.get("INDEED_HEADLESS", "1") != "0"
SLOW_MO  = int(os.environ.get("INDEED_SLOW_MO", "0"))

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
    """Simule un défilement humain progressif sur la page."""
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(300, 600))
        await asyncio.sleep(random.uniform(0.3, 0.8))


async def is_blocked(page) -> bool:
    """Détecte si Indeed a affiché une page de blocage / CAPTCHA."""
    title = await page.title()
    keywords = ["captcha", "robot", "vérification", "verification", "blocked", "access denied"]
    return any(k in title.lower() for k in keywords)


async def wait_for_cloudflare_pass(page, timeout: int = TIMEOUT_CLOUDFLARE) -> bool:
    """
    Attend que la page Cloudflare "Un instant…" se résolve.
    Retourne True si le challenge est passé, False si on reste bloqué.
    """
    try:
        await page.wait_for_function(
            """() => {
                const t = document.title.toLowerCase();
                return !t.includes('moment') && !t.includes('instant')
                       && !t.includes('vérification') && !t.includes('verification');
            }""",
            timeout=timeout,
        )
        return True
    except PlaywrightTimeout:
        return False


async def dump_debug(page, label: str) -> None:
    """Sauvegarde un screenshot + le HTML brut de la page actuelle dans debug/."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = DEBUG_DIR / f"{timestamp}_{label}"

    try:
        title = await page.title()
        current_url = page.url
        print(f"  [debug] Titre  : {title}")
        print(f"  [debug] URL    : {current_url}")

        await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        html = await page.content()
        base.with_suffix(".html").write_text(html, encoding="utf-8")
        print(f"  [debug] Screenshot + HTML sauvegardés → {base}.png / .html")
    except Exception as e:
        print(f"  [debug] Échec de la capture : {e}")


# =============================================================================
# SECTION 4 – EXTRACTION D'UNE PAGE DE RÉSULTATS
# =============================================================================

async def _try_first(card, selectors: list[tuple[str, str | None]]) -> str:
    """
    Essaie une cascade de sélecteurs. Chaque tuple = (selector_css, attribute).
    Si attribute=None, prend l'inner_text. Sinon prend l'attribut.
    Retourne le premier résultat non vide, ou "".
    """
    for sel, attr in selectors:
        try:
            el = await card.query_selector(sel)
            if not el:
                continue
            if attr:
                val = await el.get_attribute(attr)
            else:
                val = await el.inner_text()
            if val and val.strip():
                return clean_text(val)
        except Exception:
            continue
    return ""


async def extract_offers_from_page(page) -> list[JobOffer]:
    """
    Extrait toutes les offres présentes sur la page Indeed actuellement chargée.
    Utilise une cascade de sélecteurs pour résister aux changements HTML d'Indeed.
    """
    offers = []

    cards = await page.query_selector_all("div.job_seen_beacon")

    if cards:
        print(f"  [debug] {len(cards)} cartes d'offres détectées (sélecteur principal).")
    else:
        cards = await page.query_selector_all("li.css-5lfssm")
        if cards:
            print(f"  [debug] {len(cards)} cartes d'offres détectées (sélecteur secondaire).")

    if not cards:
        print("  [warn] Aucune card trouvée — sélecteurs à mettre à jour ou page bloquée")
        return offers

    # Cascade de sélecteurs : Indeed change régulièrement, on essaie plusieurs variantes
    for card in cards:
        try:
            title = await _try_first(card, [
                ("h2.jobTitle span[title]", "title"),     # ancien format
                ("h2.jobTitle a", "aria-label"),           # aria-label sur le lien
                ("h2.jobTitle a span", None),              # span dans le lien
                ("h2.jobTitle span", None),                # span sans title attr
                ("h2.jobTitle", None),                     # texte direct du h2
                ("a[data-jk]", "aria-label"),              # aria-label du lien data-jk
                ("[data-testid='job-title']", None),       # data-testid moderne
                ("h2 a", None),                            # fallback générique
            ])

            company = await _try_first(card, [
                ("span[data-testid='company-name']", None),
                ("[data-testid='company-name']", None),
                ("span.companyName", None),
                ("a.companyOverviewLink", None),
            ])

            location = await _try_first(card, [
                ("div[data-testid='text-location']", None),
                ("[data-testid='text-location']", None),
                ("div.companyLocation", None),
            ])

            salary = await _try_first(card, [
                ("div[data-testid='attribute_snippet_testid']", None),
                ("[data-testid='salary-snippet']", None),
                ("div.salary-snippet", None),
            ])

            desc = await _try_first(card, [
                ("div.job-snippet", None),
                ("[data-testid='jobsnippet_footer']", None),
            ])

            link_el = await card.query_selector("a[data-jk]")
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
                source="indeed"
            ))

        except Exception as e:
            print(f"  [warn] Erreur extraction card : {e}")
            continue

    # DIAGNOSTIC : si on a détecté des cards mais extrait 0 offres,
    # on dump le HTML de la première pour identifier le nouveau format.
    if cards and not offers:
        try:
            first_html = await cards[0].inner_html()
            print(f"  [DIAGNOSTIC] 0 offres extraites de {len(cards)} cards.")
            print(f"  [DIAGNOSTIC] Indeed a probablement changé sa structure HTML.")
            print(f"  [DIAGNOSTIC] HTML de la 1ère card (1500 premiers chars) :")
            print("  " + "─" * 60)
            print(first_html[:1500])
            print("  " + "─" * 60)
        except Exception:
            pass

    return offers


# =============================================================================
# SECTION 5 – SCRAPER PRINCIPAL
# =============================================================================

class IndeedScraper:
    """
    Orchestre le scraping multi-requêtes d'Indeed.

    Lance plusieurs requêtes ciblées (par métier + par ville) dans la même
    session Chromium pour maximiser la diversité des offres tout en gardant
    une seule mécanique anti-détection.

    Stratégie anti-détection :
    - Stealth (playwright-stealth) pour masquer l'automatisation
    - Warm-up sur la page d'accueil avant les recherches
    - Attente du passage du challenge Cloudflare si présent
    - Scroll humain sur chaque page
    - Délais aléatoires entre les requêtes
    - Retry automatique en cas d'échec
    - Rotation des User-Agents
    - Filtre fromage=3 → uniquement les offres des 3 derniers jours
    """

    def __init__(self, queries: list[str] | None = None, location: str = DEFAULT_LOCATION, **kwargs):
        """
        Args:
            queries  : liste de mots-clés. Si None, utilise DEFAULT_QUERIES (11 requêtes).
            location : localisation par défaut (peut être "France" ou une ville).
            **kwargs : absorbe les anciens paramètres (query, max_pages) pour
                       compatibilité ascendante avec l'orchestrateur existant.
        """
        self.queries  = queries if queries else DEFAULT_QUERIES
        self.location = location
        self.offers: list[JobOffer] = []

        # Compatibilité ascendante : si l'ancien paramètre 'query' est passé
        # avec une valeur non-défaut, on l'utilise comme requête supplémentaire.
        legacy_query = kwargs.get('query')
        if legacy_query and queries is None and legacy_query != "alternance":
            self.queries = [legacy_query]

    async def _warmup(self, page) -> None:
        """Visite la page d'accueil d'Indeed avant de lancer les recherches."""
        print("[indeed] Warm-up sur fr.indeed.com...")
        try:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=TIMEOUT_GOTO)
            if not await wait_for_cloudflare_pass(page):
                print("  [warn] Cloudflare challenge non résolu pendant le warm-up")
            await asyncio.sleep(random.uniform(1.5, 3.0))
            await human_scroll(page, steps=2)
            print(f"  [debug] Warm-up OK — titre : {await page.title()}")
        except PlaywrightTimeout:
            print("  [warn] Warm-up timeout – on continue quand même")

    async def _load_page_with_retry(self, page, url: str, label: str) -> bool:
        """
        Charge une URL avec retry automatique.
        En cas de timeout, capture une PNG et le HTML dans debug/ pour analyse.
        """
        for attempt in range(1, MAX_RETRY + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_GOTO)

                cf_passed = await wait_for_cloudflare_pass(page)
                if not cf_passed:
                    print(f"  [warn] Cloudflare challenge non résolu (tentative {attempt}/{MAX_RETRY})")
                    await dump_debug(page, f"cloudflare_{label}_a{attempt}")
                    if attempt < MAX_RETRY:
                        wait = random.uniform(15, 30)
                        print(f"  → attente {wait:.1f}s avant retry...")
                        await asyncio.sleep(wait)
                    continue

                await page.wait_for_selector(
                    "div.job_seen_beacon, li.css-5lfssm",
                    timeout=TIMEOUT_SELECTOR,
                )

                if await is_blocked(page):
                    print(f"  [warn] Page bloquée (tentative {attempt}/{MAX_RETRY})")
                    await dump_debug(page, f"blocked_{label}_a{attempt}")
                    await asyncio.sleep(random.uniform(10, 20))
                    continue

                return True

            except PlaywrightTimeout:
                print(f"  [warn] Timeout (tentative {attempt}/{MAX_RETRY})")
                await dump_debug(page, f"timeout_{label}_a{attempt}")
                if attempt < MAX_RETRY:
                    wait = random.uniform(8, 15)
                    print(f"  → attente {wait:.1f}s avant retry...")
                    await asyncio.sleep(wait)

        return False

    async def run(self) -> list[JobOffer]:
        """
        Lance le scraping multi-requêtes : pour chaque requête de self.queries,
        navigue vers la page de résultats et extrait les offres. Une seule
        session Chromium est utilisée pour toutes les requêtes (gain de temps).
        """
        async with async_playwright() as p:
            print(f"[indeed] Lancement Chromium (headless={HEADLESS}, slow_mo={SLOW_MO}ms)")
            browser = await p.chromium.launch(
                headless=HEADLESS,
                slow_mo=SLOW_MO,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="fr-FR",
                viewport={
                    "width": random.randint(1200, 1400),
                    "height": random.randint(750, 900),
                },
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            )

            if STEALTH_AVAILABLE:
                stealth = Stealth()
                await stealth.apply_stealth_async(context)
                print("[indeed] Stealth activé")

            page = await context.new_page()

            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            # --- Warm-up ---
            await self._warmup(page)

            # --- Boucle sur chaque requête ---
            seen_urls = set()
            print(f"\n[indeed] Démarrage du scraping multi-requêtes ({len(self.queries)} requêtes)")

            for i, query in enumerate(self.queries, 1):
                url = (
                    f"{BASE_URL}/jobs?q={query.replace(' ', '+')}"
                    f"&l={self.location.replace(' ', '+')}"
                    f"&sort=date&fromage=3"
                )
                label = f"q{i}_{query.replace(' ', '_')[:30]}"
                print(f"\n[indeed] Requête {i}/{len(self.queries)} : '{query}'")
                print(f"  → {url}")

                if not await self._load_page_with_retry(page, url, label):
                    print(f"[indeed] Échec sur '{query}' — on passe à la suivante")
                    continue

                await human_scroll(page)
                page_offers = await extract_offers_from_page(page)

                # Déduplication intra-run par URL
                new_offers = [o for o in page_offers if o.url and o.url not in seen_urls]
                for o in new_offers:
                    seen_urls.add(o.url)
                self.offers.extend(new_offers)

                print(f"  → {len(page_offers)} offres extraites ({len(new_offers)} nouvelles, cumul : {len(self.offers)})")

                # Pause entre requêtes (sauf après la dernière)
                if i < len(self.queries):
                    delay = random.uniform(DELAY_MIN, DELAY_MAX)
                    print(f"  → pause {delay:.1f}s avant prochaine recherche...")
                    await asyncio.sleep(delay)

            await browser.close()

        print(f"\n[indeed] Collecte terminée : {len(self.offers)} offres uniques au total")
        return self.offers


# =============================================================================
# SECTION 6 – EXPORT DES DONNÉES
# =============================================================================

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
    scraper = IndeedScraper()  # utilise DEFAULT_QUERIES par défaut
    await scraper.run()
    scraper.save_csv()
    scraper.save_json()


if __name__ == "__main__":
    asyncio.run(main())