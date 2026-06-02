"""Tests unitaires pour utils/exporters.py"""

import csv
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime

import pytest
from utils.exporters import export_csv, export_json, auto_export


# =============================================================================
# Fixture — offres de test
# =============================================================================

@dataclass
class _FakeOffer:
    title:         str = "Dev Python alternance"
    company:       str = "Acme Corp"
    location:      str = "Paris"
    contract_type: str = "Alternance"
    salary:        str = "1 200 €/mois"
    description:   str = "Description du poste"
    url:           str = "https://example.com/job/1"
    source:        str = "indeed"
    scraped_at:    str = field(default_factory=lambda: datetime.now().isoformat())


def _make_offers(n: int = 3) -> list[_FakeOffer]:
    return [_FakeOffer(url=f"https://example.com/job/{i}") for i in range(n)]


# =============================================================================
# export_csv
# =============================================================================

class TestExportCsv:
    def test_creates_file(self, tmp_path):
        path = str(tmp_path / "out.csv")
        result = export_csv(_make_offers(2), filepath=path)
        assert os.path.exists(result)

    def test_correct_row_count(self, tmp_path):
        path = str(tmp_path / "out.csv")
        export_csv(_make_offers(5), filepath=path)
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        assert len(rows) == 5

    def test_contains_expected_headers(self, tmp_path):
        path = str(tmp_path / "out.csv")
        export_csv(_make_offers(1), filepath=path)
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            headers = reader.fieldnames
        assert "title" in headers
        assert "company" in headers
        assert "url" in headers

    def test_data_preserved(self, tmp_path):
        path = str(tmp_path / "out.csv")
        offers = [_FakeOffer(title="Mon super poste", company="MegaCorp")]
        export_csv(offers, filepath=path)
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        assert rows[0]["title"] == "Mon super poste"
        assert rows[0]["company"] == "MegaCorp"

    def test_accepts_dict_input(self, tmp_path):
        path = str(tmp_path / "out.csv")
        offers = [{"title": "Dev", "company": "A", "location": "Paris",
                   "contract_type": "Alternance", "salary": "", "description": "",
                   "url": "https://x.com", "source": "test", "scraped_at": ""}]
        result = export_csv(offers, filepath=path)
        assert os.path.exists(result)

    def test_auto_generates_path_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_csv(_make_offers(1))
        assert result.endswith(".csv")
        assert os.path.exists(result)


# =============================================================================
# export_json
# =============================================================================

class TestExportJson:
    def test_creates_file(self, tmp_path):
        path = str(tmp_path / "out.json")
        result = export_json(_make_offers(2), filepath=path)
        assert os.path.exists(result)

    def test_valid_json_structure(self, tmp_path):
        path = str(tmp_path / "out.json")
        export_json(_make_offers(3), filepath=path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "total" in data
        assert "offers" in data
        assert "exported_at" in data

    def test_correct_offer_count(self, tmp_path):
        path = str(tmp_path / "out.json")
        export_json(_make_offers(4), filepath=path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["total"] == 4
        assert len(data["offers"]) == 4

    def test_data_preserved(self, tmp_path):
        path = str(tmp_path / "out.json")
        offers = [_FakeOffer(title="Poste unique", company="UniqueCompany")]
        export_json(offers, filepath=path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["offers"][0]["title"] == "Poste unique"

    def test_accepts_dict_input(self, tmp_path):
        path = str(tmp_path / "out.json")
        offers = [{"title": "Dev", "company": "A", "location": "Paris",
                   "contract_type": "Alternance", "salary": "", "description": "",
                   "url": "https://x.com", "source": "test", "scraped_at": ""}]
        result = export_json(offers, filepath=path)
        assert os.path.exists(result)

    def test_auto_generates_path_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_json(_make_offers(1))
        assert result.endswith(".json")
        assert os.path.exists(result)


# =============================================================================
# auto_export
# =============================================================================

class TestAutoExport:
    def test_no_export_when_env_empty(self, monkeypatch):
        monkeypatch.delenv("SCRAPER_EXPORT_FORMATS", raising=False)
        result = auto_export(_make_offers(2))
        assert result == []

    def test_csv_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCRAPER_EXPORT_FORMATS", "csv")
        result = auto_export(_make_offers(2))
        assert len(result) == 1
        assert result[0].endswith(".csv")

    def test_json_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCRAPER_EXPORT_FORMATS", "json")
        result = auto_export(_make_offers(2))
        assert len(result) == 1
        assert result[0].endswith(".json")

    def test_csv_and_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCRAPER_EXPORT_FORMATS", "csv,json")
        result = auto_export(_make_offers(2))
        assert len(result) == 2

    def test_unknown_format_ignored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCRAPER_EXPORT_FORMATS", "xml,csv")
        result = auto_export(_make_offers(2))
        assert len(result) == 1
        assert result[0].endswith(".csv")
