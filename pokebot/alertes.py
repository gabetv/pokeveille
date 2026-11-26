"""Évaluation des alertes : passage sous le prix maximum, retour en stock et bons plans signalés."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .analyse import LigneOffre, Rapport
from .correspondance import Correspondance
from .models import Disponibilite
from .temps import maintenant

# Signal bloquant toléré pour une alerte (le message précise « frais de livraison à vérifier »).
# Tout autre signal bloquant (vendeur inconnu, prix anormal, copie, mauvaise langue…) exclut l'offre.
CODES_TOLERES_ALERTE = {"FRAIS_INCONNUS"}

# Un bon plan communautaire est toujours « à vérifier » (vendeur, stock et livraison non confirmés).
# Il n'est quand même jamais signalé s'il évoque une copie, un produit ouvert, une autre langue ou un autre état.
CODES_EXCLUANT_SIGNALEMENT = {"MOTS_SUSPECTS", "OUVERT_VENDU_SCELLE", "LANGUE_DIFFERENTE", "ETAT_DIFFERENT"}
MAX_SIGNALEMENTS_PAR_VERIFICATION = 3


@dataclass
class EtatAlerte:
    dernier_total_notifie: Decimal | None = None
    etait_disponible: bool | None = None  # None = jamais vérifiée
    dernier_signalement: datetime | None = None  # date du bon plan communautaire le plus récent déjà vu


@dataclass
class Notification:
    type: str  # "prix", "stock" ou "signalement"
    ligne: LigneOffre


def lignes_eligibles(rapport: Rapport) -> list[LigneOffre]:
    return [
        l for l in rapport.lignes
        if l.comparable and l.total.montant is not None
        and l.offre.disponibilite in (Disponibilite.EN_STOCK, Disponibilite.PRECOMMANDE)
        and not any(s.bloquant and s.code not in CODES_TOLERES_ALERTE for s in l.signaux)
    ]


def signalements_candidats(rapport: Rapport, prix_max: Decimal) -> list[LigneOffre]:
    return [
        l for l in rapport.lignes
        if l.offre.signalement and l.offre.verifie_le is not None and l.offre.prix is not None
        and l.offre.prix <= prix_max
        and l.correspondance.statut is not Correspondance.DIFFERENTE
        and not any(s.code in CODES_EXCLUANT_SIGNALEMENT for s in l.signaux)
    ]


def evaluer_alerte(rapport: Rapport, prix_max: Decimal, etat: EtatAlerte) -> tuple[list[Notification], EtatAlerte]:
    eligibles = lignes_eligibles(rapport)
    en_stock = [l for l in eligibles if l.offre.disponibilite is Disponibilite.EN_STOCK]
    notifications: list[Notification] = []

    if etat.etait_disponible is False and en_stock:
        notifications.append(Notification("stock", min(en_stock, key=lambda l: l.total.montant)))

    meilleure = min(eligibles, key=lambda l: l.total.montant) if eligibles else None
    nouveau_total = etat.dernier_total_notifie
    if meilleure is not None and meilleure.total.montant <= prix_max:  # type: ignore[operator]
        if etat.dernier_total_notifie is None or meilleure.total.montant < etat.dernier_total_notifie:  # type: ignore[operator]
            notifications.append(Notification("prix", meilleure))
            nouveau_total = meilleure.total.montant
    else:
        nouveau_total = None  # repasse au-dessus du seuil : on pourra notifier à nouveau

    # Bons plans communautaires : seulement ceux publiés depuis la vérification précédente.
    # À la première vérification, on mémorise la date sans notifier les anciens bons plans.
    dates = [l.offre.verifie_le for l in rapport.lignes if l.offre.signalement and l.offre.verifie_le]
    if etat.dernier_signalement is None:
        dernier = max(dates + [maintenant()])
    else:
        nouveaux = sorted(
            (l for l in signalements_candidats(rapport, prix_max) if l.offre.verifie_le > etat.dernier_signalement),  # type: ignore[operator]
            key=lambda l: l.offre.prix,  # type: ignore[arg-type, return-value]
        )
        notifications += [Notification("signalement", l) for l in nouveaux[:MAX_SIGNALEMENTS_PAR_VERIFICATION]]
        dernier = max(dates + [etat.dernier_signalement])

    return notifications, EtatAlerte(
        dernier_total_notifie=nouveau_total, etait_disponible=bool(en_stock), dernier_signalement=dernier,
    )
