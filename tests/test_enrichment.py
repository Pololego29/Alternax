"""
Tests unitaires pour pipeline/enrichment.py
============================================
Vérifie que l'extraction de tags techniques détecte correctement les
technologies dans le titre + description d'une offre, et que les
faux positifs classiques (mot dans un autre mot) sont évités.

Lancement :
    python -m pytest tests/ -v
"""

from pipeline.enrichment import extract_tech_tags, TECH_KEYWORDS


# ============================================================================
# 1. Détection basique
# ============================================================================

def test_extract_simple_python():
    """Un mot-clé simple dans le titre est détecté."""
    tags = extract_tech_tags("Développeur Python H/F", "")
    assert "Python" in tags


def test_extract_multiple_keywords():
    """Plusieurs technologies sont détectées dans une même offre."""
    tags = extract_tech_tags(
        "Data Scientist",
        "Vous maîtrisez Python, SQL et Pandas. Connaissance de Docker appréciée."
    )
    assert "Python" in tags
    assert "SQL" in tags
    assert "Pandas" in tags
    assert "Docker" in tags
    assert "Data Science" in tags


def test_no_tech_keywords_returns_empty():
    """Une offre sans technologie retourne une liste vide."""
    tags = extract_tech_tags(
        "Alternance Marketing Digital",
        "Vous êtes passionné par la communication et les réseaux sociaux."
    )
    assert tags == []


# ============================================================================
# 2. Case-insensitive et variantes
# ============================================================================

def test_case_insensitive():
    """La détection ne dépend pas de la casse."""
    tags_lower = extract_tech_tags("développeur python", "stack django")
    tags_upper = extract_tech_tags("DÉVELOPPEUR PYTHON", "STACK DJANGO")
    tags_mixed = extract_tech_tags("Développeur Python", "Stack Django")

    assert tags_lower == tags_upper == tags_mixed
    assert "Python" in tags_lower
    assert "Django" in tags_lower


def test_variants_resolve_to_same_tag():
    """Les variantes orthographiques tombent sur le même tag normalisé."""
    tags_dotted = extract_tech_tags("Dev Vue.js", "")
    tags_concat = extract_tech_tags("Dev Vuejs", "")

    # Les deux écritures doivent produire le même tag normalisé "Vue"
    assert "Vue" in tags_dotted
    assert "Vue" in tags_concat


def test_variants_node():
    """Idem pour node.js / nodejs."""
    assert "Node.js" in extract_tech_tags("Dev node.js", "")
    assert "Node.js" in extract_tech_tags("Dev nodejs", "")


# ============================================================================
# 3. Word boundary — pas de faux positifs
# ============================================================================

def test_java_does_not_match_javascript():
    """Le mot-clé Java ne doit PAS matcher dans le mot JavaScript."""
    tags = extract_tech_tags("Développeur JavaScript", "Framework moderne")
    assert "JavaScript" in tags
    assert "Java" not in tags  # word boundary doit empêcher ce match


def test_python_does_not_match_in_another_word():
    """Python ne doit pas matcher si entouré d'autres caractères."""
    # Cas piège : "pythonista" ne contient pas vraiment Python comme tech
    # Notre implémentation utilise \b donc "pythonista" ne devrait pas matcher
    tags = extract_tech_tags("Pythonista enthousiaste", "")
    # \b autour de python : "pythonista" → \b devant python mais pas après
    # → ne matche pas, donc Python absent
    assert "Python" not in tags


# ============================================================================
# 4. Comportement de la sortie
# ============================================================================

def test_result_is_sorted_alphabetically():
    """Les tags retournés sont triés alphabétiquement (déterminisme)."""
    tags = extract_tech_tags(
        "Full-stack Developer",
        "React, Python, Docker, AWS"
    )
    assert tags == sorted(tags)


def test_no_duplicates_in_result():
    """Si une techno apparaît plusieurs fois, elle n'est listée qu'une fois."""
    tags = extract_tech_tags(
        "Python Python Python",
        "Beaucoup de Python et encore du Python"
    )
    assert tags.count("Python") == 1


def test_handles_empty_input():
    """Entrée vide ne plante pas, retourne liste vide."""
    assert extract_tech_tags("", "") == []
    assert extract_tech_tags("", None) == []  # type: ignore
    assert extract_tech_tags(None, None) == []  # type: ignore


def test_handles_only_title():
    """La description est optionnelle."""
    tags = extract_tech_tags("Développeur Python")
    assert "Python" in tags


# ============================================================================
# 5. Détection française
# ============================================================================

def test_french_keywords_detected():
    """Les mots-clés français pour IA et ML sont détectés."""
    tags = extract_tech_tags(
        "Ingénieur en intelligence artificielle",
        "Apprentissage automatique et traitement du langage"
    )
    assert "Intelligence Artificielle" in tags
    assert "Machine Learning" in tags
    assert "NLP" in tags


# ============================================================================
# 6. Configuration du dictionnaire
# ============================================================================

def test_keywords_dict_has_no_duplicates():
    """Le dictionnaire de tags n'a pas de clé en double."""
    keys = list(TECH_KEYWORDS.keys())
    assert len(keys) == len(set(keys))


def test_keywords_dict_size():
    """On a bien environ 45 keywords pour couvrir le spectre."""
    assert len(TECH_KEYWORDS) >= 40
    assert len(TECH_KEYWORDS) <= 60
