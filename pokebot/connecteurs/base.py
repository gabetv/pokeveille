"""Interface commune des connecteurs de prix. Un connecteur = une source de données."""

from __future__ import annotations

import copy
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import ConfigSource
from ..models import Offre


class ErreurSource(Exception):
    """Erreur lisible par l'utilisateur (quota dépassé, accès refusé…)."""


@dataclass(frozen=True)
class Requete:
    mots_cles: str
    ean: str | None = None
    asin: str | None = None
    ref_fabricant: str | None = None
    code_postal: str | None = None

    def cle(self) -> tuple:
        return (self.mots_cles.lower().strip(), self.ean, self.asin, self.ref_fabricant)


class Connecteur(ABC):
    id: str = ""
    site: str = ""  # domaine, ou "*" pour une source qui couvre plusieurs sites (démo, CSV)
    libelle: str = ""
    nature: str = "prix"  # "prix", "marche_secondaire" ou "officiel"

    def __init__(self, config: ConfigSource | None = None):
        self.config = config or ConfigSource()
        self._cache: dict[tuple, tuple[float, list[Offre]]] = {}
        self._dernier_appel = 0.0
        self._verrou = threading.Lock()

    def disponibilite(self) -> tuple[bool, str]:
        """(utilisable, explication). Surcharger pour signaler un accès manquant."""
        return True, "actif"

    @property
    def actif(self) -> bool:
        return self.config.actif and self.disponibilite()[0]

    def statut(self) -> str:
        disponible, explication = self.disponibilite()
        if not disponible:
            return explication
        if not self.config.actif:
            return "désactivé dans config/parametres.toml"
        return explication

    def rechercher(self, requete: Requete) -> list[Offre]:
        """Recherche avec cache et délai minimal entre deux requêtes (respect des quotas)."""
        if not self.actif:
            return []
        with self._verrou:
            cle = requete.cle()
            en_cache = self._cache.get(cle)
            if en_cache and time.monotonic() - en_cache[0] < self.config.cache_secondes:
                return [copy.copy(o) for o in en_cache[1]]
            attente = self.config.delai_entre_requetes_secondes - (time.monotonic() - self._dernier_appel)
            if attente > 0:
                time.sleep(attente)
            try:
                offres = self._rechercher(requete)
            finally:
                self._dernier_appel = time.monotonic()
            self._cache[cle] = (time.monotonic(), offres)
            return [copy.copy(o) for o in offres]

    @abstractmethod
    def _rechercher(self, requete: Requete) -> list[Offre]:
        ...


class ConnecteurNonIntegre(Connecteur):
    """Source volontairement désactivée : aucune méthode de récupération automatique autorisée connue."""

    raison: str = ""

    def disponibilite(self) -> tuple[bool, str]:
        return False, self.raison

    def _rechercher(self, requete: Requete) -> list[Offre]:  # pragma: no cover - jamais appelé
        return []
