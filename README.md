# Groupax — Agrégateur d'offres d'alternance

Plateforme qui collecte automatiquement les offres d'alternance depuis plusieurs sources (Indeed, bientôt HelloWork, APEC…), les déduplique et les expose sur un site web centralisé avec filtres et pagination.

## Fonctionnalités

- **Scraping automatique** toutes les 6 heures via APScheduler
- **Déduplication à deux niveaux** : par URL et par empreinte de contenu (titre + entreprise + lieu)
- **API REST** avec recherche fulltext, filtres et pagination
- **Interface web** responsive sans framework (HTML/CSS/JS + Tailwind CDN)
- **Déclenchement manuel** du scraping depuis le bouton "Actualiser" du site
- Compatible **Windows et macOS/Linux**

## Architecture

```
Scrapers (Playwright)
    │  Liste de JobOffer
    ▼
Pipeline (déduplication MD5)
    │  Offres uniques
    ▼
Database (SQLite)
    │  Requêtes SQL
    ▼
API (FastAPI)
    │  JSON via HTTP
    ▼
Frontend (HTML / JS vanilla)
```

```
Alternax/
├── run.py                  # Point d'entrée (fix ProactorEventLoop Windows)
├── requirements.txt
├── scrapers/
│   └── indeed.py           # Scraper Indeed France (Playwright)
├── pipeline/
│   └── deduplicator.py     # Déduplication avant insertion BDD
├── database/
│   └── db.py               # SQLite — schéma, CRUD, connexion
├── api/
│   └── main.py             # FastAPI + scheduler APScheduler
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── data/                   # Données locales (gitignorées)
    ├── offers.db
    ├── indeed_offers.csv
    └── indeed_offers.json
```

## Stack technique

| Couche | Technologie |
|---|---|
| Scraping | Python · Playwright (Chromium) |
| Pipeline | Python · hashlib (MD5) |
| Base de données | SQLite (sqlite3 stdlib) |
| API | FastAPI · Uvicorn · APScheduler |
| Frontend | HTML · CSS · JavaScript vanilla · Tailwind CDN |

## Installation

```bash
# 1. Environnement virtuel
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows

# 2. Dépendances Python
pip install -r requirements.txt

# 3. Navigateur Playwright
playwright install chromium
```

## Lancer le projet

```bash
python run.py
```

- Site vitrine → [http://localhost:8000](http://localhost:8000)
- Documentation API interactive → [http://localhost:8000/docs](http://localhost:8000/docs)

Au premier démarrage, si la base est vide, un scraping se lance immédiatement. Les suivants s'exécutent automatiquement toutes les 6 heures.

## Lancer le scraper seul (sans serveur)

```bash
python scrapers/indeed.py
```

Exporte les résultats dans `data/indeed_offers.csv` et `data/indeed_offers.json`.

## Endpoints API

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | Site vitrine (index.html) |
| `GET` | `/api/offres` | Liste paginée avec filtres |
| `GET` | `/api/stats` | Total, par source, dernier scraping |
| `GET` | `/api/sources` | Sources disponibles |
| `POST` | `/api/scrape` | Déclenche un scraping immédiat |

**Paramètres de `/api/offres` :**

| Paramètre | Type | Description |
|---|---|---|
| `search` | string | Recherche dans titre, entreprise, description |
| `location` | string | Filtre ville/région (partiel) |
| `source` | string | Filtre par source (`indeed`, …) |
| `page` | int | Numéro de page (défaut : 1) |
| `per_page` | int | Résultats par page (défaut : 20, max : 100) |

## Modèle de données

Toute la chaîne repose sur un `dataclass` commun :

```python
@dataclass
class JobOffer:
    title         : str   # Intitulé du poste
    company       : str   # Nom de l'entreprise
    location      : str   # Ville ou région
    contract_type : str   # Type de contrat
    salary        : str   # Rémunération (vide si non renseignée)
    description   : str   # Extrait de la description
    url           : str   # Lien unique (clé de déduplication)
    source        : str   # Identifiant de la source ("indeed"…)
    scraped_at    : str   # Horodatage ISO 8601
```

Chaque futur scraper (HelloWork, APEC…) doit retourner des `JobOffer` — le pipeline et la base n'ont pas à changer.

## Stratégie anti-détection (Indeed)

Indeed charge ses offres via JavaScript et détecte les bots. Techniques utilisées :

- **`headless=False`** — fenêtre Chromium visible, moins détectable
- **Masquage de `navigator.webdriver`** — script injecté au démarrage
- **Rotation des User-Agents** — pool de 4 UA Chrome/Firefox réalistes
- **Warm-up** — visite de la page d'accueil avant la recherche
- **Navigation via le bouton "Suivant"** — clics réels, pas d'URLs directes
- **Scroll humain progressif** — défilement aléatoire par paliers
- **Délais aléatoires** entre pages (5–9 secondes)
- **Retry automatique** en cas de timeout (2 tentatives max)

## Roadmap

- [ ] **Phase 2** — Scrapers HelloWork, APEC, LinkedIn
- [ ] **Phase 3** — NLP : extraction de compétences, classification par domaine (spaCy / BERT)
- [ ] **Phase 4** — Recommandation personnalisée par profil utilisateur
- [ ] **Phase 5** — Production : PostgreSQL · Docker · déploiement VPS

## Dépendances

```
playwright>=1.44.0       # Pilotage de Chromium
pandas>=2.2.0            # Manipulation de données (préparation NLP)
fastapi>=0.111           # Framework API REST asynchrone
uvicorn[standard]>=0.29  # Serveur ASGI
apscheduler>=3.10        # Scheduler cron intégré
python-multipart>=0.0.9  # Formulaires FastAPI
```
