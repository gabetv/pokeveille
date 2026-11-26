"""Registre des connecteurs. Ajouter une source = ajouter une classe et l'enregistrer ici."""

from __future__ import annotations

from ..config import Parametres
from .amazon import ConnecteurAmazon
from .base import Connecteur, ErreurSource, Requete
from .fichiers import ConnecteurCsvManuel, ConnecteurDemo
from .lecrocodeal import ConnecteurCrocoDeal
from .non_integres import (
    ConnecteurCardmarket, ConnecteurCultura, ConnecteurFnac, ConnecteurJoueClub, ConnecteurKingJouet,
    ConnecteurPokemonOfficiel,
)

__all__ = ["Connecteur", "ErreurSource", "Requete", "construire_connecteurs"]


def construire_connecteurs(p: Parametres) -> list[Connecteur]:
    non_integres: list[Connecteur] = [
        cls(p.source(cls.id)) for cls in (
            ConnecteurPokemonOfficiel, ConnecteurFnac, ConnecteurCultura, ConnecteurJoueClub,
            ConnecteurKingJouet, ConnecteurCardmarket,
        )
    ]
    if p.demo:
        # En mode démo, seule la source fictive est interrogée.
        return [ConnecteurDemo(p.chemin_offres_demo)] + non_integres
    return [
        ConnecteurAmazon(p, p.source("amazon_fr")),
        ConnecteurCsvManuel(p.chemin_offres_manuelles, p.source("csv_manuel")),
        ConnecteurCrocoDeal(p.sources.get("lecrocodeal")),
    ] + non_integres
