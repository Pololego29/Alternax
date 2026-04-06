"""
api/main.py
===========
Backend FastAPI — sert les offres et orchestre le scraping automatique.

Endpoints :
    GET /api/offres      Liste paginée avec filtres
    GET /api/stats       Statistiques globales
    GET /api/sources     Sources disponibles
    POST /api/scrape     Déclenche un scraping manuel

Scheduler :
    Le scraper Indeed tourne automatiquement toutes les 6h via APScheduler.

Lancer le serveur :
    uvicorn api.main:app --reload --port 8000

Le site vitrine est servi depuis frontend/ sur http://localhost:8000
"""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Executor dédié au scraping (1 seul thread — on ne veut pas plusieurs scrapers en parallèle)
_scraper_executor = ThreadPoolExecutor(max_workers=1)

# Ajoute la racine du projet au path pour les imports relatifs
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_offers, get_stats
from pipeline.deduplicator import process_and_save
from scrapers.indeed import IndeedScraper


# =============================================================================
# SECTION 1 – TÂCHE DE SCRAPING
# =============================================================================

def _scrape_sync() -> None:
    """
    Version synchrone du scraping, exécutée dans un thread dédié.

    Sur Windows, uvicorn utilise SelectorEventLoop qui ne supporte pas
    asyncio.create_subprocess_exec (requis par Playwright). En lançant
    le scraper dans un thread séparé, on crée un ProactorEventLoop
    indépendant de celui de FastAPI — compatible avec Playwright.
    """
    # Nouveau ProactorEventLoop dans ce thread (indépendant de FastAPI)
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        scraper = IndeedScraper(query="alternance", location="France", max_pages=5)
        offers = await scraper.run()
        inserted = process_and_save(offers)
        print(f"[scheduler] Scraping terminé — {inserted} nouvelles offres ajoutées")

    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


async def run_scraping_job() -> None:
    """
    Tâche lancée par le scheduler toutes les 6h.
    Délègue le scraping à un thread avec son propre event loop (fix Windows).
    """
    print("\n[scheduler] Démarrage du scraping automatique...")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_scraper_executor, _scrape_sync)
    except Exception as e:
        print(f"[scheduler] Erreur durant le scraping : {e}")


# =============================================================================
# SECTION 2 – DÉMARRAGE / ARRÊT DE L'APPLICATION
# =============================================================================

scheduler = AsyncIOScheduler(timezone="Europe/Paris")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère le cycle de vie de l'application FastAPI.

    Au démarrage :
    - Initialise la base de données
    - Lance le scheduler (scraping toutes les 6h)
    - Effectue un premier scraping immédiat si la base est vide

    À l'arrêt :
    - Arrête proprement le scheduler
    """
    # Initialisation BDD
    init_db()
    print("[api] Base de données initialisée")

    # Scheduler : scraping toutes les 6h
    scheduler.add_job(
        run_scraping_job,
        trigger="interval",
        hours=6,
        id="indeed_scraper",
        replace_existing=True,
    )
    scheduler.start()
    print("[api] Scheduler démarré — scraping toutes les 6h")

    # Premier scraping au démarrage si la base est vide
    stats = get_stats()
    if stats["total"] == 0:
        print("[api] Base vide — premier scraping lancé...")
        asyncio.create_task(run_scraping_job())

    yield  # L'application tourne ici

    scheduler.shutdown()
    print("[api] Scheduler arrêté")


# =============================================================================
# SECTION 3 – APPLICATION FASTAPI
# =============================================================================

app = FastAPI(
    title="Groupax – API Alternances",
    description="Offres d'alternance collectées automatiquement",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS : autorise le frontend (même origine en prod, localhost en dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Sert les fichiers statiques du frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# =============================================================================
# SECTION 4 – ENDPOINTS API
# =============================================================================

@app.get("/")
async def serve_frontend():
    """Sert la page d'accueil du site vitrine."""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/offres")
async def list_offres(
    search:   str = Query("", description="Recherche dans titre, entreprise, description"),
    location: str = Query("", description="Filtre par ville/région"),
    source:   str = Query("", description="Filtre par source (indeed, hellowork…)"),
    page:     int = Query(1,  ge=1, description="Numéro de page"),
    per_page: int = Query(20, ge=1, le=100, description="Offres par page"),
):
    """
    Retourne la liste des offres avec filtres et pagination.

    Exemple : GET /api/offres?search=data&location=Paris&page=2
    """
    offers, total = get_offers(
        search=search,
        location=location,
        source=source,
        page=page,
        per_page=per_page,
    )
    return {
        "offers": offers,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, -(-total // per_page)),  # ceil division
    }


@app.get("/api/stats")
async def stats():
    """Retourne les statistiques globales (total, par source, dernière collecte)."""
    return get_stats()


@app.get("/api/sources")
async def sources():
    """Liste les sources disponibles pour le filtre du frontend."""
    s = get_stats()
    return list(s["by_source"].keys())


@app.post("/api/scrape")
async def trigger_scrape():
    """
    Déclenche un scraping manuel immédiat.
    Utile pour tester ou forcer une mise à jour sans attendre les 6h.
    """
    asyncio.create_task(run_scraping_job())
    return {"message": "Scraping lancé en arrière-plan"}
