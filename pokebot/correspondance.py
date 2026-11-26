"""Reconnaissance produit : une annonce correspond-elle exactement au produit de référence ?

Ordre de vérification :
1. EAN/GTIN ;
2. ASIN Amazon ou référence fabricant ;
3. nom exact (normalisé) ;
4. édition, langue, contenu, variante, état de carte, gradation.

Deux produits de la même extension ne sont jamais considérés comme identiques sans preuve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .models import Offre, Produit, TypeProduit, normaliser_langue
from .texte import normaliser_nom, normaliser_texte, similarite

SEUIL_NOM_PROCHE = 0.5


class Correspondance(str, Enum):
    EXACTE = "exacte"
    A_VERIFIER = "a_verifier"
    DIFFERENTE = "differente"


@dataclass(frozen=True)
class ResultatCorrespondance:
    statut: Correspondance
    raison: str


def gtin_valide(chiffres: str) -> bool:
    valeurs = [int(c) for c in chiffres]
    corps, controle = valeurs[:-1], valeurs[-1]
    total = sum(v * (3 if i % 2 == 0 else 1) for i, v in enumerate(reversed(corps)))
    return (10 - total % 10) % 10 == controle


def normaliser_gtin(valeur: str | None) -> str | None:
    """EAN-8/UPC-12/EAN-13/GTIN-14 → GTIN-14. Renvoie None si la clé de contrôle est fausse."""
    if not valeur:
        return None
    chiffres = re.sub(r"\D", "", str(valeur))
    if len(chiffres) not in (8, 12, 13, 14) or not gtin_valide(chiffres):
        return None
    return chiffres.zfill(14)


def normaliser_asin(valeur: str | None) -> str | None:
    if not valeur:
        return None
    v = str(valeur).strip().upper()
    return v if re.fullmatch(r"[A-Z0-9]{10}", v) else None


def normaliser_ref(valeur: str | None) -> str | None:
    if not valeur:
        return None
    v = re.sub(r"[\s\-_./]", "", str(valeur)).upper()
    return v or None


def _norm(valeur: object) -> str | None:
    if valeur is None:
        return None
    if isinstance(valeur, Enum):
        return str(valeur.value)
    texte = normaliser_texte(str(valeur))
    return texte or None


def _attributs(produit: Produit, offre: Offre) -> list[tuple[str, str | None, str | None, bool]]:
    """(libellé, valeur produit, valeur annonce, obligatoire pour conclure sans identifiant fort)."""
    attrs: list[tuple[str, str | None, str | None, bool]] = [
        ("type de produit", _norm(produit.type), _norm(offre.type), False),
        ("langue", normaliser_langue(produit.langue), normaliser_langue(offre.langue), produit.langue is not None),
    ]
    for libelle, champ in (("édition", "edition"), ("contenu", "contenu"), ("variante", "variante")):
        vp = getattr(produit, champ)
        attrs.append((libelle, _norm(vp), _norm(getattr(offre, champ)), vp is not None))
    if produit.type is TypeProduit.CARTE:
        attrs.append(("état de la carte", _norm(produit.etat_carte), _norm(offre.etat_carte), True))
    if produit.type is TypeProduit.CARTE_GRADEE:
        attrs.append(("société de gradation", _norm(produit.societe_gradation), _norm(offre.societe_gradation), True))
        attrs.append(("note de gradation", _norm(produit.note_gradation), _norm(offre.note_gradation), True))
    return attrs


def _conflits_et_inconnus(produit: Produit, offre: Offre) -> tuple[list[str], list[str]]:
    conflits, inconnus = [], []
    for libelle, vp, vo, obligatoire in _attributs(produit, offre):
        if vp is not None and vo is not None and vp != vo:
            conflits.append(libelle)
        elif obligatoire and vo is None:
            inconnus.append(libelle)
    return conflits, inconnus


def _apres_identifiant(nom_id: str, conflits: list[str], inconnus: list[str], identifie_tout: bool) -> ResultatCorrespondance:
    if conflits:
        return ResultatCorrespondance(
            Correspondance.A_VERIFIER, f"{nom_id} identique mais {', '.join(conflits)} différent(s) dans l'annonce"
        )
    if not identifie_tout and inconnus:
        return ResultatCorrespondance(
            Correspondance.A_VERIFIER, f"{nom_id} identique, mais {', '.join(inconnus)} non précisé(s)"
        )
    return ResultatCorrespondance(Correspondance.EXACTE, f"{nom_id} identique")


def comparer(produit: Produit, offre: Offre) -> ResultatCorrespondance:
    conflits, inconnus = _conflits_et_inconnus(produit, offre)
    est_carte = produit.type in (TypeProduit.CARTE, TypeProduit.CARTE_GRADEE)

    # 1. EAN / GTIN : identifie précisément une édition commerciale (langue et contenu compris).
    ean_p, ean_o = normaliser_gtin(produit.ean), normaliser_gtin(offre.ean)
    if ean_p and ean_o:
        if ean_p != ean_o:
            return ResultatCorrespondance(Correspondance.DIFFERENTE, "EAN différent")
        return _apres_identifiant("EAN", conflits, inconnus, identifie_tout=True)

    # 2a. ASIN Amazon.
    asin_p, asin_o = normaliser_asin(produit.asin), normaliser_asin(offre.asin)
    if asin_p and asin_o and asin_p == asin_o:
        return _apres_identifiant("ASIN", conflits, inconnus, identifie_tout=True)

    # 2b. Référence fabricant (pour une carte : numéro, qui n'identifie ni la langue, ni l'état, ni la note).
    ref_p, ref_o = normaliser_ref(produit.ref_fabricant), normaliser_ref(offre.ref_fabricant)
    if ref_p and ref_o:
        if ref_p != ref_o:
            return ResultatCorrespondance(Correspondance.DIFFERENTE, "référence fabricant différente")
        if est_carte and conflits:
            # Même numéro de carte, mais autre langue, état, gradation ou type : autre article.
            return ResultatCorrespondance(
                Correspondance.DIFFERENTE, f"même carte mais {', '.join(conflits)} différent(s)"
            )
        return _apres_identifiant("Référence", conflits, inconnus, identifie_tout=not est_carte)

    # 3. Nom exact, puis 4. attributs.
    if normaliser_nom(produit.nom) == normaliser_nom(offre.titre):
        if conflits:
            return ResultatCorrespondance(
                Correspondance.DIFFERENTE, f"même nom mais {', '.join(conflits)} différent(s)"
            )
        if inconnus:
            return ResultatCorrespondance(
                Correspondance.A_VERIFIER, f"nom identique, mais {', '.join(inconnus)} non précisé(s)"
            )
        return ResultatCorrespondance(Correspondance.EXACTE, "nom exact et attributs identiques")

    if conflits:
        return ResultatCorrespondance(Correspondance.DIFFERENTE, f"{', '.join(conflits)} différent(s)")
    if similarite(produit.nom, offre.titre) >= SEUIL_NOM_PROCHE:
        return ResultatCorrespondance(Correspondance.A_VERIFIER, "nom proche mais pas identique")
    return ResultatCorrespondance(Correspondance.DIFFERENTE, "autre produit")
