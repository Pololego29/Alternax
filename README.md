# Alternax — Agrégateur d'offres d'alternance

Alternax est un projet étudiant qui a pour but de centraliser des offres d'alternance sur une seule plateforme.

L'idée est simple : récupérer automatiquement des offres depuis Indeed, les stocker dans une base de données, puis les afficher sur un petit site web avec une recherche, des filtres et une pagination.

## Objectif du projet

Aujourd'hui, les offres d'alternance sont dispersées sur plusieurs sites.  
Notre objectif est donc de créer un outil qui permet de gagner du temps dans la recherche d'alternance.

Pour cette première version, nous nous concentrons sur :

- la récupération automatique d'offres depuis Indeed ;
- le stockage des offres dans une base locale ;
- l'affichage des offres sur une interface web simple ;
- la mise en place d'une API pour faire le lien entre la base et le site.

## Fonctionnement général

Le projet fonctionne en plusieurs étapes :

1. Un scraper visite Indeed et récupère des offres d'alternance.
2. Les offres sont nettoyées et dédupliquées pour éviter les doublons.
3. Les offres sont stockées dans une base de données SQLite.
4. Une API FastAPI permet de récupérer les offres.
5. Le site web affiche les offres avec des filtres et une pagination.

Schéma simplifié :

```text
Indeed
  ↓
Scraper Python
  ↓
Base de données SQLite
  ↓
API FastAPI
  ↓
Site web HTML/CSS/JS
```

## Lancer le projet en local

```bash
# Installer les dépendances
pip install -r requirements-scraper.txt
playwright install chromium

# Lancer l'API et le site
python run.py

# Dans un second terminal, lancer le scraper
python -m scrapers.run_scraper
```

Site → [http://localhost:8000](http://localhost:8000)

<!--
## VERSION COMPLÈTE (soutenance)

### Équipe

| Membre | Rôle |
|---|---|
| **Paul** | Lead technique — architecture, API FastAPI, déploiement, intégration |
| **Ikram** | Scraper Indeed (Playwright, anti-détection, pipeline de données) |
| **Hakob** | Contribution frontend et tests |
| **Ruben** | Tâches déléguées (tests, revue de code) |
| **Paul 2** | Tâches déléguées (documentation, tests) |
| **Yassine** | Tâches déléguées (tests, revue de code) |

Tous les membres ont participé activement au projet. La répartition des commits Git ne reflète pas l'ensemble des contributions — certains membres ont travaillé en pair programming, revue de code ou sur des branches séparées.

---

### Comment ça marche

```
┌─────────────────────────────────────────────────────┐
│  Scraper (Playwright + Chromium)                    │
│  └── Visite Indeed, extrait les offres page par page│
└─────────────────────┬───────────────────────────────┘
                      │ Liste de JobOffer
                      ▼
┌─────────────────────────────────────────────────────┐
│  Pipeline de déduplication                          │
│  └── Filtre par URL (exact) + empreinte MD5         │
│      (titre + entreprise + lieu)                    │
└─────────────────────┬───────────────────────────────┘
                      │ Offres uniques
                      ▼
┌─────────────────────────────────────────────────────┐
│  Base de données (SQLite en local)                  │
│  └── Table offers, index sur source/location/date   │
└─────────────────────┬───────────────────────────────┘
                      │ Requêtes SQL
                      ▼
┌─────────────────────────────────────────────────────┐
│  API REST (FastAPI)                                 │
│  └── GET /api/offres  — liste paginée avec filtres  │
│  └── GET /api/stats   — statistiques globales       │
│  └── GET /api/sources — sources disponibles         │
└─────────────────────┬───────────────────────────────┘
                      │ JSON via HTTP
                      ▼
┌─────────────────────────────────────────────────────┐
│  Site vitrine (HTML / CSS / JS vanilla)             │
│  └── Recherche, filtres, pagination                 │
└─────────────────────────────────────────────────────┘
```

---

### Structure du projet

```
Alternax/
├── run.py                      # Point d'entrée local (fix Windows ProactorEventLoop)
├── requirements.txt            # Dépendances API
├── requirements-scraper.txt    # Dépendances scraper (+ playwright)
├── Procfile                    # Déploiement Railway
├── vercel.json                 # Déploiement Vercel (frontend)
│
├── scrapers/
│   ├── indeed.py               # Scraper Indeed France (Playwright)
│   └── run_scraper.py          # Point d'entrée standalone (GitHub Actions)
│
├── pipeline/
│   └── deduplicator.py         # Déduplication avant insertion BDD
│
├── database/
│   └── db.py                   # SQLite (local) / PostgreSQL (prod) — auto-détecté
│
├── api/
│   └── main.py                 # API FastAPI
│
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   ├── config.js               # URL de l'API (généré au build Vercel)
│   └── scripts/
│       └── build.js            # Script de build Vercel
│
├── .github/
│   └── workflows/
│       └── scrape.yml          # Scraping automatique toutes les 6h (GitHub Actions)
│
└── data/                       # Données locales (ignorées par git)
    └── offers.db
```

---

### Stack technique

| Couche | Technologie |
|---|---|
| Scraping | Python · Playwright (Chromium) |
| Anti-détection | headless=False en local, rotation User-Agents, scroll humain, warm-up |
| Pipeline | Python · hashlib MD5 |
| Base de données | SQLite (local) · PostgreSQL/Supabase (production) |
| API | FastAPI · Uvicorn |
| Automatisation | GitHub Actions (cron toutes les 6h) |
| Frontend | HTML · CSS · JavaScript vanilla · Tailwind CDN |
| Déploiement | Vercel (frontend) · Railway (API) |

---

### Endpoints API

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/api/offres` | Liste paginée avec filtres |
| `GET` | `/api/stats` | Total, par source, dernière collecte |
| `GET` | `/api/sources` | Sources disponibles |

**Paramètres de `/api/offres` :**

| Paramètre | Description |
|---|---|
| `search` | Recherche dans titre, entreprise, description |
| `location` | Filtre ville/région |
| `source` | Filtre par source (`indeed`, …) |
| `page` | Numéro de page (défaut : 1) |
| `per_page` | Résultats par page (défaut : 20, max : 100) |

---

### Déploiement (production)

```
GitHub Actions (cron 6h)
    └── Scraper → écrit dans Supabase (PostgreSQL)

Railway
    └── API FastAPI → lit Supabase → sert le JSON

Vercel
    └── Frontend statique → appelle l'API Railway
```

#### Variables d'environnement requises

| Variable | Où | Valeur |
|---|---|---|
| `DATABASE_URL` | Railway + GitHub Actions Secrets | `postgresql://...` (Supabase) |
| `API_URL` | Vercel | `https://votre-api.up.railway.app/api` |
| `FRONTEND_URL` | Railway | `https://votre-app.vercel.app` |

#### Étapes

1. Créer une base PostgreSQL sur [Supabase](https://supabase.com) (gratuit)
2. Déployer l'API sur [Railway](https://railway.app) — connecter le repo GitHub, ajouter `DATABASE_URL`
3. Déployer le frontend sur [Vercel](https://vercel.com) — connecter le repo GitHub, ajouter `API_URL`
4. Ajouter `DATABASE_URL` dans les Secrets du repo GitHub (Settings → Secrets → Actions)
5. Lancer le premier scraping manuellement : onglet Actions → "Scraping Indeed" → "Run workflow"

---

### Améliorations futures

- **Sources supplémentaires** — HelloWork, APEC, France Travail (API officielle gratuite)
- **Recherche avancée** — filtres par secteur, niveau d'études, durée de contrat
- **NLP** — extraction automatique de compétences requises (spaCy)
- **Alertes** — notification par email ou webhook quand une nouvelle offre correspond à un profil
- **Authentification** — sauvegarde de recherches et favoris par utilisateur

---

### Stratégie anti-détection Indeed

Indeed détecte les bots et bloque les requêtes automatisées. Techniques mises en place :

- Navigateur visible (`headless=False`) en local — moins détectable qu'un headless
- Masquage de `navigator.webdriver` via script injecté
- Rotation de 4 User-Agents Chrome/Firefox réalistes
- Warm-up : visite de la page d'accueil avant la recherche
- Navigation via le bouton "Suivant" (clics réels, pas d'URLs directes)
- Scroll progressif simulant un comportement humain
- Délais aléatoires entre les pages (5–9 secondes)
- Retry automatique en cas de timeout (2 tentatives)
-->
