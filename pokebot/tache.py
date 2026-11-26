"""Une exécution complète de la version « site + webhook » (lancée toutes les 30 min par GitHub Actions).

1. synchronise config/suivi.toml avec la base (abonné virtuel n°0 = le salon du webhook) ;
2. lit la veille (Poképédia, Le CrocoDeal, Fnac) et compare les prix des produits suivis ;
3. poste les nouveautés dans le salon Discord par webhook ;
4. régénère le site statique.

Aucun bot n'est connecté : les commandes slash et les messages privés n'existent pas dans ce mode.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .affichage import formater_notification
from .affichage_veille import formater_annonce
from .alertes import evaluer_alerte
from .analyse import Rapport
from .base import BaseDonnees
from .comparateur import Comparateur
from .config import RACINE, Parametres
from .models import Etat
from .service_veille import ServiceVeille
from .site import generer_site
from .webhook import Webhook

log = logging.getLogger(__name__)
SALON = 0  # abonné virtuel : tout ce qui lui est destiné part sur le webhook
FREQUENCE_TACHE = 30


@dataclass
class Suivi:
    produits: list[str]
    prix_max: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class Bilan:
    messages: list[str]
    envoyes: int
    rapports: list[Rapport]
    erreurs: dict[str, str]


def charger_suivi(chemin: Path, comp: Comparateur) -> Suivi:
    conf = tomllib.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}
    choix = conf.get("produits", "tous")
    gamme = [p.id for p in comp.produits_anniversaire()]
    produits = gamme if choix == "tous" else [i for i in choix if comp.produit(i)]
    inconnus = [i for i in (choix if isinstance(choix, list) else []) if not comp.produit(i)]
    if inconnus:
        log.warning("suivi.toml : produit(s) inconnu(s) ignoré(s) : %s", ", ".join(inconnus))
    prix = {k: Decimal(str(v)) for k, v in (conf.get("prix_max") or {}).items() if comp.produit(k) and float(v) > 0}
    return Suivi(produits=produits, prix_max=prix)


def synchroniser(base: BaseDonnees, suivi: Suivi) -> None:
    """La base reflète exactement le fichier : favoris et alertes de l'abonné n°0."""
    for pid in set(base.favoris(SALON)) - set(suivi.produits):
        base.retirer_favori(SALON, pid)
    for pid in suivi.produits:
        base.ajouter_favori(SALON, pid)
    existantes = {a.produit_id: a for a in base.alertes(SALON)}
    for pid, alerte in existantes.items():
        if suivi.prix_max.get(pid) != alerte.prix_max:
            base.supprimer_alerte(SALON, alerte.id)  # prix modifié ou retiré : l'état repart de zéro
    restantes = {a.produit_id for a in base.alertes(SALON)}
    for pid, prix in suivi.prix_max.items():
        if pid not in restantes:
            base.creer_alerte(SALON, pid, prix, FREQUENCE_TACHE, etat=Etat.NEUF, langue="fr")


def executer(
    p: Parametres, comp: Comparateur, base: BaseDonnees, webhook: Webhook,
    dossier_site: Path, veille: ServiceVeille | None = None, chemin_suivi: Path | None = None,
    envoyer: bool = True,
) -> Bilan:
    veille = veille or ServiceVeille(p, comp, base)
    suivi = charger_suivi(chemin_suivi or RACINE / "config" / "suivi.toml", comp)
    synchroniser(base, suivi)
    catalogue = {pr.id: pr for pr in comp.catalogue}
    messages: list[str] = []

    # Veille : un message par annonce (l'abonné n°0 ne reçoit chaque annonce qu'une fois).
    for e in veille.actualiser():
        if e.utilisateur_id == SALON:
            produits = [catalogue[i] for i in e.annonce.produit_ids if i in catalogue]
            messages.append(formater_annonce(e.annonce, produits))

    # Prix : comparatif de chaque produit suivi (sert aussi au site) et alertes de prix maximum.
    rapports = {pid: comp.rapport(catalogue[pid]) for pid in suivi.produits if pid in catalogue}
    for alerte in base.alertes(SALON):
        produit = catalogue.get(alerte.produit_id)
        if produit is None:
            continue
        rapport = comp.rapport(produit, alerte.preferences())
        notifications, etat = evaluer_alerte(rapport, alerte.prix_max, alerte.etat_alerte)
        messages += [formater_notification(n, rapport, alerte.prix_max) for n in notifications]
        base.maj_etat_alerte(alerte.id, etat)

    envoyes = 0
    if messages and envoyer:
        if webhook.configure:
            envoyes = webhook.envoyer_tous(messages)
        else:
            log.warning("%d message(s) non envoyé(s) : DISCORD_WEBHOOK_URL absent", len(messages))

    generer_site(dossier_site, list(rapports.values()), veille.sorties(), base, catalogue,
                 erreurs=veille.erreurs, demo=p.demo)
    return Bilan(messages, envoyes, list(rapports.values()), dict(veille.erreurs))
