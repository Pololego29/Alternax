"""
scrapers/run_scraper.py
=======================
Point d'entrée standalone pour le scraping.

Utilisé par GitHub Actions (voir .github/workflows/scrape.yml).
Peut aussi être lancé manuellement : python -m scrapers.run_scraper

Nécessite DATABASE_URL en variable d'environnement pour écrire
dans la base de production. En local sans DATABASE_URL, écrit dans SQLite.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db
from pipeline.deduplicator import process_and_save
from scrapers.indeed import IndeedScraper
from scrapers.hellowork import HelloWorkScraper


async def main() -> None:
    print("[scraper] Initialisation de la base...")
    init_db()

    all_offers = []

    # --- Indeed ---
    print("\n[scraper] Démarrage du scraping Indeed...")
    indeed_scraper = IndeedScraper(query="alternance", location="France", max_pages=5)
    indeed_offers = await indeed_scraper.run()
    all_offers.extend(indeed_offers)
    print(f"[scraper] Indeed : {len(indeed_offers)} offres récupérées")

    # --- HelloWork ---
    print("\n[scraper] Démarrage du scraping HelloWork...")
    hellowork_scraper = HelloWorkScraper(query="alternance", location="France", max_pages=5)
    hellowork_offers = await hellowork_scraper.run()
    all_offers.extend(hellowork_offers)
    print(f"[scraper] HelloWork : {len(hellowork_offers)} offres récupérées")

    # --- Déduplication & sauvegarde globale ---
    print(f"\n[scraper] Total brut toutes sources : {len(all_offers)} offres")
    inserted = process_and_save(all_offers)
    print(f"[scraper] Terminé : {inserted} nouvelles offres insérées")


if __name__ == "__main__":
    asyncio.run(main())
