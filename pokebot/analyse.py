"""Calcul des prix totaux, des références (Amazon, médiane), de l'avis du bot et du classement."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .config import Seuils
from .correspondance import Correspondance, ResultatCorrespondance, comparer
from .models import (
    Disponibilite, Etat, Offre, Preferences, Produit, StatutLivraison, TypeProduit, TypeVendeur,
)
from .risques import CODES_CONTREFACON, Signal, signal_prix_anormal, signaux_annonce, vendeur_fiable
from .temps import maintenant

CENTIME = Decimal("0.01")
SITE_AMAZON = "amazon.fr"


class Avis(str, Enum):
    TRES_BONNE_AFFAIRE = "Très bonne affaire"
    RAISONNABLE = "Prix raisonnable"
    UN_PEU_CHER = "Un peu cher"
    CHER = "Cher"
    A_VERIFIER = "À vérifier"
    INSUFFISANT = "Comparaison insuffisante"


EMOJI_AVIS = {
    Avis.TRES_BONNE_AFFAIRE: "🟢",
    Avis.RAISONNABLE: "🔵",
    Avis.UN_PEU_CHER: "🟠",
    Avis.CHER: "🔴",
    Avis.A_VERIFIER: "⚠️",
    Avis.INSUFFISANT: "⚪",
}


@dataclass(frozen=True)
class PrixTotal:
    montant: Decimal | None  # prix + livraison + frais obligatoires connus
    exact: bool  # False si la livraison est inconnue ou estimée
    mention: str


def prix_total(offre: Offre) -> PrixTotal:
    if offre.prix is None:
        return PrixTotal(None, False, "prix non communiqué")
    base = offre.prix + (offre.frais_obligatoires or Decimal("0"))
    if offre.statut_livraison is StatutLivraison.CONNUE and offre.livraison is not None:
        return PrixTotal((base + offre.livraison).quantize(CENTIME), True, "livraison comprise")
    if offre.statut_livraison is StatutLivraison.ESTIMEE and offre.livraison is not None:
        return PrixTotal((base + offre.livraison).quantize(CENTIME), False, "livraison estimée, à vérifier")
    return PrixTotal(base.quantize(CENTIME), False, "frais de livraison à vérifier")


def avis_prix(
    total: Decimal | None,
    ref_amazon: Decimal | None,
    mediane: Decimal | None,
    seuils: Seuils,
    *,
    carte: bool = False,
    a_verifier: bool = False,
) -> tuple[Avis, str]:
    """Applique les règles de l'avis. Renvoie (avis, explication)."""
    if a_verifier:
        return Avis.A_VERIFIER, "points à vérifier avant tout achat"
    if total is None:
        return Avis.INSUFFISANT, "prix non communiqué"

    refs: dict[str, Decimal] = {}
    if ref_amazon is not None and not carte:
        refs["Amazon"] = ref_amazon
    if mediane is not None:
        refs["médiane"] = mediane
    if not refs:
        if carte:
            return Avis.INSUFFISANT, f"moins de {seuils.min_offres_mediane} offres comparables pour calculer une médiane"
        return Avis.INSUFFISANT, "ni référence Amazon ni médiane du marché"

    note = "comparé à : " + " et ".join(refs)
    if carte:
        affaire = total <= refs["médiane"] * seuils.tres_bonne_affaire_carte
    elif len(refs) == 2:
        affaire = (total <= refs["Amazon"] * seuils.tres_bonne_affaire_amazon
                   and total <= refs["médiane"] * seuils.tres_bonne_affaire_mediane)
    elif seuils.exiger_deux_references:
        affaire = False
        note += " (une seule référence : « très bonne affaire » non attribuable)"
    else:
        cle, ref = next(iter(refs.items()))
        seuil = seuils.tres_bonne_affaire_amazon if cle == "Amazon" else seuils.tres_bonne_affaire_mediane
        affaire = total <= ref * seuil

    if affaire:
        return Avis.TRES_BONNE_AFFAIRE, note
    if any(total <= r * seuils.raisonnable for r in refs.values()):
        return Avis.RAISONNABLE, note
    if all(total > r * seuils.cher for r in refs.values()):
        return Avis.CHER, note
    return Avis.UN_PEU_CHER, note


@dataclass
class LigneOffre:
    offre: Offre
    correspondance: ResultatCorrespondance
    total: PrixTotal
    signaux: list[Signal]
    comparable: bool
    avis: Avis = Avis.INSUFFISANT
    note_avis: str = ""
    ecart_amazon_eur: Decimal | None = None
    ecart_amazon_pct: Decimal | None = None

    @property
    def bloquee(self) -> bool:
        return any(s.bloquant for s in self.signaux)

    @property
    def suspecte(self) -> bool:
        return any(s.code in CODES_CONTREFACON for s in self.signaux)


@dataclass
class ReferenceAmazon:
    montant: Decimal
    ligne: LigneOffre
    vendeur_tiers: bool
    hors_livraison: bool


@dataclass
class Rapport:
    produit: Produit
    lignes: list[LigneOffre]  # annonces classées
    ventes_reelles: list[LigneOffre]
    ref_amazon: ReferenceAmazon | None
    mediane: Decimal | None
    nb_offres_mediane: int
    mediane_ventes: Decimal | None
    annonces_ecartees: int
    statut_amazon: str
    statuts_sources: dict[str, str] = field(default_factory=dict)
    genere_le: datetime = field(default_factory=maintenant)
    demo: bool = False


def _mediane(valeurs: list[Decimal]) -> Decimal:
    return Decimal(statistics.median(valeurs)).quantize(CENTIME)


def choisir_reference_amazon(lignes: list[LigneOffre], seuils: Seuils) -> ReferenceAmazon | None:
    """Offre Amazon.fr disponible, neuve, même produit. Priorité : vendu et expédié par Amazon."""
    candidates = [
        l for l in lignes
        if l.offre.site == SITE_AMAZON and l.comparable and not l.offre.vente_reelle
        and l.offre.disponibilite is Disponibilite.EN_STOCK and l.total.montant is not None
        and not l.suspecte
    ]
    par_amazon = [l for l in candidates if l.offre.type_vendeur is TypeVendeur.AMAZON]
    # Un vendeur tiers n'est retenu que si sa réputation est connue et suffisante.
    tiers = [l for l in candidates if l.offre.type_vendeur is not TypeVendeur.AMAZON and vendeur_fiable(l.offre, seuils)]
    pool = par_amazon or tiers
    if not pool:
        return None
    meilleure = min(pool, key=lambda l: l.total.montant)
    return ReferenceAmazon(
        montant=meilleure.total.montant,  # type: ignore[arg-type]
        ligne=meilleure,
        vendeur_tiers=meilleure.offre.type_vendeur is not TypeVendeur.AMAZON,
        hors_livraison=meilleure.offre.statut_livraison is StatutLivraison.INCONNUE,
    )


def cle_classement(l: LigneOffre) -> tuple[int, Decimal]:
    dispo = l.offre.disponibilite
    if dispo is Disponibilite.RUPTURE:
        groupe = 5
    elif not l.comparable:
        groupe = 4
    elif l.bloquee:
        groupe = 3
    elif dispo is Disponibilite.EN_STOCK:
        groupe = 0
    elif dispo is Disponibilite.PRECOMMANDE:
        groupe = 1
    else:
        groupe = 2
    return groupe, l.total.montant if l.total.montant is not None else Decimal("Infinity")


def construire_rapport(
    produit: Produit,
    offres: list[Offre],
    seuils: Seuils,
    preferences: Preferences | None = None,
    *,
    statut_amazon: str = "",
    statuts_sources: dict[str, str] | None = None,
    demo: bool = False,
) -> Rapport:
    est_carte = produit.type in (TypeProduit.CARTE, TypeProduit.CARTE_GRADEE)
    etat_attendu = None if est_carte else Etat.NEUF

    lignes: list[LigneOffre] = []
    ecartees = 0
    for offre in offres:
        corr = comparer(produit, offre)
        if corr.statut is Correspondance.DIFFERENTE:
            ecartees += 1
            continue
        comparable = corr.statut is Correspondance.EXACTE and (etat_attendu is None or offre.etat is etat_attendu)
        lignes.append(LigneOffre(
            offre=offre,
            correspondance=corr,
            total=prix_total(offre),
            signaux=signaux_annonce(produit, offre, corr, seuils, preferences),
            comparable=comparable,
        ))

    annonces = [l for l in lignes if not l.offre.vente_reelle]
    ventes = [l for l in lignes if l.offre.vente_reelle]

    ref = None if est_carte else choisir_reference_amazon(annonces, seuils)

    base_mediane = [
        l.total.montant for l in annonces
        if l.comparable and l.total.montant is not None
        and l.offre.disponibilite in (Disponibilite.EN_STOCK, Disponibilite.PRECOMMANDE)
        and l.offre.statut_livraison is not StatutLivraison.INCONNUE
        and vendeur_fiable(l.offre, seuils) and not l.bloquee
    ]
    mediane = _mediane(base_mediane) if len(base_mediane) >= seuils.min_offres_mediane else None  # type: ignore[arg-type]

    base_ventes = [l.total.montant for l in ventes if l.comparable and l.total.montant is not None and not l.suspecte]
    mediane_ventes = _mediane(base_ventes) if len(base_ventes) >= seuils.min_offres_mediane else None  # type: ignore[arg-type]

    reference_marche = mediane if mediane is not None else (ref.montant if ref else None)
    for l in annonces:
        if l.total.montant is not None and reference_marche is not None:
            s = signal_prix_anormal(l.total.montant, reference_marche, seuils)
            if s:
                l.signaux.append(s)
        if not l.comparable:
            if l.correspondance.statut is Correspondance.A_VERIFIER:
                l.avis, l.note_avis = Avis.A_VERIFIER, f"correspondance à vérifier ({l.correspondance.raison})"
            else:
                l.avis, l.note_avis = Avis.INSUFFISANT, f"état « {l.offre.etat.value} » : non comparable au neuf"
            continue
        l.avis, l.note_avis = avis_prix(
            l.total.montant,
            ref.montant if ref else None,
            mediane,
            seuils,
            carte=est_carte,
            a_verifier=l.bloquee,
        )
        if ref is not None and l.total.montant is not None:
            l.ecart_amazon_eur = (l.total.montant - ref.montant).quantize(CENTIME)
            l.ecart_amazon_pct = ((l.total.montant - ref.montant) / ref.montant * 100).quantize(Decimal("0.1"))

    annonces.sort(key=cle_classement)
    ventes.sort(key=lambda l: l.offre.verifie_le.timestamp() if l.offre.verifie_le else 0.0, reverse=True)
    return Rapport(
        produit=produit,
        lignes=annonces,
        ventes_reelles=ventes,
        ref_amazon=ref,
        mediane=mediane,
        nb_offres_mediane=len(base_mediane),
        mediane_ventes=mediane_ventes,
        annonces_ecartees=ecartees,
        statut_amazon=statut_amazon,
        statuts_sources=dict(statuts_sources or {}),
        demo=demo,
    )


def meilleure_offre(rapport: Rapport) -> LigneOffre | None:
    """Meilleure offre fiable : comparable, sans signal bloquant, en stock ou en précommande."""
    for l in rapport.lignes:
        if cle_classement(l)[0] <= 1:
            return l
    return None
