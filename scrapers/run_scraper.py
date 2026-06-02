"""
scrapers/run_scraper.py
=======================
Point d'entrée standalone pour le scraping de toutes les sources.

Utilisé par GitHub Actions (voir .github/workflows/scrape.yml) et l'API
FastAPI (api/main.py). Peut aussi être lancé manuellement :
    python -m scrapers.run_scraper

Nécessite DATABASE_URL en variable d'environnement pour écrire
dans la base de production. En local sans DATABASE_URL, écrit dans SQLite.
Pour France Travail : nécessite FT_CLIENT_ID et FT_CLIENT_SECRET.
"""

import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# 1. On définit la racine du projet (le dossier parent de scrapers/)
RACINE_PROJET = Path(__file__).parent.parent

# 2. On charge explicitement le .env qui se trouve à cette racine
load_dotenv(dotenv_path=RACINE_PROJET / '.env')

# 3. On ajoute la racine au PYTHONPATH pour les imports
sys.path.insert(0, str(RACINE_PROJET))

from database.db import init_db
from pipeline.deduplicator import process_and_save
from scrapers.indeed import IndeedScraper
from scrapers.france_travail import FranceTravailSource
from scrapers.letudiant import LEtudiantSource
from scrapers.hellowork import fetch_hellowork


async def main() -> None:
    print("[scraper] Initialisation de la base...")
    init_db()

    all_offers = []

    print("[scraper] Démarrage du scraping Indeed...")
    try:
        indeed = IndeedScraper(query="alternance", location="France", max_pages=5)
        all_offers.extend(await indeed.run())
    except Exception as e:
        print(f"[scraper] Erreur Indeed : {e}")
    print(f"[scraper] Total accumulé après Indeed : {len(all_offers)} offres")

    print("[scraper] Démarrage de la source France Travail...")
    try:
        ft = FranceTravailSource(query="alternance", max_results=1000)
        all_offers.extend(await ft.run())
    except Exception as e:
        print(f"[scraper] Erreur France Travail : {e}")
    print(f"[scraper] Total accumulé après France Travail : {len(all_offers)} offres")

    print("[scraper] Démarrage de la source L'Étudiant...")
    try:
        letu = LEtudiantSource(max_pages=20, limit=50)
        all_offers.extend(await letu.run())
    except Exception as e:
        print(f"[scraper] Erreur L'Étudiant : {e}")
    print(f"[scraper] Total accumulé après L'Étudiant : {len(all_offers)} offres")

    print("[scraper] Démarrage de la source HelloWork...")
    try:
        all_offers.extend(await fetch_hellowork())
    except Exception as e:
        print(f"[scraper] Erreur HelloWork : {e}")
    print(f"[scraper] Total accumulé après HelloWork : {len(all_offers)} offres")

    inserted = process_and_save(all_offers)
    print(f"[scraper] Terminé : {inserted} nouvelles offres insérées")


if __name__ == "__main__":
    asyncio.run(main())