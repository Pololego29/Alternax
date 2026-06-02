# Alternax — Agrégateur d'offres d'alternance

Plateforme qui collecte automatiquement les offres d'alternance depuis quatre sources complémentaires (Indeed, France Travail, L'Étudiant.fr, HelloWork), les déduplique, les enrichit automatiquement avec des tags techniques, et les expose sur un site web centralisé avec filtres, dashboard analytique et pagination.

## Fonctionnalités

- **Quatre sources actives** combinant scraping HTML (Playwright + httpx/BeautifulSoup) et appels API (REST OAuth2 + tRPC)
- **Scraping automatique** toutes les 30 minutes via APScheduler intégré à l'API, et toutes les 3 heures via GitHub Actions
- **Déduplication à deux niveaux** : par URL et par empreinte de contenu (titre + entreprise + lieu)
- **Enrichissement automatique par tags techniques** : extraction de 45 mots-clés (langages, frameworks, cloud, data, méthodologies) sur titre + description, sans dépendance externe
- **Dashboard analytique** : top entreprises qui recrutent, top localisations, top technologies demandées, répartition par source
- **API REST** avec recherche fulltext, filtres par source, localisation et tag technique, et pagination
- **Interface web** responsive sans framework (HTML/CSS/JS + Tailwind CDN), tags cliquables pour filtrer
- **Tests unitaires** pytest (28 tests verts couvrant l'enrichissement et le parser HelloWork)
- Compatible **Windows et macOS/Linux**

## Sources de données

Alternax agrège les offres d'alternance depuis quatre sources complémentaires :

### Indeed
Scraping HTML via Playwright avec gestion de la protection Cloudflare et du mur de connexion. Utilise `playwright-stealth` pour contourner la détection anti-bot. Stratégie **multi-requêtes** : plutôt qu'une seule recherche `alternance France` (qui retournerait toujours les mêmes ~16 résultats sponsorisés), on lance **11 requêtes ciblées** (par métier + par ville) dans la même session Chromium, ce qui porte le volume à ~80-130 offres uniques par run. Module : `scrapers/indeed.py`.

### France Travail
Connexion à l'API officielle France Travail (ex-Pôle Emploi) via OAuth2 (flow `client_credentials`). Récupère jusqu'à 1000 offres par run via pagination, filtrées sur les contrats d'alternance (apprentissage + professionnalisation). Les offres sont enrichies avec les grands domaines ROME pour la classification métier. Module : `scrapers/france_travail.py`.

Variables d'environnement requises : `FT_CLIENT_ID`, `FT_CLIENT_SECRET`.

### L'Étudiant.fr
Accès direct à l'API tRPC publique de Piloty (la plateforme qui propulse jobs-stages.letudiant.fr). Identifiée par inspection réseau du frontend, cette API ne nécessite aucune authentification et permet de récupérer ~1000 offres par run via pagination par curseur. Plus stable et plus rapide qu'un scraping HTML classique. Module : `scrapers/letudiant.py`.

### HelloWork
Scraping HTML via httpx + BeautifulSoup. HelloWork sert son HTML rendu côté serveur, ce qui permet d'éviter Playwright et tourne en quelques secondes au lieu de quelques minutes. La pagination par URL n'étant pas exposée publiquement, le scraper combine **34 URLs de catégories différentes** (18 domaines + 14 villes + 2 mots-clés transverses) pour récupérer ~500-700 offres uniques par run avec une bonne diversité sectorielle et géographique — couvre tous les profils étudiants, pas seulement la tech. Module : `scrapers/hellowork.py`.

### Orchestration

Les quatre sources sont exécutées séquentiellement par `scrapers/run_scraper.py`, avec gestion d'erreur isolée par source (un crash sur une source ne bloque pas les autres). Les offres passent ensuite par le pipeline (déduplication + enrichissement par tags techniques) via `pipeline/deduplicator.py` et `pipeline/enrichment.py`, avant insertion en base.

## Architecture

```
Scrapers (Playwright + httpx + BeautifulSoup)
    │  Liste de JobOffer
    ▼
Pipeline (déduplication MD5 + enrichissement par tags)
    │  Offres uniques et taguées
    ▼
Database (SQLite / PostgreSQL)
    │  Requêtes SQL
    ▼
API (FastAPI + APScheduler)
    │  JSON via HTTP
    ▼
Frontend (HTML / JS vanilla + dashboard analytique)
```

```
Alternax/
├── run.py                        # Lancement du serveur (utile sous Windows)
├── Procfile                      # Commande de démarrage (déploiement)
├── requirements.txt              # Dépendances API (FastAPI, uvicorn, APScheduler…)
├── requirements-scraper.txt      # Dépendances scraping (Playwright, httpx, BS4…)
├── .env                          # Credentials locaux (gitignoré)
├── .github/
│   └── workflows/
│       └── scrape.yml            # Cron GitHub Actions (toutes les 3h)
├── scrapers/
│   ├── indeed.py                 # Scraper Indeed (Playwright + stealth + multi-requêtes)
│   ├── france_travail.py         # Source France Travail (OAuth2 + REST)
│   ├── letudiant.py              # Source L'Étudiant (tRPC public)
│   ├── hellowork.py              # Scraper HelloWork (httpx + BeautifulSoup)
│   └── run_scraper.py            # Orchestrateur multi-sources
├── pipeline/
│   ├── deduplicator.py           # Déduplication avant insertion BDD
│   └── enrichment.py             # Extraction de 45 tags techniques
├── database/
│   └── db.py                     # Schéma, CRUD, dashboard, connexion
├── api/
│   └── main.py                   # FastAPI + scheduler APScheduler
├── frontend/
│   ├── index.html                # Dashboard + liste + filtres
│   ├── style.css
│   ├── config.js                 # URL de l'API (local / production)
│   └── app.js
└── tests/
    ├── test_enrichment.py        # 15 tests sur l'extraction de tags
    └── test_hellowork.py         # 13 tests sur le parser HelloWork
```

## Stack technique

| Couche | Technologie |
|---|---|
| Scraping HTML (lourd) | Python · Playwright (Chromium) · playwright-stealth |
| Scraping HTML (léger) | Python · httpx · BeautifulSoup |
| Appels API | httpx · OAuth2 (France Travail) · tRPC (L'Étudiant) |
| Pipeline | Python · hashlib (MD5) · regex (extraction de tags) |
| Base de données | SQLite (par défaut) · PostgreSQL (via `DATABASE_URL`) |
| API | FastAPI · Uvicorn · APScheduler |
| Frontend | HTML · CSS · JavaScript vanilla · Tailwind CDN |
| Tests | pytest |
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

```bash
FT_CLIENT_ID=ton_client_id
FT_CLIENT_SECRET=ton_client_secret
INDEED_HEADLESS=0
```

`INDEED_HEADLESS=0` force le navigateur Indeed à s'ouvrir en mode visible (sans cela, Cloudflare bloque systématiquement les requêtes headless en local).

Les credentials France Travail s'obtiennent gratuitement en créant une application sur [francetravail.io](https://francetravail.io) et en activant les APIs "Offres d'emploi v2" et "ROME 4.0 - Métiers".

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

Lance les quatre sources dans l'ordre (Indeed → France Travail → L'Étudiant → HelloWork), affiche le total accumulé après chaque source, puis enrichit (tags techniques), dédoublonne et insère en base.

### Lancer les tests

```bash
pip install pytest          # non inclus dans les requirements
python -m pytest tests/ -v
```

Affiche les 28 tests unitaires (15 sur l'extraction de tags + 13 sur le parser HelloWork). Aucune dépendance réseau, exécution en moins d'une seconde.

## Endpoints API

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | Site vitrine (index.html) |
| `GET` | `/api/offres` | Liste paginée avec filtres |
| `GET` | `/api/stats` | Total, répartition par source, dernier scraping |
| `GET` | `/api/dashboard` | Top entreprises, lieux, technos, sources (agrégations) |
| `GET` | `/api/sources` | Sources disponibles (`indeed`, `france_travail`, `letudiant`, `hellowork`) |

**Paramètres de `/api/offres` :**

| Paramètre | Type | Description |
|---|---|---|
| `search` | string | Recherche dans titre, entreprise, description |
| `location` | string | Filtre ville/région (partiel) |
| `source` | string | Filtre par source (`indeed`, `france_travail`, `letudiant`, `hellowork`) |
| `tech` | string | Filtre par tag technique (ex: `Python`, `React`, `Data Science`) |
| `page` | int | Numéro de page (défaut : 1) |
| `per_page` | int | Résultats par page (défaut : 20) |

**Paramètres de `/api/dashboard` :**

| Paramètre | Type | Description |
|---|---|---|
| `limit` | int | Nombre d'éléments par catégorie (défaut : 5) |

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
    source        : str   # Identifiant de la source
    scraped_at    : str   # Horodatage ISO 8601
    category      : str   # Domaine métier (renseigné par France Travail / L'Étudiant)
```

Les `tech_tags` (Python, React, AWS…) ne sont pas portés par le scraper : ils sont
calculés automatiquement à partir du titre et de la description **au moment de
l'insertion en base** (voir `pipeline/enrichment.py`), puis stockés dans la colonne
`tech_tags` de la table `offers`.

Chaque nouvelle source doit retourner des `JobOffer` — le pipeline et la base n'ont pas à changer.

## Enrichissement par tags techniques

Le module `pipeline/enrichment.py` scanne le titre et la description de chaque offre à l'insertion et détecte les technologies mentionnées dans un dictionnaire de **45 mots-clés** :

- **Langages** : Python, JavaScript, TypeScript, Java, PHP, SQL…
- **Frameworks** : React, Vue, Angular, Node.js, Django, FastAPI, Symfony, Spring…
- **Bases de données** : PostgreSQL, MongoDB, MySQL…
- **Cloud / DevOps** : AWS, Azure, GCP, Docker, Kubernetes, Linux, CI/CD…
- **Data / IA** : Data Science, Machine Learning, Deep Learning, NLP, Pandas, TensorFlow, PyTorch, Power BI…
- **Méthodologies & outils** : Agile, Scrum, GitHub, GitLab, Cybersécurité…

La détection utilise des regex avec `\b` (word boundary) pour éviter les faux positifs classiques (le mot `Java` ne matche pas `JavaScript`, `Python` ne matche pas `Pythonista`). Les variantes orthographiques (`vue.js` et `vuejs`) sont normalisées vers le même tag.

Les tags sont stockés en JSON dans la colonne `tech_tags` de la table `offers`, et exploités côté frontend pour le filtrage en un clic et le dashboard analytique.

## Stratégie anti-détection (Indeed)

Contrairement à France Travail, L'Étudiant et HelloWork qui exposent des contenus accessibles sans contournement, Indeed protège ses pages contre le scraping. Techniques utilisées :

- **`playwright-stealth`** — masquage des empreintes navigateur classiques (webdriver, plugins, langues…)
- **Mode visible** (`headless=False`) — Cloudflare détecte trop facilement le mode headless
- **Gestion de la protection Cloudflare** — attente automatique du challenge "Un instant…"
- **Rotation des User-Agents** — pool de UA Chrome/Firefox réalistes
- **Warm-up** — visite de la page d'accueil avant les recherches
- **Stratégie multi-requêtes** — Indeed force la connexion à partir de la page 2 (paramètre `branding=page-two-signin`), on compense en lançant **11 requêtes ciblées différentes** (par métier + par ville) dans la même session Chromium, ce qui porte le volume de ~16 à **~80-130 offres uniques par run**
- **Filtre `fromage=3`** — limite aux offres postées dans les 3 derniers jours pour garantir la fraîcheur des résultats à chaque run
- **Cascade de sélecteurs CSS** — l'extracteur essaie 8 variantes de sélecteurs pour le titre, 4 pour l'entreprise, 3 pour le lieu : résistant aux changements réguliers du HTML d'Indeed
- **Scroll humain progressif** — défilement aléatoire par paliers entre les requêtes
- **Délais aléatoires** entre requêtes (4–7 secondes)
- **Retry automatique** en cas de timeout ou de Cloudflare non résolu (max 2 tentatives par requête)
- **Diagnostic intégré** — si une page renvoie des cards mais aucune extraction réussie, dump automatique du HTML de la première card dans la console pour identifier rapidement un éventuel changement de structure

## Roadmap

- [x] **Phase 1** — Scraper Indeed (Playwright) + pipeline + API + frontend
- [x] **Phase 2** — Intégration France Travail (OAuth2 + enrichissement ROME)
- [x] **Phase 3** — Intégration L'Étudiant.fr (API tRPC publique)
- [x] **Phase 4** — Intégration HelloWork (httpx + BeautifulSoup multi-catégories)
- [x] **Phase 5** — Enrichissement par tags techniques + dashboard analytique
- [x] **Phase 6** — Tests unitaires (pytest)
- [x] **Phase 7** — Optimisation Indeed multi-requêtes + extracteur résistant
- [ ] **Phase 8** — Scrapers APEC, LinkedIn, Welcome to the Jungle
- [ ] **Phase 9** — NLP : extraction d'entités structurées (niveau d'études, durée contrat, soft skills) via spaCy / BERT
- [ ] **Phase 10** — Recommandation personnalisée par profil utilisateur (matching par compétences)
- [ ] **Phase 11** — Production : PostgreSQL hébergé · Docker · déploiement VPS · domaine personnalisé

## Dépendances principales

```text
fastapi>=0.111           # Framework API REST asynchrone
uvicorn[standard]>=0.29  # Serveur ASGI
apscheduler>=3.10        # Scheduler cron intégré
playwright>=1.44.0       # Pilotage de Chromium (Indeed)
playwright-stealth>=2.0  # Masquage anti-détection
httpx>=0.27.0            # Client HTTP asynchrone (France Travail, L'Étudiant, HelloWork)
beautifulsoup4>=4.12.0   # Parsing HTML (HelloWork)
python-dotenv>=1.0.0     # Chargement des variables d'environnement
python-multipart>=0.0.9  # Formulaires FastAPI
psycopg2-binary>=2.9     # Driver PostgreSQL (production)
pytest>=8.0              # Tests unitaires (non inclus dans requirements.txt)
```

