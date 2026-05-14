# Alternax — Agrégateur d'offres d'alternance

Plateforme qui collecte automatiquement les offres d'alternance depuis trois sources complémentaires (Indeed, France Travail, L'Étudiant.fr), les déduplique et les expose sur un site web centralisé avec filtres et pagination.

## Fonctionnalités

- **Trois sources actives** combinant scraping HTML (Playwright) et appels API (REST OAuth2 + tRPC)
- **Scraping automatique** toutes les 30 minutes via APScheduler intégré à l'API, et toutes les 3 heures via GitHub Actions
- **Déduplication à deux niveaux** : par URL et par empreinte de contenu (titre + entreprise + lieu)
- **API REST** avec recherche fulltext, filtres par source et localisation, et pagination
- **Interface web** responsive sans framework (HTML/CSS/JS + Tailwind CDN)
- Compatible **Windows et macOS/Linux**

## Sources de données

Alternax agrège les offres d'alternance depuis trois sources complémentaires :

### Indeed
Scraping HTML via Playwright avec gestion de la protection Cloudflare et du mur de connexion. Utilise `playwright-stealth` pour contourner la détection anti-bot. Module : `scrapers/indeed.py`.

### France Travail
Connexion à l'API officielle France Travail (ex-Pôle Emploi) via OAuth2 (flow `client_credentials`). Récupère jusqu'à 1000 offres par run via pagination, filtrées sur les contrats d'alternance (apprentissage + professionnalisation). Les offres sont enrichies avec les grands domaines ROME pour la classification métier. Module : `scrapers/france_travail.py`.

Variables d'environnement requises : `FT_CLIENT_ID`, `FT_CLIENT_SECRET`.

### L'Étudiant.fr
Accès direct à l'API tRPC publique de Piloty (la plateforme qui propulse jobs-stages.letudiant.fr). Identifiée par inspection réseau du frontend, cette API ne nécessite aucune authentification et permet de récupérer ~1000 offres par run via pagination par curseur. Plus stable et plus rapide qu'un scraping HTML classique. Module : `scrapers/letudiant.py`.

### Orchestration

Les trois sources sont exécutées séquentiellement par `scrapers/run_scraper.py`, avec gestion d'erreur isolée par source (un crash sur une source ne bloque pas les autres). Les offres sont ensuite dédupliquées et insérées en base via `pipeline/deduplicator.py`.

## Architecture

```
Scrapers (Playwright + httpx)
    │  Liste de JobOffer
    ▼
Pipeline (déduplication MD5)
    │  Offres uniques
    ▼
Database (SQLite / PostgreSQL)
    │  Requêtes SQL
    ▼
API (FastAPI + APScheduler)
    │  JSON via HTTP
    ▼
Frontend (HTML / JS vanilla)
```

```
Alternax/
├── requirements.txt              # Dépendances API (FastAPI, uvicorn…)
├── requirements-scraper.txt      # Dépendances scraping (Playwright, httpx…)
├── .env                          # Credentials locaux (gitignoré)
├── .github/
│   └── workflows/
│       └── scrape.yml            # Cron GitHub Actions (toutes les 3h)
├── scrapers/
│   ├── indeed.py                 # Scraper Indeed (Playwright + stealth)
│   ├── france_travail.py         # Source France Travail (OAuth2 + REST)
│   ├── letudiant.py              # Source L'Étudiant (tRPC public)
│   └── run_scraper.py            # Orchestrateur multi-sources
├── pipeline/
│   └── deduplicator.py           # Déduplication avant insertion BDD
├── database/
│   └── db.py                     # Schéma, CRUD, connexion
├── api/
│   └── main.py                   # FastAPI + scheduler APScheduler
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js
```

## Stack technique

| Couche | Technologie |
|---|---|
| Scraping HTML | Python · Playwright (Chromium) · playwright-stealth |
| Appels API | httpx · OAuth2 (France Travail) · tRPC (L'Étudiant) |
| Pipeline | Python · hashlib (MD5) |
| Base de données | SQLite (par défaut) · PostgreSQL (via `DATABASE_URL`) |
| API | FastAPI · Uvicorn · APScheduler |
| Frontend | HTML · CSS · JavaScript vanilla · Tailwind CDN |
| CI / Scheduling | GitHub Actions (cron) |

## Installation

```bash
# 1. Environnement virtuel
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows

# 2. Dépendances Python
pip install -r requirements.txt
pip install -r requirements-scraper.txt

# 3. Navigateur Playwright (pour Indeed uniquement)
playwright install chromium
```

### Variables d'environnement

Pour utiliser la source France Travail, crée un fichier `.env` à la racine du projet :

```
FT_CLIENT_ID=ton_client_id
FT_CLIENT_SECRET=ton_client_secret
```

Les credentials s'obtiennent gratuitement en créant une application sur [francetravail.io](https://francetravail.io) et en activant les APIs "Offres d'emploi v2" et "ROME 4.0 - Métiers".

En production (hébergeur ou GitHub Actions), ces variables sont injectées via les secrets de la plateforme.

## Lancer le projet

### Mode complet (API + scraping automatique)

```bash
uvicorn api.main:app --reload --port 8000
```

- Site vitrine → [http://localhost:8000](http://localhost:8000)
- Documentation API interactive → [http://localhost:8000/docs](http://localhost:8000/docs)

Au démarrage, un scraping se lance immédiatement en tâche de fond. Les suivants s'exécutent automatiquement toutes les 30 minutes.

### Mode scraping seul

```bash
python -m scrapers.run_scraper
```

Lance les trois sources dans l'ordre (Indeed → France Travail → L'Étudiant), affiche le total accumulé après chaque source, puis dédoublonne et insère en base.

## Endpoints API

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | Site vitrine (index.html) |
| `GET` | `/api/offres` | Liste paginée avec filtres |
| `GET` | `/api/stats` | Total, répartition par source, dernier scraping |
| `GET` | `/api/sources` | Sources disponibles (`indeed`, `france_travail`, `letudiant`) |

**Paramètres de `/api/offres` :**

| Paramètre | Type | Description |
|---|---|---|
| `search` | string | Recherche dans titre, entreprise, description |
| `location` | string | Filtre ville/région (partiel) |
| `source` | string | Filtre par source (`indeed`, `france_travail`, `letudiant`) |
| `page` | int | Numéro de page (défaut : 1) |
| `per_page` | int | Résultats par page (défaut : 20) |

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
    source        : str   # Identifiant de la source ("indeed", "france_travail", "letudiant")
    scraped_at    : str   # Horodatage ISO 8601
    category      : str   # Catégorie métier (grand domaine ROME pour FT, catégorie Piloty pour L'Étudiant)
```

Chaque nouvelle source doit retourner des `JobOffer` — le pipeline et la base n'ont pas à changer.

## Stratégie anti-détection (Indeed)

Contrairement à France Travail et L'Étudiant qui exposent des APIs publiques, Indeed protège ses pages contre le scraping. Techniques utilisées :

- **`playwright-stealth`** — masquage des empreintes navigateur classiques (webdriver, plugins, langues…)
- **Gestion de la protection Cloudflare** — attente automatique du challenge "Un instant…"
- **Rotation des User-Agents** — pool de UA Chrome/Firefox réalistes
- **Warm-up** — visite de la page d'accueil avant la recherche
- **Navigation via le bouton "Suivant"** — clics réels, pas d'URLs directes
- **Scroll humain progressif** — défilement aléatoire par paliers
- **Délais aléatoires** entre pages (5–9 secondes)
- **Retry automatique** en cas de timeout

## Roadmap

- [x] **Phase 1** — Scraper Indeed (Playwright) + pipeline + API + frontend
- [x] **Phase 2** — Intégration France Travail (OAuth2 + enrichissement ROME)
- [x] **Phase 3** — Intégration L'Étudiant.fr (API tRPC publique)
- [ ] **Phase 4** — Scrapers HelloWork, APEC, LinkedIn
- [ ] **Phase 5** — NLP : extraction de compétences, classification par domaine (spaCy / BERT)
- [ ] **Phase 6** — Recommandation personnalisée par profil utilisateur
- [ ] **Phase 7** — Production : PostgreSQL · Docker · déploiement VPS

## Dépendances principales

```
fastapi>=0.111           # Framework API REST asynchrone
uvicorn[standard]>=0.29  # Serveur ASGI
apscheduler>=3.10        # Scheduler cron intégré
playwright>=1.44.0       # Pilotage de Chromium (Indeed)
playwright-stealth>=2.0  # Masquage anti-détection
httpx>=0.27.0            # Client HTTP asynchrone (France Travail, L'Étudiant)
python-dotenv>=1.0.0     # Chargement des variables d'environnement
python-multipart>=0.0.9  # Formulaires FastAPI
psycopg2-binary>=2.9     # Driver PostgreSQL (production)
```