"""Tests unitaires pour scrapers/hellowork.py"""

import pytest
from scrapers.hellowork import (
    clean_text,
    build_search_url,
    extract_offers_from_html,
    has_next_page,
    HelloWorkScraper,
)


# =============================================================================
# clean_text
# =============================================================================

class TestCleanText:
    def test_removes_extra_whitespace(self):
        assert clean_text("hello   world") == "hello world"

    def test_none_returns_empty(self):
        assert clean_text(None) == ""

    def test_empty_returns_empty(self):
        assert clean_text("") == ""

    def test_strips_edges(self):
        assert clean_text("  hello  ") == "hello"


# =============================================================================
# build_search_url
# =============================================================================

class TestBuildSearchUrl:
    def test_page_1_has_no_p_param(self):
        url = build_search_url("alternance", "france", page=1)
        assert "hellowork.com" in url
        assert "alternance" in url
        assert "&p=" not in url

    def test_page_2_has_p_param(self):
        url = build_search_url("alternance", "france", page=2)
        assert "p=2" in url

    def test_query_is_encoded(self):
        url = build_search_url("dev python", "france", page=1)
        assert "dev+python" in url or "dev%20python" in url

    def test_location_is_present(self):
        url = build_search_url("alternance", "lyon", page=1)
        assert "lyon" in url


# =============================================================================
# extract_offers_from_html
# =============================================================================

_SAMPLE_HTML_WITH_OFFERS = """
<html><body><ul>
  <li data-testid="job-card">
    <p data-testid="job-title">Développeur Python</p>
    <p data-testid="job-company">TechCorp</p>
    <p data-testid="job-location">Paris</p>
    <p data-testid="job-contract">Alternance</p>
    <p data-testid="job-salary">1 200 €/mois</p>
    <p data-testid="job-description">Rejoignez notre équipe</p>
    <a href="/fr-fr/emploi/offre/12345.html">Voir l'offre</a>
  </li>
  <li data-testid="job-card">
    <p data-testid="job-title">Data Analyst Alternant</p>
    <p data-testid="job-company">DataInc</p>
    <p data-testid="job-location">Lyon</p>
    <p data-testid="job-contract">Contrat d'apprentissage</p>
    <a href="https://www.hellowork.com/emploi/offre/99999.html">Voir</a>
  </li>
</ul></body></html>
"""

_SAMPLE_HTML_NO_OFFERS = """
<html><body><p>Aucune offre trouvée.</p></body></html>
"""

_SAMPLE_HTML_CARD_MISSING_TITLE = """
<html><body><ul>
  <li data-testid="job-card">
    <p data-testid="job-company">Acme</p>
    <p data-testid="job-location">Paris</p>
  </li>
</ul></body></html>
"""


class TestExtractOffersFromHtml:
    def test_extracts_two_offers(self):
        offers = extract_offers_from_html(_SAMPLE_HTML_WITH_OFFERS)
        assert len(offers) == 2

    def test_offer_fields_populated(self):
        offers = extract_offers_from_html(_SAMPLE_HTML_WITH_OFFERS)
        o = offers[0]
        assert o.title == "Développeur Python"
        assert o.company == "TechCorp"
        assert o.location == "Paris"
        assert o.contract_type == "Alternance"
        assert o.salary == "1 200 €/mois"
        assert o.source == "hellowork"

    def test_relative_url_becomes_absolute(self):
        offers = extract_offers_from_html(_SAMPLE_HTML_WITH_OFFERS)
        assert offers[0].url.startswith("https://www.hellowork.com")

    def test_absolute_url_unchanged(self):
        offers = extract_offers_from_html(_SAMPLE_HTML_WITH_OFFERS)
        assert offers[1].url == "https://www.hellowork.com/emploi/offre/99999.html"

    def test_no_offers_on_empty_page(self):
        offers = extract_offers_from_html(_SAMPLE_HTML_NO_OFFERS)
        assert offers == []

    def test_card_without_title_skipped(self):
        offers = extract_offers_from_html(_SAMPLE_HTML_CARD_MISSING_TITLE)
        assert offers == []

    def test_scraped_at_is_set(self):
        offers = extract_offers_from_html(_SAMPLE_HTML_WITH_OFFERS)
        assert offers[0].scraped_at != ""


# =============================================================================
# has_next_page
# =============================================================================

_HTML_WITH_NEXT = """
<html><body>
  <nav><a data-testid="next-page" href="?p=2">Suivant</a></nav>
</body></html>
"""

_HTML_WITHOUT_NEXT = """
<html><body>
  <nav><span>Page 3 / 3</span></nav>
</body></html>
"""

_HTML_WITH_PAGE_PARAM = """
<html><body>
  <nav><a href="?p=4">Page 4</a></nav>
</body></html>
"""


class TestHasNextPage:
    def test_detects_next_page_button(self):
        assert has_next_page(_HTML_WITH_NEXT, current_page=1) is True

    def test_no_next_on_last_page(self):
        assert has_next_page(_HTML_WITHOUT_NEXT, current_page=3) is False

    def test_detects_via_page_param_link(self):
        assert has_next_page(_HTML_WITH_PAGE_PARAM, current_page=3) is True

    def test_empty_html_returns_false(self):
        assert has_next_page("<html></html>", current_page=1) is False


# =============================================================================
# HelloWorkScraper (initialisation seulement — pas de vraies requêtes)
# =============================================================================

class TestHelloWorkScraperInit:
    def test_default_values(self):
        s = HelloWorkScraper()
        assert s.query == "alternance"
        assert s.max_pages == 5

    def test_custom_values(self):
        s = HelloWorkScraper(query="dev python", location="Lyon", max_pages=2)
        assert s.query == "dev python"
        assert s.location == "Lyon"
        assert s.max_pages == 2

    def test_initial_offers_empty(self):
        s = HelloWorkScraper()
        assert s.offers == []

    def test_stats_initialized(self):
        s = HelloWorkScraper()
        assert s.stats["pages_scraped"] == 0
        assert s.stats["offers_total"] == 0

    def test_add_offers_deduplicates(self):
        s = HelloWorkScraper()
        from scrapers.hellowork import JobOffer
        offer = JobOffer(
            title="Dev", company="A", location="Paris",
            contract_type="Alternance", salary="", description="",
            url="https://x.com/1", source="hellowork",
        )
        s._add_offers([offer, offer])
        assert len(s.offers) == 1
        assert s.stats["offers_duplicates"] == 1
