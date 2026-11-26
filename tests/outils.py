"""Fabriques de données pour les tests (valeurs fictives)."""

from __future__ import annotations

from decimal import Decimal

from pokebot.models import (
    Disponibilite, Etat, Offre, Produit, StatutLivraison, TypeProduit, TypeVendeur,
)

EAN_ETB = "2000000000015"
EAN_AUTRE = "2000000000022"


def D(x: str) -> Decimal:
    return Decimal(x)


def produit_etb(**kw) -> Produit:
    base = dict(
        id="etb", nom="Coffret Dresseur d'élite Test", categorie="coffret dresseur d'élite",
        type=TypeProduit.SCELLE, langue="fr", gamme="30e anniversaire", ean=EAN_ETB, asin="B0TEST0001",
    )
    base.update(kw)
    return Produit(**base)


def offre(**kw) -> Offre:
    base = dict(
        source="test", site="fnac.com", titre="Coffret Dresseur d'élite Test", url="https://exemple.invalid/o",
        prix=D("50.00"), livraison=D("0"), statut_livraison=StatutLivraison.CONNUE,
        vendeur="Enseigne", type_vendeur=TypeVendeur.ENSEIGNE, etat=Etat.NEUF, langue="fr",
        disponibilite=Disponibilite.EN_STOCK, ean=EAN_ETB,
    )
    base.update(kw)
    return Offre(**base)


def offre_amazon(prix: str, **kw) -> Offre:
    kw.setdefault("vendeur", "Amazon")
    kw.setdefault("type_vendeur", TypeVendeur.AMAZON)
    return offre(source="amazon_fr", site="amazon.fr", prix=D(prix), asin="B0TEST0001", **kw)
