"""
scrapers/run_scraper.py
=======================
Point d'entrée standalone pour le scraping.

Utilisé par GitHub Actions (voir .github/workflows/scrape.yml).
Peut aussi être lancé manuellement : python -m scrapers.run_scraper

Nécessite DATABASE_URL en variable d'environnement pour écrire
dans la base de production. En local sans DATABASE_URL, écrit dans SQLite.

Améliorations :
- Gestion d'erreurs robuste
- Logging structuré
- Arguments en ligne de commande
- Métriques de performance
- Support pour plusieurs scrapers
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db
from pipeline.deduplicator import process_and_save
from scrapers.indeed import IndeedScraper, JobOffer


def setup_logging(verbose: bool = False) -> None:
    """Configure le logging pour le scraper."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('scraper.log', mode='a', encoding='utf-8')
        ]
    )


async def run_scraper(scraper_name: str, query: str, location: str, max_pages: int) -> List[JobOffer]:
    """
    Exécute un scraper spécifique avec les paramètres donnés.

    Args:
        scraper_name: Nom du scraper ("indeed")
        query: Terme de recherche
        location: Localisation
        max_pages: Nombre maximum de pages

    Returns:
        Liste des offres collectées

    Raises:
        ValueError: Si le scraper n'est pas supporté
    """
    logger = logging.getLogger(__name__)

    if scraper_name.lower() == "indeed":
        scraper = IndeedScraper(query=query, location=location, max_pages=max_pages)
        logger.info(f"Démarrage du scraping Indeed: {query} à {location} ({max_pages} pages max)")
        return await scraper.run()
    else:
        raise ValueError(f"Scraper '{scraper_name}' non supporté. Scrapers disponibles: indeed")


async def main() -> None:
    """Fonction principale du scraper."""
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Lance le scraping d'offres d'alternance")
    parser.add_argument("--scraper", default="indeed", help="Scraper à utiliser (défaut: indeed)")
    parser.add_argument("--query", default="alternance", help="Terme de recherche (défaut: alternance)")
    parser.add_argument("--location", default="France", help="Localisation (défaut: France)")
    parser.add_argument("--max-pages", type=int, default=5, help="Nombre max de pages (défaut: 5)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mode verbose")
    parser.add_argument("--dry-run", action="store_true", help="Ne pas sauvegarder en base")

    args = parser.parse_args()
    setup_logging(args.verbose)

    start_time = time.time()

    try:
        logger.info("=== DÉMARRAGE DU SCRAPER ===")

        # Initialisation de la base
        logger.info("Initialisation de la base de données...")
        init_db()
        logger.info("Base de données initialisée avec succès")

        # Exécution du scraping
        offers = await run_scraper(args.scraper, args.query, args.location, args.max_pages)

        # Statistiques
        scraping_time = time.time() - start_time
        logger.info(f"Scraping terminé en {scraping_time:.2f}s - {len(offers)} offres collectées")

        if not args.dry_run:
            # Sauvegarde en base
            logger.info("Sauvegarde des offres en base...")
            inserted = process_and_save(offers)
            logger.info(f"Sauvegarde terminée : {inserted} nouvelles offres insérées")
        else:
            logger.info("Mode dry-run : aucune sauvegarde effectuée")

        logger.info("=== SCRAPER TERMINÉ AVEC SUCCÈS ===")

    except Exception as e:
        logger.error(f"Erreur lors du scraping: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
