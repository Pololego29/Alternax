"""
Tests unitaires pour scrapers/hellowork.py
============================================
Vérifie que le parser de cartes HelloWork extrait correctement les champs
depuis un markup HTML représentatif (titre, entreprise, lieu, salaire).

Les tests sont déterministes : aucune requête réseau, on construit le HTML
en mémoire pour valider la logique du parser.

Lancement :
    python -m pytest tests/test_hellowork.py -v
"""

from bs4 import BeautifulSoup

from scrapers.hellowork import (
    parse_offer_card,
    parse_offers_page,
    JOB_URL_PATTERN,
)


def _make_card(
    title_attr: str,
    h3_text: str,
    location: str = "",
    salary: str = "",
    duration: str = "1 an",
    date: str = "il y a 2 jours",
) -> tuple:
    """
    Construit un container BS4 ressemblant à une carte HelloWork réelle.
    Chaque info est dans son propre élément, comme dans le HTML produit
    par HelloWork (sinon les regex de séparation par '|' échouent).
    """
    html = f"""
    <article class="offer-card">
        <div class="content">
            <img src="logo.png" alt="logo entreprise" />
            <a href="/fr-fr/emplois/76846651.html" title="{title_attr}">
                <h3>{h3_text}</h3>
            </a>
            <span class="location">{location}</span>
            <span class="contract">Alternance</span>
            <span class="salary">{salary}</span>
            <span class="duration">{duration}</span>
            <span class="see-offer">Voir l'offre</span>
            <span class="date">{date}</span>
        </div>
    </article>
    """
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("a")
    h3 = link.find("h3")
    container = soup.find("article")
    return link, h3, container


# ============================================================================
# 1. Extraction titre + entreprise
# ============================================================================

def test_extract_title_and_company_from_title_attribute():
    """Le titre et l'entreprise sont extraits depuis l'attribut title du lien."""
    link, h3, container = _make_card(
        title_attr="Alternance Développeur Python H/F - Safran",
        h3_text="Alternance Développeur Python H/F",
        location="Paris - 75",
        salary="500 € / mois",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/76846651.html")
    assert offer.title == "Alternance Développeur Python H/F"
    assert offer.company == "Safran"


def test_extract_title_with_dashes_in_title():
    """Quand le titre contient un tiret, on coupe sur le DERNIER tiret."""
    link, h3, container = _make_card(
        title_attr="Alternance - Chef de Projet MOA Digital H/F - GRDF",
        h3_text="Alternance - Chef de Projet MOA Digital H/F",
        location="Saint-Denis - 93",
        salary="800 € / mois",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/76834053.html")
    assert offer.title == "Alternance - Chef de Projet MOA Digital H/F"
    assert offer.company == "GRDF"


def test_fallback_to_h3_when_no_title_attribute():
    """Si le lien n'a pas d'attribut title, on utilise le texte du H3."""
    link, h3, container = _make_card(
        title_attr="",
        h3_text="Alternance Chargé Marketing H/F",
        location="Lyon - 69",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/12345.html")
    assert offer.title == "Alternance Chargé Marketing H/F"
    assert offer.company == ""


# ============================================================================
# 2. Extraction localisation
# ============================================================================

def test_extract_simple_location():
    """Extraction de la ville et du département (format Ville - DD)."""
    link, h3, container = _make_card(
        title_attr="Dev H/F - ACME",
        h3_text="Dev H/F",
        location="Tarnos - 40",
        salary="800 € / mois",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/1.html")
    assert offer.location == "Tarnos (40)"


def test_extract_compound_city_name():
    """Les noms de villes composés (avec tirets) sont préservés."""
    link, h3, container = _make_card(
        title_attr="Stage H/F - Entreprise",
        h3_text="Stage H/F",
        location="Boulogne-Billancourt - 92",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/2.html")
    assert offer.location == "Boulogne-Billancourt (92)"


# ============================================================================
# 3. Extraction salaire
# ============================================================================

def test_extract_salary_range():
    """Une plage de salaire 'XXX - XXX € / mois' est correctement extraite."""
    link, h3, container = _make_card(
        title_attr="Dev H/F - ACME",
        h3_text="Dev H/F",
        location="Paris - 75",
        salary="492,22 - 1 823,03 € / mois",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/3.html")
    assert "€" in offer.salary
    assert "1 823,03" in offer.salary or "1823,03" in offer.salary


def test_no_salary_returns_empty():
    """Pas d'info salaire dans le markup → champ salary vide."""
    link, h3, container = _make_card(
        title_attr="Dev H/F - ACME",
        h3_text="Dev H/F",
        location="Paris - 75",
        salary="",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/4.html")
    assert offer.salary == ""


# ============================================================================
# 4. URL et métadonnées
# ============================================================================

def test_url_is_normalized_to_absolute():
    """L'URL relative est convertie en URL absolue HelloWork."""
    link, h3, container = _make_card(
        title_attr="Dev H/F - ACME",
        h3_text="Dev H/F",
        location="Paris - 75",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/76846651.html")
    assert offer.url == "https://www.hellowork.com/fr-fr/emplois/76846651.html"


def test_source_is_hellowork():
    """Le champ source vaut 'hellowork' pour tracer l'origine de l'offre."""
    link, h3, container = _make_card(
        title_attr="Dev - ACME",
        h3_text="Dev",
        location="Lyon - 69",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/5.html")
    assert offer.source == "hellowork"


def test_contract_type_is_alternance():
    """Toutes les offres HelloWork récupérées sont des alternances."""
    link, h3, container = _make_card(
        title_attr="Dev - ACME",
        h3_text="Dev",
        location="Lyon - 69",
    )
    offer = parse_offer_card(link, h3, container, "/fr-fr/emplois/6.html")
    assert offer.contract_type == "Alternance"


# ============================================================================
# 5. Parsing d'une page entière
# ============================================================================

def _make_page_html(*cards_data) -> str:
    """Construit le HTML d'une page de résultats avec plusieurs cartes."""
    cards_html = ""
    for href, title_attr, h3_text, location, salary in cards_data:
        cards_html += f"""
        <article class="offer-card">
            <div>
                <a href="{href}" title="{title_attr}">
                    <h3>{h3_text}</h3>
                </a>
                <span>{location}</span>
                <span>Alternance</span>
                <span>{salary}</span>
                <span>1 an</span>
                <span>il y a 2 jours</span>
            </div>
        </article>
        """
    return f"<html><body>{cards_html}</body></html>"


def test_parse_page_extracts_multiple_offers():
    """Le parser de page extrait toutes les cartes présentes dans le HTML."""
    html = _make_page_html(
        ("/fr-fr/emplois/100.html", "Dev Python H/F - Safran",
         "Dev Python H/F", "Paris - 75", "500 € / mois"),
        ("/fr-fr/emplois/200.html", "Chef de Projet - GRDF",
         "Chef de Projet", "Lyon - 69", "700 € / mois"),
    )
    soup = BeautifulSoup(html, "html.parser")
    offers = parse_offers_page(soup)
    assert len(offers) == 2
    assert offers[0].company == "Safran"
    assert offers[1].company == "GRDF"


def test_parse_page_ignores_voir_offre_links():
    """Les liens 'Voir l'offre' sans H3 sont ignorés (évite les doublons)."""
    # Une carte avec un lien principal H3 + un lien "Voir l'offre" pointant la même URL
    html = """
    <html><body>
        <article class="offer-card">
            <div>
                <a href="/fr-fr/emplois/100.html" title="Dev Python H/F - Safran">
                    <h3>Dev Python H/F</h3>
                </a>
                <span>Paris - 75</span>
                <span>Alternance</span>
                <span>500 € / mois</span>
                <span>1 an</span>
                <a href="/fr-fr/emplois/100.html">Voir l'offre</a>
                <span>il y a 2 jours</span>
            </div>
        </article>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    offers = parse_offers_page(soup)
    # Une seule offre, pas deux : le lien "Voir l'offre" sans H3 est filtré
    assert len(offers) == 1
    assert offers[0].company == "Safran"


# ============================================================================
# 6. Pattern d'URL
# ============================================================================

def test_url_pattern_matches_offer_urls():
    """Le regex JOB_URL_PATTERN reconnaît bien les URLs d'offres HelloWork."""
    assert JOB_URL_PATTERN.search("/fr-fr/emplois/76846651.html")
    assert JOB_URL_PATTERN.search("/fr-fr/emplois/1.html")
    # Doit pas matcher d'autres URLs
    assert not JOB_URL_PATTERN.search("/fr-fr/entreprise/acme.html")
    assert not JOB_URL_PATTERN.search("/fr-fr/alternance/domaine_informatique.html")