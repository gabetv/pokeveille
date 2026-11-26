"""Outils de normalisation de texte (accents, casse, ponctuation)."""

from __future__ import annotations

import re
import unicodedata

# Mots qui n'aident pas à distinguer deux produits.
MOTS_VIDES = {
    "pokemon", "jcc", "tcg", "jeu", "de", "cartes", "carte", "a", "collectionner",
    "le", "la", "les", "l", "d", "du", "des", "et", "en", "un", "une", "the",
}


def sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normaliser_texte(texte: str | None) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces."""
    if not texte:
        return ""
    t = sans_accents(texte).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def jetons(texte: str | None) -> list[str]:
    return [m for m in normaliser_texte(texte).split() if m not in MOTS_VIDES]


def normaliser_nom(texte: str | None) -> str:
    return " ".join(jetons(texte))


def similarite(a: str | None, b: str | None) -> float:
    """Indice de Jaccard sur les mots significatifs (0 à 1)."""
    ja, jb = set(jetons(a)), set(jetons(b))
    union = ja | jb
    return len(ja & jb) / len(union) if union else 0.0
