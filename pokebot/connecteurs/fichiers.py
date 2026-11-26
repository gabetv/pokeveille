"""Connecteurs basés sur des fichiers CSV : démonstration (fictif) et saisie manuelle."""

from __future__ import annotations

from pathlib import Path

from ..config import ConfigSource
from ..correspondance import normaliser_asin, normaliser_gtin, normaliser_ref
from ..csv_io import lire_offres
from ..models import Offre
from ..texte import similarite
from .base import Connecteur, Requete

SEUIL_PERTINENCE = 0.3


def _pertinente(offre: Offre, requete: Requete) -> bool:
    if requete.ean and normaliser_gtin(offre.ean) and normaliser_gtin(offre.ean) == normaliser_gtin(requete.ean):
        return True
    if requete.asin and normaliser_asin(offre.asin) and normaliser_asin(offre.asin) == normaliser_asin(requete.asin):
        return True
    if requete.ref_fabricant and normaliser_ref(offre.ref_fabricant) == normaliser_ref(requete.ref_fabricant):
        return True
    return similarite(requete.mots_cles, offre.titre) >= SEUIL_PERTINENCE


class ConnecteurFichier(Connecteur):
    site = "*"
    demo = False

    def __init__(self, chemin: Path, config: ConfigSource | None = None):
        super().__init__(config or ConfigSource(delai_entre_requetes_secondes=0, cache_secondes=0))
        self.chemin = chemin

    def _rechercher(self, requete: Requete) -> list[Offre]:
        return [o for o in lire_offres(self.chemin, demo=self.demo) if _pertinente(o, requete)]


class ConnecteurDemo(ConnecteurFichier):
    id = "demo"
    libelle = "Données de démonstration (FICTIVES)"
    demo = True

    def disponibilite(self) -> tuple[bool, str]:
        if not self.chemin.exists():
            return False, f"fichier de démonstration introuvable : {self.chemin}"
        return True, "actif — toutes les offres sont fictives"


class ConnecteurCsvManuel(ConnecteurFichier):
    id = "csv_manuel"
    libelle = "Offres saisies manuellement (CSV)"

    def disponibilite(self) -> tuple[bool, str]:
        if not self.chemin.exists():
            return False, f"aucun fichier {self.chemin.name} (facultatif)"
        n = len(lire_offres(self.chemin))
        if n == 0:
            return False, f"{self.chemin.name} ne contient aucune offre"
        return True, f"actif — {n} offre(s) saisie(s) à la main, à revérifier régulièrement"
