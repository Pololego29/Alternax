
"""
scrapers/hellowork.py
======================
Scraper pour les offres d'alternance sur hellowork.com.
 
Stratégie : HelloWork sert son HTML rendu côté serveur, donc on peut utiliser
httpx + BeautifulSoup (beaucoup plus rapide que Playwright). La pagination
classique (?p=N) ne fonctionne pas, mais en combinant ~35 URLs de catégories
différentes (domaines + villes + métiers), on récupère ~500-700 offres uniques
en une seule passe.
 
Couverture : tous les profils étudiants (tech, commerce, RH, santé, BTP,
droit, marketing, hôtellerie, finance...) et toutes les grandes villes de France.
"""
 
import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin
 
import httpx
from bs4 import BeautifulSoup
 
 
# =============================================================================
# DATA MODEL
# =============================================================================
 
@dataclass
class JobOffer:
    title:         str  = ""
    company:       str  = ""
    location:      str  = ""
    contract_type: str  = "Alternance"
    salary:        str  = ""
    description:   str  = ""
    url:           str  = ""
    source:        str  = "hellowork"
    scraped_at:    str  = ""
    tech_tags:     list = field(default_factory=list)
 
 
# =============================================================================
# CONFIGURATION
# =============================================================================
 
BASE_URL = "https://www.hellowork.com"
 
# Liste des catégories explorées en page 1.
# Couvre tous les profils étudiants pour ne pas biaiser le dataset vers la tech.
DEFAULT_CATEGORY_URLS = [
    # ───────── Domaines (tous les grands secteurs) ─────────
    "/fr-fr/alternance/domaine_informatique.html",
    "/fr-fr/alternance/domaine_commerce.html",
    "/fr-fr/alternance/domaine_marketing-communication.html",
    "/fr-fr/alternance/domaine_compta-gestion-finance.html",
    "/fr-fr/alternance/domaine_ressources-humaines.html",
    "/fr-fr/alternance/domaine_industrie.html",
    "/fr-fr/alternance/domaine_ingenierie.html",
    "/fr-fr/alternance/domaine_sante-social.html",
    "/fr-fr/alternance/domaine_btp.html",
    "/fr-fr/alternance/domaine_logistique-transport.html",
    "/fr-fr/alternance/domaine_juridique.html",
    "/fr-fr/alternance/domaine_restauration-tourisme-hotellerie-loisirs.html",
    "/fr-fr/alternance/domaine_graphisme.html",
    "/fr-fr/alternance/domaine_recherche.html",
    "/fr-fr/alternance/domaine_telecom.html",
    "/fr-fr/alternance/domaine_service.html",
    "/fr-fr/alternance/domaine_administration.html",
    "/fr-fr/alternance/domaine_production.html",
 
    # ───────── Villes (top 14 villes étudiantes françaises) ─────────
    "/fr-fr/alternance/ville_paris-75000.html",
    "/fr-fr/alternance/ville_lyon-69000.html",
    "/fr-fr/alternance/ville_toulouse-31000.html",
    "/fr-fr/alternance/ville_marseille-13000.html",
    "/fr-fr/alternance/ville_bordeaux-33000.html",
    "/fr-fr/alternance/ville_nantes-44000.html",
    "/fr-fr/alternance/ville_lille-59000.html",
    "/fr-fr/alternance/ville_rennes-35000.html",
    "/fr-fr/alternance/ville_strasbourg-67000.html",
    "/fr-fr/alternance/ville_montpellier-34000.html",
    "/fr-fr/alternance/ville_nice-06000.html",
    "/fr-fr/alternance/ville_grenoble-38000.html",
    "/fr-fr/alternance/ville_aix-en-provence-13100.html",
    "/fr-fr/alternance/ville_dijon-21000.html",
 
    # ───────── Catégories transverses populaires ─────────
    "/fr-fr/alternance/mot-cle_teletravail.html",
    "/fr-fr/alternance/mot-cle_bac-2.html",
]
 
# Headers de navigateur réaliste pour éviter le 403
BROWSER_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Sec-Ch-Ua":          '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile":   "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest":     "document",
    "Sec-Fetch-Mode":     "navigate",
    "Sec-Fetch-Site":     "none",
    "Upgrade-Insecure-Requests": "1",
}
 
JOB_URL_PATTERN = re.compile(r"/fr-fr/emplois/\d+\.html")
 
 
# =============================================================================
# SCRAPING — fonction principale
# =============================================================================
 
async def fetch_hellowork(
    category_urls: list[str] | None = None,
    delay:         float = 1.0,
    timeout:       float = 30.0,
) -> list[JobOffer]:
    """
    Récupère les offres d'alternance HelloWork sur toutes les catégories.
 
    Args:
        category_urls : chemins relatifs à scraper. Par défaut : 34 URLs
                        couvrant tous les profils étudiants et les
                        principales villes françaises.
        delay         : pause entre deux requêtes (secondes), 1.0 par défaut
        timeout       : timeout par requête (secondes)
 
    Returns:
        Liste dédupliquée d'objets JobOffer.
    """
    if category_urls is None:
        category_urls = DEFAULT_CATEGORY_URLS
 
    all_offers: list[JobOffer] = []
    seen_urls: set[str] = set()
    failed_urls = 0
 
    async with httpx.AsyncClient(
        timeout=timeout, headers=BROWSER_HEADERS, follow_redirects=True,
    ) as client:
        for i, path in enumerate(category_urls, 1):
            url = BASE_URL + path
            print(f"[hellowork] {i}/{len(category_urls)} → {path}")
 
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    print(f"  [skip] Status {resp.status_code}")
                    failed_urls += 1
                    continue
            except httpx.HTTPError as e:
                print(f"  [skip] Erreur HTTP : {e}")
                failed_urls += 1
                continue
 
            soup = BeautifulSoup(resp.text, "html.parser")
            page_offers = parse_offers_page(soup)
 
            new_offers = [o for o in page_offers if o.url not in seen_urls]
            for o in new_offers:
                seen_urls.add(o.url)
            all_offers.extend(new_offers)
 
            print(f"  → {len(new_offers)} nouvelles (cumul : {len(all_offers)})")
 
            if delay > 0 and i < len(category_urls):
                await asyncio.sleep(delay)
 
    print(f"\n[hellowork] Collecte terminée : {len(all_offers)} offres uniques "
          f"({failed_urls} catégorie(s) en échec)")
    return all_offers
 
 
# =============================================================================
# PARSING — extraction depuis le HTML
# =============================================================================
 
def parse_offers_page(soup: BeautifulSoup) -> list[JobOffer]:
    """Parse toutes les offres présentes sur une page de résultats."""
    offers: list[JobOffer] = []
    seen_in_page: set[str] = set()
 
    # Chaque offre apparaît dans deux liens : le lien principal (avec H3) et un
    # lien "Voir l'offre". On ne garde que le principal pour récupérer le titre.
    job_links = soup.find_all("a", href=JOB_URL_PATTERN)
 
    for link in job_links:
        href = link.get("href", "")
        if not href or href in seen_in_page:
            continue
 
        # On exige un H3 dans le lien — ça filtre les "Voir l'offre"
        h3 = link.find(["h3", "h2"])
        if not h3:
            continue
 
        seen_in_page.add(href)
 
        # Trouver le container parent qui contient toutes les infos d'offre
        container = link
        for _ in range(8):
            container = container.parent
            if container is None or container.name == "body":
                container = None
                break
            text = container.get_text(separator=" ", strip=True)
            if len(text) > 60 and "Alternance" in text:
                break
 
        if container is None:
            continue
 
        offer = parse_offer_card(link, h3, container, href)
        if offer and offer.title:
            offers.append(offer)
 
    return offers
 
 
def parse_offer_card(link, h3, container, href: str) -> JobOffer | None:
    """Extrait les champs depuis le markup d'une carte d'offre."""
 
    # Titre + entreprise via l'attribut title du lien (format : "Titre - Entreprise")
    title_attr = link.get("title", "")
    if " - " in title_attr:
        title, _, company = title_attr.rpartition(" - ")
        title   = title.strip()
        company = company.strip()
    else:
        title   = h3.get_text(strip=True)
        company = ""
 
    # Texte complet du container, séparateur " | " pour parser ensuite
    text = container.get_text(separator=" | ", strip=True)
 
    # Localisation — pattern "Ville - département" (2-3 chiffres)
    location = ""
    loc_match = re.search(
        r"\|\s*([A-Za-zÀ-ÿ][\wÀ-ÿ\-' ]{2,40})\s*-\s*(\d{2,3}[A-Z]?)\s*\|",
        text,
    )
    if loc_match:
        ville = loc_match.group(1).strip()
        dept  = loc_match.group(2).strip()
        if len(ville) >= 3 and not ville[0].isdigit():
            location = f"{ville} ({dept})"
 
    # Salaire — pattern "XXX,XX - X XXX,XX € / mois"
    salary = ""
    salary_match = re.search(
        r"(\d{1,3}(?:[\s,]\d{3})*(?:[,.]\d{1,2})?"
        r"(?:\s*-\s*\d{1,3}(?:[\s,]\d{3})*(?:[,.]\d{1,2})?)?"
        r"\s*€\s*/\s*\w+)",
        text,
    )
    if salary_match:
        salary = salary_match.group(1).strip()
 
    return JobOffer(
        title         = title,
        company       = company,
        location      = location,
        contract_type = "Alternance",
        salary        = salary,
        description   = "",
        url           = urljoin(BASE_URL, href),
        source        = "hellowork",
        scraped_at    = datetime.now().isoformat(timespec="seconds"),
    )
 
 
# =============================================================================
# TEST STANDALONE — utilise la liste complète pour valider tous les profils
# =============================================================================
 
async def main():
    """Lancement direct pour tester le scraper sur l'ensemble des catégories."""
    print("=" * 70)
    print(f"Test HelloWork — {len(DEFAULT_CATEGORY_URLS)} catégories")
    print("=" * 70)
 
    offers = await fetch_hellowork()  # utilise DEFAULT_CATEGORY_URLS
 
    print(f"\n→ {len(offers)} offres récupérées au total\n")
 
    # Aperçu de la diversité : 1 offre par "source d'origine" si possible
    seen_companies = set()
    sample = []
    for o in offers:
        if o.company and o.company not in seen_companies and len(sample) < 10:
            seen_companies.add(o.company)
            sample.append(o)
 
    for i, o in enumerate(sample, 1):
        print(f"--- Offre {i} ---")
        print(f"  Titre      : {o.title}")
        print(f"  Entreprise : {o.company}")
        print(f"  Lieu       : {o.location}")
        print(f"  Salaire    : {o.salary}")
        print(f"  URL        : {o.url}")
        print()
 
 
if __name__ == "__main__":
    asyncio.run(main())
 