"""Service de veille des sorties et des drops (indépendant de Discord, donc testable).

- actualiser() : lit le calendrier Poképédia et les flux d'annonces, enregistre les nouveautés et
  renvoie les messages à envoyer aux membres concernés (alerte ou favori sur le produit).
  À la toute première lecture d'une source, rien n'est envoyé : on mémorise l'existant.
- signaler_drop() : arrivage en magasin signalé par un membre (/drop).
- traiter_message() : message d'un salon Discord suivi (fonction « Suivre » de Discord).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .base import BaseDonnees
from .comparateur import Comparateur
from .config import Parametres
from .connecteurs.base import ErreurSource
from .models import Produit
from .sources_veille import CalendrierPokepedia, FluxAnnonces, flux_crocodeal, flux_fnac_eclaireur
from .temps import maintenant as maintenant_paris
from .veille import (
    DROP, INFO, SORTIE, Annonce, code_postal, dates_citees, magasin_cite, produits_cites,
)

log = logging.getLogger(__name__)
_MOTS_DROP = re.compile(
    r"\b(restock|reassort|réassort|arrivage|arrivé|arrive|en stock|dispo|disponible|drop|en rayon|rayon|"
    r"mise en rayon|livraison magasin|reçu|recu|invitation|vente réservée|vente reservee|ajout panier|"
    r"baisse de prix)\b", re.IGNORECASE,
)
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


@dataclass
class Envoi:
    utilisateur_id: int
    salon_id: int | None
    annonce: Annonce


@dataclass
class LigneSortie:
    produit: Produit
    date_sortie: object | None  # date | None
    source: str | None
    url: str | None
    annonces: list[Annonce] = field(default_factory=list)


class ServiceVeille:
    def __init__(
        self, parametres: Parametres, comparateur: Comparateur, base: BaseDonnees,
        calendrier: CalendrierPokepedia | None = None, flux: list[FluxAnnonces] | None = None,
    ):
        self.p, self.comp, self.base = parametres, comparateur, base
        reel = not parametres.demo  # en démo : aucune requête réseau, seuls les /drop fonctionnent
        self.calendrier = calendrier if calendrier is not None else (
            CalendrierPokepedia(parametres.sources.get("pokepedia")) if reel else None)
        self.flux = flux if flux is not None else ([
            flux_crocodeal(parametres.sources.get("lecrocodeal")),
            flux_fnac_eclaireur(parametres.sources.get("fnac_eclaireur")),
        ] if reel else [])
        self.erreurs: dict[str, str] = {}

    @property
    def catalogue(self) -> list[Produit]:
        return self.comp.catalogue

    def _envois(self, a: Annonce, exclure: int | None = None) -> list[Envoi]:
        envois, vus = [], set()
        for pid in a.produit_ids:
            for uid, salon in self.base.abonnes(pid):
                if uid != exclure and uid not in vus:
                    vus.add(uid)
                    envois.append(Envoi(uid, salon, a))
        return envois

    # --- Lecture des sources ------------------------------------------------------------------
    def actualiser(self, instant: datetime | None = None) -> list[Envoi]:
        instant = instant or maintenant_paris()
        envois = self._calendrier(instant)
        for f in self.flux:
            envois += self._flux(f)
        envois += self._rappels(instant)
        return envois

    def _calendrier(self, instant: datetime) -> list[Envoi]:
        if self.calendrier is None or not self.calendrier.config.actif:
            return []
        try:
            dates = self.calendrier.dates(self.catalogue)
        except ErreurSource as exc:
            self.erreurs[self.calendrier.id] = str(exc)
            return []
        self.erreurs.pop(self.calendrier.id, None)
        premiere_lecture = self.base.marquer_veille(f"init:{self.calendrier.id}")
        envois = []
        for d in dates:
            connue = self.base.date_sortie(d.produit_id, d.source)
            ancienne = self.base.maj_date_sortie(d.produit_id, d.source, d.date_sortie, d.url)
            if premiere_lecture or (connue and ancienne is None):
                continue  # rien de nouveau (ou première lecture : on mémorise sans notifier)
            produit = self.comp.produit(d.produit_id)
            nom = produit.nom if produit else d.produit_id
            if ancienne:
                titre = f"Date de sortie modifiée : {nom} — {ancienne:%d/%m/%Y} → {d.date_sortie:%d/%m/%Y}"
            else:
                titre = f"Date de sortie annoncée : {nom} — {d.date_sortie:%d/%m/%Y}"
            a = Annonce(source=d.source, cle=f"{d.source}:{d.produit_id}:{d.date_sortie.isoformat()}", type=SORTIE,
                        titre=titre, url=d.url, publie_le=instant, dates=[d.date_sortie], produit_ids=[d.produit_id])
            if self.base.enregistrer_annonce(a):
                envois += self._envois(a)
        return envois

    def _flux(self, f: FluxAnnonces) -> list[Envoi]:
        if not f.config.actif:
            return []
        try:
            annonces = f.annonces(self.catalogue)
        except ErreurSource as exc:
            self.erreurs[f.id] = str(exc)
            return []
        self.erreurs.pop(f.id, None)
        premiere_lecture = self.base.marquer_veille(f"init:{f.id}")
        envois = []
        for a in annonces:
            if self.base.enregistrer_annonce(a) and not premiere_lecture and a.produit_ids:
                envois += self._envois(a)
        return envois

    def _rappels(self, instant: datetime) -> list[Envoi]:
        """La veille d'une sortie annoncée : un rappel unique aux membres qui suivent le produit."""
        if not self.p.rappel_veille_sortie:
            return []
        demain = instant.date() + timedelta(days=1)
        envois = []
        for pid, (jour, source, url) in self.base.dates_sortie().items():
            if jour != demain or not self.base.marquer_veille(f"rappel:{pid}:{jour.isoformat()}"):
                continue
            produit = self.comp.produit(pid)
            a = Annonce(source=source, cle=f"rappel:{pid}:{jour.isoformat()}", type=SORTIE,
                        titre=f"Sortie prévue demain ({jour:%d/%m/%Y}) : {produit.nom if produit else pid}",
                        url=url, publie_le=instant, dates=[jour], produit_ids=[pid])
            envois += self._envois(a)
        return envois

    # --- Drops ------------------------------------------------------------------------------------
    def signaler_drop(
        self, utilisateur_id: int, produit: Produit, magasin: str, ville: str | None = None,
        details: str | None = None, instant: datetime | None = None,
    ) -> tuple[Annonce | None, list[Envoi], str | None]:
        instant = instant or datetime.now(timezone.utc)
        dernier = self.base.dernier_drop(utilisateur_id, produit.id)
        delai = timedelta(minutes=self.p.delai_entre_drops_minutes)
        if dernier and instant - dernier < delai:
            return None, [], (f"vous avez déjà signalé ce produit il y a moins de "
                              f"{self.p.delai_entre_drops_minutes} min")
        a = Annonce(
            source="membre", cle=f"membre:{utilisateur_id}:{produit.id}:{int(instant.timestamp())}", type=DROP,
            titre=f"Arrivage signalé : {produit.nom}", publie_le=instant, texte=(details or "")[:300],
            produit_ids=[produit.id], magasin=magasin.strip()[:80], ville=(ville or "").strip()[:80] or None,
            utilisateur_id=utilisateur_id,
        )
        self.base.enregistrer_annonce(a)
        return a, self._envois(a, exclure=utilisateur_id), None

    def traiter_message(self, cle: str, texte: str, url: str | None, publie_le: datetime) -> list[Envoi]:
        """Message relayé depuis un salon d'annonces suivi : gardé seulement s'il cite un produit du catalogue."""
        produits = produits_cites(texte, self.catalogue)
        if not produits:
            return []
        premiere_ligne = next((l.strip() for l in texte.splitlines() if l.strip()), "message")
        a = Annonce(
            source="discord", cle=f"discord:{cle}", type=DROP if _MOTS_DROP.search(texte) else INFO,
            titre=premiere_ligne[:150], url=url, publie_le=publie_le, texte=texte[:500],
            dates=dates_citees(texte, publie_le.date()), produit_ids=[p.id for p in produits],
            magasin=magasin_cite(texte), ville=code_postal(texte),
        )
        return self._envois(a) if self.base.enregistrer_annonce(a) else []

    # --- Consultation ---------------------------------------------------------------------------
    def sorties(self, produits: list[Produit] | None = None) -> list[LigneSortie]:
        dates = self.base.dates_sortie()
        lignes = []
        for p in produits if produits is not None else self.comp.produits_anniversaire():
            jour, source, url = dates.get(p.id, (None, None, None))
            annonces = self.base.annonces(produit_id=p.id, types=(SORTIE, INFO), limite=2)
            lignes.append(LigneSortie(p, jour, source, url, annonces))
        lointain = datetime.max.date()
        return sorted(lignes, key=lambda l: (l.date_sortie is None, l.date_sortie or lointain, l.produit.nom))

    def drops(self, produit: Produit | None = None, jours: int = 30) -> tuple[list[Annonce], list[tuple[str, str, int]]]:
        depuis = datetime.now(timezone.utc) - timedelta(days=jours)
        liste = self.base.annonces(produit_id=produit.id if produit else None, types=(DROP,), depuis=depuis, limite=200)
        stats = Counter(
            (a.magasin or "magasin non précisé", JOURS[a.publie_le.astimezone(maintenant_paris().tzinfo).weekday()])
            for a in liste
        )
        return liste, [(m, j, n) for (m, j), n in stats.most_common(8)]
