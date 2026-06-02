"""
pipeline/enrichment.py
======================
Enrichissement des offres avec extraction de tags techniques.

Scanne le titre et la description d'une offre pour détecter les technologies
mentionnées (langages, frameworks, bases de données, cloud, data, etc.) et
retourne une liste normalisée de tags. La détection est case-insensitive
avec word boundary pour éviter les faux positifs (ex: "java" ne matche pas
"javascript").

Utilisé automatiquement par database/db.py au moment de l'insertion.
"""

import re

# =============================================================================
# Dictionnaire des mots-clés techniques détectés
# =============================================================================
# Format : { "Tag normalisé" : [variantes à chercher dans le texte] }

TECH_KEYWORDS: dict[str, list[str]] = {
    # Langages de programmation
    "Python":                   ["python"],
    "JavaScript":               ["javascript"],
    "TypeScript":               ["typescript"],
    "Java":                     ["java"],
    "PHP":                      ["php"],
    "SQL":                      ["sql"],

    # Frameworks Frontend
    "React":                    ["react", "reactjs"],
    "Vue":                      ["vue.js", "vuejs"],
    "Angular":                  ["angular"],

    # Frameworks Backend
    "Node.js":                  ["node.js", "nodejs"],
    "Django":                   ["django"],
    "FastAPI":                  ["fastapi"],
    "Symfony":                  ["symfony"],
    "Spring":                   ["spring boot"],

    # Bases de données
    "PostgreSQL":               ["postgresql", "postgres"],
    "MongoDB":                  ["mongodb"],
    "MySQL":                    ["mysql"],

    # Cloud / DevOps
    "AWS":                      ["aws"],
    "Azure":                    ["azure"],
    "GCP":                      ["gcp", "google cloud"],
    "Docker":                   ["docker"],
    "Kubernetes":               ["kubernetes", "k8s"],
    "Linux":                    ["linux"],
    "DevOps":                   ["devops"],
    "CI/CD":                    ["ci/cd", "ci-cd"],

    # Data / IA
    "Data Science":             ["data scientist", "data science"],
    "Data Analyst":             ["data analyst", "data analyste"],
    "Data Engineer":            ["data engineer", "data engineering"],
    "Machine Learning":         ["machine learning", "apprentissage automatique"],
    "Deep Learning":            ["deep learning"],
    "Intelligence Artificielle": ["intelligence artificielle"],
    "NLP":                      ["nlp", "traitement du langage"],
    "Power BI":                 ["power bi", "powerbi"],
    "Pandas":                   ["pandas"],
    "TensorFlow":               ["tensorflow"],
    "PyTorch":                  ["pytorch"],

    # Méthodologies & Outils
    "Agile":                    ["agile"],
    "Scrum":                    ["scrum"],
    "GitHub":                   ["github"],
    "GitLab":                   ["gitlab"],

    # Cybersécurité
    "Cybersécurité":            ["cybersécurité", "cybersecurity", "cyber security"],
}


def extract_tech_tags(title: str, description: str = "") -> list[str]:
    """
    Extrait les tags techniques d'une offre en scannant titre + description.

    Retourne une liste triée de tags normalisés, sans doublons.
    Si aucun tag n'est détecté, retourne une liste vide.

    Examples
    --------
    >>> extract_tech_tags("Développeur Python H/F", "Stack: Django, PostgreSQL")
    ['Django', 'PostgreSQL', 'Python']

    >>> extract_tech_tags("Data Engineer", "Big Data avec Spark et AWS")
    ['AWS', 'Data Engineer']
    """
    # Espaces de marge pour aider les word boundaries en début/fin
    text = f" {title or ''} {description or ''} ".lower()
    found: set[str] = set()

    for tag, variants in TECH_KEYWORDS.items():
        for variant in variants:
            # \b = word boundary : "java" ne matche pas "javascript"
            pattern = r"\b" + re.escape(variant.lower()) + r"\b"
            if re.search(pattern, text):
                found.add(tag)
                break  # une seule variante suffit par tag

    return sorted(found)


if __name__ == "__main__":
    # Petit test rapide
    samples = [
        ("Développeur Python H/F", "Vous maîtrisez Django, PostgreSQL et Docker."),
        ("Data Scientist", "Machine Learning, Python, NumPy, Pandas, scikit-learn."),
        ("Alternance Marketing", "Pas de tech ici, juste du marketing digital."),
        ("Full-Stack JavaScript", "React + Node.js + MongoDB."),
    ]
    for title, desc in samples:
        tags = extract_tech_tags(title, desc)
        print(f"{title:<35} → {tags}")