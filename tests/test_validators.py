"""Tests unitaires pour utils/validators.py"""

import pytest
from utils.validators import (
    normalize_whitespace,
    normalize_contract_type,
    normalize_location,
    normalize_url,
    truncate,
    normalize_offer,
    validate_and_normalize,
)


# =============================================================================
# normalize_whitespace
# =============================================================================

class TestNormalizeWhitespace:
    def test_removes_extra_spaces(self):
        assert normalize_whitespace("hello   world") == "hello world"

    def test_removes_tabs_and_newlines(self):
        assert normalize_whitespace("hello\t\nworld") == "hello world"

    def test_strips_edges(self):
        assert normalize_whitespace("  hello  ") == "hello"

    def test_empty_string(self):
        assert normalize_whitespace("") == ""

    def test_none(self):
        assert normalize_whitespace(None) == ""


# =============================================================================
# normalize_contract_type
# =============================================================================

class TestNormalizeContractType:
    def test_detects_alternance(self):
        assert normalize_contract_type("Contrat alternance") == "Alternance"

    def test_detects_apprentissage(self):
        assert normalize_contract_type("Apprentissage") == "Alternance"

    def test_detects_stage(self):
        assert normalize_contract_type("Stage de 6 mois") == "Stage"

    def test_detects_cdi(self):
        assert normalize_contract_type("CDI temps plein") == "CDI"

    def test_detects_cdd(self):
        assert normalize_contract_type("CDD 12 mois") == "CDD"

    def test_detects_freelance(self):
        assert normalize_contract_type("Freelance senior") == "Freelance"

    def test_case_insensitive(self):
        assert normalize_contract_type("ALTERNANCE") == "Alternance"

    def test_none_defaults_to_alternance(self):
        assert normalize_contract_type(None) == "Alternance"

    def test_empty_defaults_to_alternance(self):
        assert normalize_contract_type("") == "Alternance"

    def test_unknown_type_returns_as_is(self):
        result = normalize_contract_type("Contrat mystère")
        assert result == "Contrat mystère"


# =============================================================================
# normalize_location
# =============================================================================

class TestNormalizeLocation:
    def test_normalizes_paris(self):
        assert normalize_location("Paris") == "Paris (75)"

    def test_normalizes_lyon(self):
        assert normalize_location("Lyon") == "Lyon (69)"

    def test_normalizes_ile_de_france(self):
        assert normalize_location("Ile de France") == "Île-de-France"

    def test_preserves_precise_location(self):
        result = normalize_location("Bordeaux, 33000")
        assert "Bordeaux" in result

    def test_empty_string(self):
        assert normalize_location("") == ""

    def test_none(self):
        assert normalize_location(None) == ""

    def test_case_insensitive(self):
        assert normalize_location("PARIS") == "Paris (75)"


# =============================================================================
# normalize_url
# =============================================================================

class TestNormalizeUrl:
    def test_valid_https_url(self):
        url = "https://example.com/job/123"
        assert normalize_url(url) == url

    def test_adds_https_prefix(self):
        assert normalize_url("example.com/job") == "https://example.com/job"

    def test_empty_string(self):
        assert normalize_url("") == ""

    def test_none(self):
        assert normalize_url(None) == ""

    def test_too_long_url_returns_empty(self):
        long_url = "https://example.com/" + "a" * 600
        assert normalize_url(long_url) == ""

    def test_strips_whitespace(self):
        assert normalize_url("  https://example.com  ") == "https://example.com"


# =============================================================================
# truncate
# =============================================================================

class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("hello", 100) == "hello"

    def test_long_text_truncated_with_ellipsis(self):
        result = truncate("a" * 200, 100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_exact_length_unchanged(self):
        text = "a" * 50
        assert truncate(text, 50) == text


# =============================================================================
# normalize_offer
# =============================================================================

class TestNormalizeOffer:
    def _raw(self, **kwargs):
        base = {
            "title":         "Développeur Python en alternance",
            "company":       "Acme Corp",
            "location":      "Paris",
            "contract_type": "alternance",
            "salary":        "1 200 €/mois",
            "description":   "Description du poste",
            "url":           "https://example.com/job/1",
            "source":        "indeed",
            "scraped_at":    "2024-01-01T12:00:00",
        }
        base.update(kwargs)
        return base

    def test_returns_all_expected_keys(self):
        result = normalize_offer(self._raw())
        for key in ["title", "company", "location", "contract_type",
                    "salary", "description", "url", "source", "scraped_at"]:
            assert key in result

    def test_normalizes_contract_type(self):
        result = normalize_offer(self._raw(contract_type="apprentissage"))
        assert result["contract_type"] == "Alternance"

    def test_normalizes_location(self):
        result = normalize_offer(self._raw(location="Lyon"))
        assert result["location"] == "Lyon (69)"

    def test_empty_source_defaults_to_unknown(self):
        result = normalize_offer(self._raw(source=""))
        assert result["source"] == "unknown"

    def test_does_not_mutate_input(self):
        raw = self._raw()
        original_title = raw["title"]
        normalize_offer(raw)
        assert raw["title"] == original_title


# =============================================================================
# validate_and_normalize (pipeline complet)
# =============================================================================

class TestValidateAndNormalize:
    def _make_offer(self, title="Dev Python alternance", url="https://x.com/1"):
        return {
            "title":         title,
            "company":       "Acme",
            "location":      "Paris",
            "contract_type": "Alternance",
            "salary":        "",
            "description":   "Test",
            "url":           url,
            "source":        "indeed",
            "scraped_at":    "2024-01-01T00:00:00",
        }

    def test_returns_list_of_dicts(self):
        result = validate_and_normalize([self._make_offer()])
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_valid_offer_kept(self):
        result = validate_and_normalize([self._make_offer()])
        assert len(result) == 1

    def test_invalid_title_kept_in_non_strict(self):
        offer = self._make_offer(title="X")
        result = validate_and_normalize([offer], strict=False)
        assert len(result) == 1

    def test_invalid_title_dropped_in_strict(self):
        offer = self._make_offer(title="X")
        result = validate_and_normalize([offer], strict=True)
        assert len(result) == 0

    def test_multiple_offers(self):
        offers = [self._make_offer(url=f"https://x.com/{i}") for i in range(5)]
        result = validate_and_normalize(offers)
        assert len(result) == 5

    def test_dataclass_input_supported(self):
        from dataclasses import dataclass, field
        from datetime import datetime

        @dataclass
        class FakeOffer:
            title:         str = "Dev Python"
            company:       str = "Acme"
            location:      str = "Paris"
            contract_type: str = "Alternance"
            salary:        str = ""
            description:   str = "desc"
            url:           str = "https://x.com/99"
            source:        str = "indeed"
            scraped_at:    str = field(default_factory=lambda: datetime.now().isoformat())

        result = validate_and_normalize([FakeOffer()])
        assert len(result) == 1
        assert result[0]["title"] == "Dev Python"
