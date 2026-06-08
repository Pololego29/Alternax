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

from fastapi import FastAPI, Query, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

# =============================================================================
# 2. CONFIGURATION DES CHEMINS
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
sys.path.insert(0, str(BASE_DIR))

# Imports de tes modules
try:
    from database.db import (
        init_db, get_offers, get_stats, get_dashboard_stats,
        create_user, get_user_by_email, create_session, get_user_by_token,
        delete_session, add_favorite, remove_favorite,
        get_favorite_ids, get_favorite_offers,
    )
    from api.security import hash_password, verify_password, generate_token
    # On importe l'orchestrateur unifié qui exécute TOUTES les sources
    # (Indeed + France Travail + L'Étudiant) PUIS persiste en base.
    from scrapers.run_scraper import main as run_all_scrapers
    logging.info("Modules chargés.")
except ImportError as e:
    logging.error(f"Erreur import : {e}")
    run_all_scrapers = None

# =============================================================================
# 3. CYCLE DE VIE (LIFESPAN)
# =============================================================================
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Alternax] Démarrage et mise à jour des données...")
    init_db()

    if run_all_scrapers:
        # On planifie pour que ça tourne régulièrement (toutes les 30 min)
        # → lance Indeed + France Travail + L'Étudiant + dédup + insert DB
        scheduler.add_job(run_all_scrapers, 'interval', minutes=30, id='scrape_all_job')
        scheduler.start()

        # ACTUALISATION IMMÉDIATE : on lance le scrap tout de suite au démarrage
        asyncio.create_task(run_all_scrapers())

    yield
    if scheduler.running:
        scheduler.shutdown()

# =============================================================================
# 4. APPLICATION ET ROUTES
# =============================================================================
app = FastAPI(title="Alternax API", lifespan=lifespan)

# CORS : on autorise l'URL front explicite (FRONTEND_URL) si elle est fournie,
# et dans tous les cas les déploiements *.vercel.app + le localhost de dev, via
# un regex. Sans ça, le site casse (page vide) dès que l'URL Vercel change ou
# que FRONTEND_URL pointe sur une ancienne URL : le navigateur bloque les appels
# faute d'en-tête Access-Control-Allow-Origin.
_frontend_url = os.environ.get("FRONTEND_URL", "").strip()
_allowed_origins = [_frontend_url] if _frontend_url else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)*vercel\.app|http://localhost(:\d+)?",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
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
    return ["indeed", "france_travail", "letudiant", "hellowork"]


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


# =============================================================================
# 5. AUTHENTIFICATION (connexion simple email + mot de passe)
# =============================================================================

class Credentials(BaseModel):
    email: str
    password: str


def current_user(authorization: str = Header(default="")) -> dict:
    """Dépendance : extrait l'utilisateur depuis l'en-tête `Authorization: Bearer <token>`."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié.")
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée.")
    return user


@app.post("/api/auth/register")
def register(creds: Credentials):
    """Crée un compte et ouvre une session. Retourne un token."""
    email = creds.email.strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Adresse email invalide.")
    if len(creds.password) < 6:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (6 caractères minimum).")
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet email.")

    user = create_user(email, hash_password(creds.password))
    token = generate_token()
    create_session(token, user["id"])
    return {"token": token, "email": email}


@app.post("/api/auth/login")
def login(creds: Credentials):
    """Vérifie les identifiants et ouvre une session. Retourne un token."""
    email = creds.email.strip().lower()
    user = get_user_by_email(email)
    if not user or not verify_password(creds.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")

    token = generate_token()
    create_session(token, user["id"])
    return {"token": token, "email": email}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default=""), user: dict = Depends(current_user)):
    """Ferme la session courante (supprime le token)."""
    token = authorization.removeprefix("Bearer ").strip()
    delete_session(token)
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    """Retourne l'utilisateur courant (sert à valider le token au chargement)."""
    return {"email": user["email"]}


# =============================================================================
# 6. FAVORIS (réservés aux utilisateurs connectés)
# =============================================================================

@app.get("/api/favorites")
def list_favorites(user: dict = Depends(current_user)):
    """Offres mises en favori par l'utilisateur + liste de leurs ids."""
    return {
        "offers": get_favorite_offers(user["id"]),
        "ids": get_favorite_ids(user["id"]),
    }


@app.post("/api/favorites/{offer_id}")
def create_favorite(offer_id: int, user: dict = Depends(current_user)):
    """Ajoute une offre aux favoris."""
    add_favorite(user["id"], offer_id)
    return {"ok": True}


@app.delete("/api/favorites/{offer_id}")
def delete_favorite(offer_id: int, user: dict = Depends(current_user)):
    """Retire une offre des favoris."""
    remove_favorite(user["id"], offer_id)
    return {"ok": True}


# =============================================================================
# 7. FICHIERS DU FRONT À LA RACINE
# =============================================================================
# index.html référence ses assets en racine (/style.css, /config.js, /app.js,
# /logo.png). On monte donc le dossier frontend sur "/" — placé APRÈS toutes les
# routes /api pour qu'il ne serve qu'en dernier recours (fallback). html=True
# fait servir index.html pour "/". Sans ça, le site est cassé en local.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")