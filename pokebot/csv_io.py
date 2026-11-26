"""Lecture des fichiers CSV : catalogue de produits et offres (démo ou saisies manuellement)."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .models import (
    Offre, Produit, StatutLivraison, TypeProduit, TypeVendeur, dispo_depuis, enum_depuis,
    etat_depuis, normaliser_langue, parser_decimal,
)
from .temps import depuis_texte

log = logging.getLogger(__name__)

COLONNES_CATALOGUE = [
    "id", "nom", "categorie", "type", "langue", "gamme", "ean", "asin", "ref_fabricant", "edition",
    "contenu", "variante", "etat_carte", "societe_gradation", "note_gradation", "lien_officiel",
    "prix_conseille", "source_prix_conseille", "mots_cles",
]

COLONNES_OFFRES = [
    "source", "site", "titre", "url", "prix", "livraison", "statut_livraison", "frais_obligatoires",
    "vendeur", "type_vendeur", "note_vendeur", "nb_avis_vendeur", "etat", "langue", "disponibilite",
    "type", "ean", "asin", "ref_fabricant", "edition", "contenu", "variante", "etat_carte",
    "societe_gradation", "note_gradation", "vente_reelle", "verifie_le", "description",
]


def _v(ligne: dict, cle: str) -> str | None:
    valeur = (ligne.get(cle) or "").strip()
    return valeur or None


def _lire(chemin: Path) -> list[dict]:
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        return [l for l in csv.DictReader(f) if any((v or "").strip() for v in l.values() if isinstance(v, str))]


def lire_catalogue(chemin: Path, demo: bool = False) -> list[Produit]:
    produits: dict[str, Produit] = {}
    for n, ligne in enumerate(_lire(chemin), start=2):
        try:
            ident = _v(ligne, "id")
            if not ident or not _v(ligne, "nom"):
                raise ValueError("colonnes id et nom obligatoires")
            if ident in produits:
                raise ValueError(f"identifiant en double : {ident}")
            prix_conseille = parser_decimal(_v(ligne, "prix_conseille"))
            source_prix = _v(ligne, "source_prix_conseille")
            if prix_conseille is not None and not source_prix:
                raise ValueError("prix_conseille renseigné sans source_prix_conseille officielle")
            produits[ident] = Produit(
                id=ident,
                nom=_v(ligne, "nom"),  # type: ignore[arg-type]
                categorie=_v(ligne, "categorie") or "non classé",
                type=enum_depuis(TypeProduit, _v(ligne, "type"), defaut=TypeProduit.SCELLE),  # type: ignore[arg-type]
                langue=normaliser_langue(_v(ligne, "langue")),
                gamme=_v(ligne, "gamme") or "",
                ean=_v(ligne, "ean"),
                asin=_v(ligne, "asin"),
                ref_fabricant=_v(ligne, "ref_fabricant"),
                edition=_v(ligne, "edition"),
                contenu=_v(ligne, "contenu"),
                variante=_v(ligne, "variante"),
                etat_carte=_v(ligne, "etat_carte"),
                societe_gradation=_v(ligne, "societe_gradation"),
                note_gradation=_v(ligne, "note_gradation"),
                lien_officiel=_v(ligne, "lien_officiel"),
                prix_conseille=prix_conseille,
                source_prix_conseille=source_prix,
                mots_cles=_v(ligne, "mots_cles") or "",
                demo=demo,
            )
        except ValueError as exc:
            log.warning("%s, ligne %d ignorée : %s", chemin.name, n, exc)
    return list(produits.values())


def lire_offres(chemin: Path, demo: bool = False) -> list[Offre]:
    offres: list[Offre] = []
    for n, ligne in enumerate(_lire(chemin), start=2):
        try:
            for obligatoire in ("source", "site", "titre", "url", "verifie_le"):
                if not _v(ligne, obligatoire):
                    raise ValueError(f"colonne « {obligatoire} » vide")
            livraison = parser_decimal(_v(ligne, "livraison"))
            statut = enum_depuis(StatutLivraison, _v(ligne, "statut_livraison"))
            if statut is None:
                statut = StatutLivraison.CONNUE if livraison is not None else StatutLivraison.INCONNUE
            if statut is not StatutLivraison.INCONNUE and livraison is None:
                raise ValueError("statut_livraison renseigné sans montant de livraison")
            nb_avis = _v(ligne, "nb_avis_vendeur")
            offres.append(Offre(
                source=_v(ligne, "source"),  # type: ignore[arg-type]
                site=_v(ligne, "site").lower(),  # type: ignore[union-attr]
                titre=_v(ligne, "titre"),  # type: ignore[arg-type]
                url=_v(ligne, "url"),  # type: ignore[arg-type]
                prix=parser_decimal(_v(ligne, "prix")),
                livraison=livraison,
                statut_livraison=statut,
                frais_obligatoires=parser_decimal(_v(ligne, "frais_obligatoires")) or parser_decimal("0"),  # type: ignore[arg-type]
                vendeur=_v(ligne, "vendeur"),
                type_vendeur=enum_depuis(TypeVendeur, _v(ligne, "type_vendeur"), defaut=TypeVendeur.INCONNU),  # type: ignore[arg-type]
                note_vendeur=parser_decimal(_v(ligne, "note_vendeur")),
                nb_avis_vendeur=int(nb_avis) if nb_avis else None,
                etat=etat_depuis(_v(ligne, "etat")),
                langue=normaliser_langue(_v(ligne, "langue")),
                disponibilite=dispo_depuis(_v(ligne, "disponibilite")),
                type=enum_depuis(TypeProduit, _v(ligne, "type")),
                ean=_v(ligne, "ean"),
                asin=_v(ligne, "asin"),
                ref_fabricant=_v(ligne, "ref_fabricant"),
                edition=_v(ligne, "edition"),
                contenu=_v(ligne, "contenu"),
                variante=_v(ligne, "variante"),
                etat_carte=_v(ligne, "etat_carte"),
                societe_gradation=_v(ligne, "societe_gradation"),
                note_gradation=_v(ligne, "note_gradation"),
                vente_reelle=(_v(ligne, "vente_reelle") or "").lower() in ("1", "oui", "true", "vrai"),
                verifie_le=depuis_texte(_v(ligne, "verifie_le")),
                description=_v(ligne, "description") or "",
                demo=demo,
            ))
        except ValueError as exc:
            log.warning("%s, ligne %d ignorée : %s", chemin.name, n, exc)
    return offres
