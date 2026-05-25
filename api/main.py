import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

# =============================================================================
# 1. FIX WINDOWS (DOIT ÊTRE LA PREMIÈRE LIGNE)
# =============================================================================
# Ce moteur est le SEUL capable de gérer les processus Playwright sur Windows.
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- Chargement des variables d'environnement depuis .env ---
# Nécessaire pour que FT_CLIENT_ID et FT_CLIENT_SECRET soient disponibles
# quand on lance l'API en local. En prod (GitHub Actions, Render…), les
# variables sont déjà injectées par la plateforme, donc load_dotenv ne fera rien.
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# =============================================================================
# 2. CONFIGURATION DES CHEMINS
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
sys.path.insert(0, str(BASE_DIR))

# Imports de tes modules
try:
    from database.db import init_db, get_offers, get_stats, get_dashboard_stats
    # On importe l'orchestrateur unifié qui exécute TOUTES les sources
    # (Indeed + France Travail + L'Étudiant) PUIS persiste en base.
    from scrapers.run_scraper import main as run_all_scrapers
    logging.info("✅ Modules chargés.")
except ImportError as e:
    logging.error(f"⚠️ Erreur import : {e}")
    run_all_scrapers = None

# =============================================================================
# 3. CYCLE DE VIE (LIFESPAN)
# =============================================================================
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 [Alternax] Démarrage et mise à jour des données...")
    init_db()

    if run_all_scrapers:
        # On planifie pour que ça tourne régulièrement (toutes les 30 min)
        # → lance Indeed + France Travail + L'Étudiant + dédup + insert DB
        scheduler.add_job(run_all_scrapers, 'interval', minutes=30, id='scrape_all_job')
        scheduler.start()

        # ACTUALISATION IMMÉDIATE : on lance le scrap tout de suite au démarrage
        asyncio.create_task(run_all_scrapers())

    yield
    scheduler.shutdown()

# =============================================================================
# 4. APPLICATION ET ROUTES
# =============================================================================
app = FastAPI(title="Alternax API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Montage pour le logo et les fichiers du front
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
async def serve_home():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/sources")
async def list_sources():
    """Retourne la liste des sources disponibles pour le frontend"""
    return ["indeed", "france_travail", "letudiant"]


@app.get("/api/offres")
async def list_offres(
    search: str = "",
    location: str = "",
    source: str = "",
    tech: str = "",
    page: int = 1,
    per_page: int = 20,
):
    """
    Liste paginée des offres avec filtres optionnels.

    Paramètres :
    - search   : recherche fulltext dans titre, entreprise, description
    - location : filtre par ville/région (partial match)
    - source   : filtre par source (indeed, france_travail, letudiant)
    - tech     : filtre par tag technique (ex: "Python", "React")
    - page     : numéro de page (défaut 1)
    - per_page : nombre d'offres par page (défaut 20)
    """
    offers, total = get_offers(
        search=search, location=location, source=source, tech=tech,
        page=page, per_page=per_page,
    )
    return {
        "offers": offers,
        "total":  total,
        "page":   page,
        "pages":  max(1, -(-total // per_page)),
    }


@app.get("/api/stats")
async def api_stats():
    """Stats globales : total, répartition par source, dernière collecte."""
    return get_stats()


@app.get("/api/dashboard")
async def api_dashboard(limit: int = 5):
    """
    Stats agrégées pour le dashboard frontend :
    - top entreprises qui recrutent
    - top localisations
    - top technologies demandées
    - répartition par source
    """
    return get_dashboard_stats(limit=limit)