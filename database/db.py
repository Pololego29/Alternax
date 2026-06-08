"""
database/db.py
==============
Accès à la base de données.

Backends supportés (détecté automatiquement via DATABASE_URL) :
- SQLite    : local, aucune configuration requise
- PostgreSQL : production, nécessite DATABASE_URL dans l'environnement

En local : laisser DATABASE_URL vide → SQLite dans data/offers.db
En prod  : définir DATABASE_URL=postgresql://user:pass@host/db
"""

import json
import os
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from pipeline.enrichment import extract_tech_tags

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PATH      = Path(__file__).parent.parent / "data" / "offers.db"
_USE_PG      = bool(DATABASE_URL)


# =============================================================================
# SECTION 1 – CONNEXION (abstraction SQLite / PostgreSQL)
# =============================================================================

class _Conn:
    """
    Normalise sqlite3 et psycopg2 derrière une interface commune.
    Adapte les placeholders (? pour SQLite, %s pour PostgreSQL).
    """
    __slots__ = ("_raw", "_pg")

    def __init__(self, raw, use_pg: bool):
        self._raw = raw
        self._pg  = use_pg

    def execute(self, sql: str, params=None):
        if self._pg:
            sql = sql.replace("?", "%s")
        cur = self._raw.cursor()
        cur.execute(sql, params or [])
        return cur

    def commit(self):   self._raw.commit()
    def rollback(self): self._raw.rollback()
    def close(self):    self._raw.close()


@contextmanager
def get_conn():
    """Retourne une connexion normalisée vers SQLite ou PostgreSQL."""
    if _USE_PG:
        import psycopg2
        from psycopg2.extras import DictCursor
        raw = psycopg2.connect(DATABASE_URL)
        raw.cursor_factory = DictCursor
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(DB_PATH))
        raw.row_factory = sqlite3.Row

    conn = _Conn(raw, use_pg=_USE_PG)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =============================================================================
# SECTION 2 – INITIALISATION
# =============================================================================

_SCHEMA_PK = "SERIAL PRIMARY KEY"      if _USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
_SCHEMA_TS = "TIMESTAMP DEFAULT NOW()" if _USE_PG else "TEXT DEFAULT (datetime('now'))"


def init_db() -> None:
    """Crée la table offers et ses index si nécessaire."""
    with get_conn() as conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS offers (
                id            {_SCHEMA_PK},
                title         TEXT      NOT NULL,
                company       TEXT      DEFAULT '',
                location      TEXT      DEFAULT '',
                contract_type TEXT      DEFAULT 'Alternance',
                salary        TEXT      DEFAULT '',
                description   TEXT      DEFAULT '',
                url           TEXT      UNIQUE,
                source        TEXT      DEFAULT '',
                scraped_at    TEXT      DEFAULT '',
                tech_tags     TEXT      DEFAULT '[]',
                created_at    {_SCHEMA_TS}
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source   ON offers(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_location ON offers(location)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_created  ON offers(created_at)")

        # --- Comptes utilisateurs (connexion simple email + mot de passe) ---
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id            {_SCHEMA_PK},
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    {_SCHEMA_TS}
            )
        """)

        # --- Sessions (token opaque → utilisateur) ---
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at {_SCHEMA_TS}
            )
        """)

        # --- Favoris (une ligne par offre mise en favori par un utilisateur) ---
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS favorites (
                id         {_SCHEMA_PK},
                user_id    INTEGER NOT NULL,
                offer_id   INTEGER NOT NULL,
                created_at {_SCHEMA_TS},
                UNIQUE (user_id, offer_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fav_user ON favorites(user_id)")

    # Migration douce, dans sa PROPRE transaction : ajoute tech_tags aux tables
    # créées avant l'ajout de cette colonne. L'isolation est indispensable car
    # sur PostgreSQL une instruction en échec invalide toute la transaction —
    # si l'ALTER était dans le bloc ci-dessus, il annulerait la création de la
    # table sur une base neuve (la colonne existe déjà → ALTER échoue).
    try:
        with get_conn() as conn:
            conn.execute("ALTER TABLE offers ADD COLUMN tech_tags TEXT DEFAULT '[]'")
    except Exception:
        pass  # colonne déjà existante, on ignore


# =============================================================================
# SECTION 3 – ÉCRITURE
# =============================================================================

# INSERT OR IGNORE (SQLite) vs ON CONFLICT DO NOTHING (PostgreSQL)
_INSERT_SQL = (
    """INSERT INTO offers
           (title, company, location, contract_type, salary, description, url, source, scraped_at, tech_tags)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT (url) DO NOTHING"""
    if _USE_PG else
    """INSERT OR IGNORE INTO offers
           (title, company, location, contract_type, salary, description, url, source, scraped_at, tech_tags)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
)


def _params(offer: dict) -> list:
    """Convertit une offre dict en liste de paramètres SQL, avec extraction
    automatique des tags techniques si non fournis."""
    tags = offer.get("tech_tags")
    if tags is None or tags == []:
        tags = extract_tech_tags(
            offer.get("title", ""),
            offer.get("description", ""),
        )
    tags_json = json.dumps(tags) if isinstance(tags, list) else (tags or "[]")

    return [
        offer.get("title", ""),
        offer.get("company", ""),
        offer.get("location", ""),
        offer.get("contract_type", "Alternance"),
        offer.get("salary", ""),
        offer.get("description", ""),
        offer.get("url", ""),
        offer.get("source", ""),
        offer.get("scraped_at", ""),
        tags_json,
    ]


def insert_offers_bulk(offers: list[dict]) -> int:
    """Insère plusieurs offres en une transaction. Retourne le nombre inséré."""
    inserted = 0
    with get_conn() as conn:
        for offer in offers:
            cur = conn.execute(_INSERT_SQL, _params(offer))
            inserted += cur.rowcount
    return inserted


# =============================================================================
# SECTION 4 – LECTURE
# =============================================================================

_LIKE = "ILIKE" if _USE_PG else "LIKE"  # ILIKE = insensible à la casse en PostgreSQL


def _parse_tags(row_dict: dict) -> dict:
    """Désérialise tech_tags depuis JSON pour le frontend."""
    raw = row_dict.get("tech_tags") or "[]"
    try:
        row_dict["tech_tags"] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        row_dict["tech_tags"] = []
    return row_dict


def get_offers(
    search: str = "",
    location: str = "",
    source: str = "",
    tech: str = "",
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict], int]:
    """Récupère les offres avec filtres et pagination."""
    conditions: list[str] = []
    params:     list      = []

    if search:
        conditions.append(
            f"(title {_LIKE} ? OR company {_LIKE} ? OR description {_LIKE} ?)"
        )
        term = f"%{search}%"
        params.extend([term, term, term])

    if location:
        conditions.append(f"location {_LIKE} ?")
        params.append(f"%{location}%")

    if source:
        conditions.append("source = ?")
        params.append(source)

    if tech:
        # Recherche le tag dans le JSON sérialisé : ex. cherche "\"Python\""
        # entre guillemets pour éviter les sous-chaînes accidentelles.
        conditions.append(f"tech_tags {_LIKE} ?")
        params.append(f'%"{tech}"%')

    where  = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * per_page

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM offers {where}", params
        ).fetchone()["n"]

        rows = conn.execute(
            f"""
            SELECT id, title, company, location, contract_type,
                   salary, description, url, source, scraped_at,
                   tech_tags, created_at
            FROM offers {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ).fetchall()

    return [_parse_tags(dict(r)) for r in rows], total


def get_stats() -> dict:
    """Statistiques globales : total, par source, dernière collecte."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM offers"
        ).fetchone()["n"]

        by_source = conn.execute(
            "SELECT source, COUNT(*) AS count FROM offers GROUP BY source"
        ).fetchall()

        last_scrape = conn.execute(
            "SELECT MAX(scraped_at) AS last FROM offers"
        ).fetchone()["last"]

    return {
        "total": total,
        "by_source": {row["source"]: row["count"] for row in by_source},
        "last_scrape": last_scrape or "Jamais",
    }


def get_dashboard_stats(limit: int = 5) -> dict:
    """
    Stats pour le mini-dashboard frontend :
    - Top entreprises qui recrutent
    - Top localisations
    - Top technologies recherchées (extraite des tech_tags)
    - Répartition par source
    """
    with get_conn() as conn:
        # Top entreprises (on filtre les vides)
        top_companies = conn.execute(
            f"""
            SELECT company, COUNT(*) AS count
            FROM offers
            WHERE company != '' AND company IS NOT NULL
            GROUP BY company
            ORDER BY count DESC
            LIMIT ?
            """, [limit]
        ).fetchall()

        # Top localisations
        top_locations = conn.execute(
            f"""
            SELECT location, COUNT(*) AS count
            FROM offers
            WHERE location != '' AND location IS NOT NULL
            GROUP BY location
            ORDER BY count DESC
            LIMIT ?
            """, [limit]
        ).fetchall()

        # Répartition par source
        by_source = conn.execute(
            "SELECT source, COUNT(*) AS count FROM offers GROUP BY source ORDER BY count DESC"
        ).fetchall()

        # Top techs : on agrège les listes JSON côté Python (compatible SQLite + PG)
        all_tags = conn.execute(
            "SELECT tech_tags FROM offers WHERE tech_tags != '[]' AND tech_tags IS NOT NULL"
        ).fetchall()

    # Agrégation des tags
    tag_counter: Counter = Counter()
    for row in all_tags:
        try:
            tags = json.loads(row["tech_tags"])
            tag_counter.update(tags)
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        "top_companies": [{"name": r["company"],  "count": r["count"]} for r in top_companies],
        "top_locations": [{"name": r["location"], "count": r["count"]} for r in top_locations],
        "top_techs":     [{"name": name, "count": n} for name, n in tag_counter.most_common(limit)],
        "by_source":     [{"name": r["source"],   "count": r["count"]} for r in by_source],
    }


def url_exists(url: str) -> bool:
    """Vérifie si une URL est déjà en base."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM offers WHERE url = ?", [url]
        ).fetchone()
        return row is not None


def get_existing_urls() -> set[str]:
    """Retourne toutes les URLs déjà en base en UNE seule requête.

    Utilisé par la déduplication en lot. Évite d'ouvrir une connexion par
    offre (ce qui était catastrophiquement lent sur une base distante comme
    Neon : une connexion SSL par URL → des centaines de connexions par run).
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url FROM offers WHERE url IS NOT NULL AND url != ''"
        ).fetchall()
    return {r["url"] for r in rows}


# =============================================================================
# SECTION 5 – UTILISATEURS, SESSIONS & FAVORIS
# =============================================================================

def create_user(email: str, password_hash: str) -> dict:
    """Crée un utilisateur et retourne sa ligne (id, email)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            [email, password_hash],
        )
    return get_user_by_email(email)


def get_user_by_email(email: str) -> dict | None:
    """Récupère un utilisateur par email (ou None)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?", [email]
        ).fetchone()
    return dict(row) if row else None


def create_session(token: str, user_id: int) -> None:
    """Enregistre un token de session pour un utilisateur."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id) VALUES (?, ?)", [token, user_id]
        )


def get_user_by_token(token: str) -> dict | None:
    """Retrouve l'utilisateur associé à un token de session (ou None)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            [token],
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    """Supprime un token de session (déconnexion)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", [token])


# INSERT idempotent : ne fait rien si le favori existe déjà.
_FAV_INSERT_SQL = (
    "INSERT INTO favorites (user_id, offer_id) VALUES (?, ?) "
    "ON CONFLICT (user_id, offer_id) DO NOTHING"
    if _USE_PG else
    "INSERT OR IGNORE INTO favorites (user_id, offer_id) VALUES (?, ?)"
)


def add_favorite(user_id: int, offer_id: int) -> None:
    """Ajoute une offre aux favoris d'un utilisateur (sans doublon)."""
    with get_conn() as conn:
        conn.execute(_FAV_INSERT_SQL, [user_id, offer_id])


def remove_favorite(user_id: int, offer_id: int) -> None:
    """Retire une offre des favoris d'un utilisateur."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND offer_id = ?",
            [user_id, offer_id],
        )


def get_favorite_ids(user_id: int) -> list[int]:
    """Liste des ids d'offres mises en favori par l'utilisateur."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT offer_id FROM favorites WHERE user_id = ?", [user_id]
        ).fetchall()
    return [r["offer_id"] for r in rows]


def get_favorite_offers(user_id: int) -> list[dict]:
    """Offres complètes mises en favori, les plus récemment ajoutées d'abord."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT o.id, o.title, o.company, o.location, o.contract_type,
                   o.salary, o.description, o.url, o.source, o.scraped_at,
                   o.tech_tags, o.created_at
            FROM favorites f JOIN offers o ON o.id = f.offer_id
            WHERE f.user_id = ?
            ORDER BY f.created_at DESC
            """,
            [user_id],
        ).fetchall()
    return [_parse_tags(dict(r)) for r in rows]