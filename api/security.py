"""
api/security.py
===============
Utilitaires de sécurité pour la connexion utilisateur.

- Hachage des mots de passe via PBKDF2-HMAC-SHA256 (bibliothèque standard,
  aucune dépendance à installer).
- Génération de tokens de session opaques et aléatoires.

Format de hachage stocké en base :
    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
"""

import hashlib
import hmac
import secrets

_ALGO       = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Hache un mot de passe avec un sel aléatoire. Retourne une chaîne stockable."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Vérifie un mot de passe contre la valeur hachée stockée (comparaison constante)."""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def generate_token() -> str:
    """Génère un token de session opaque (URL-safe, ~43 caractères)."""
    return secrets.token_urlsafe(32)
