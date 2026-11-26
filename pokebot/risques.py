"""Protection contre les fausses bonnes affaires : signaux de risque sur une annonce."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .config import Seuils
from .correspondance import Correspondance, ResultatCorrespondance
from .models import (
    Disponibilite, Etat, NOMS_LANGUES, Offre, Preferences, Produit, StatutLivraison,
    TypeProduit, TypeVendeur, normaliser_langue,
)
from .temps import format_paris
from .texte import normaliser_texte

MOTS_SUSPECTS = re.compile(
    r"\b(copie|copy|reproduction|repro|replique|replica|proxy|proxies|personnalise|personnalisee|"
    r"personnalisable|custom|fake|contrefacon|non officiel|non officielle|fan made|fanmade|orica)\b"
)
MOTS_OUVERT = re.compile(
    r"\b(ouvert|ouverte|deballe|deballee|opened|open box|sans blister|sans cellophane|"
    r"reemballe|resealed|rescelle|rescellee)\b"
)

# Signaux qui excluent une offre de toute référence de prix et de toute alerte.
CODES_CONTREFACON = {"MOTS_SUSPECTS", "OUVERT_VENDU_SCELLE"}


@dataclass(frozen=True)
class Signal:
    code: str
    message: str
    bloquant: bool = True  # True => l'avis devient « À vérifier »


def vendeur_fiable(offre: Offre, seuils: Seuils) -> bool:
    if offre.type_vendeur in (TypeVendeur.AMAZON, TypeVendeur.ENSEIGNE):
        return True
    if not offre.vendeur or offre.note_vendeur is None or offre.nb_avis_vendeur is None:
        return False
    return offre.note_vendeur >= seuils.note_vendeur_min and offre.nb_avis_vendeur >= seuils.avis_vendeur_min


def signaux_annonce(
    produit: Produit,
    offre: Offre,
    correspondance: ResultatCorrespondance,
    seuils: Seuils,
    preferences: Preferences | None = None,
) -> list[Signal]:
    signaux: list[Signal] = []
    texte = normaliser_texte(f"{offre.titre} {offre.description}")

    m = MOTS_SUSPECTS.search(texte)
    if m:
        signaux.append(Signal("MOTS_SUSPECTS", f"l'annonce mentionne « {m.group(1)} » : copie ou produit non officiel possible"))
    if offre.etat is Etat.NEUF and produit.type is TypeProduit.SCELLE:
        m = MOTS_OUVERT.search(texte)
        if m:
            signaux.append(Signal("OUVERT_VENDU_SCELLE", f"annonce « neuf » qui mentionne « {m.group(1)} » : produit peut-être ouvert"))

    if offre.prix is None:
        signaux.append(Signal("PRIX_INCONNU", "prix non communiqué"))
    if offre.statut_livraison is StatutLivraison.INCONNUE:
        signaux.append(Signal("FRAIS_INCONNUS", "frais de livraison à vérifier"))
    elif offre.statut_livraison is StatutLivraison.ESTIMEE:
        signaux.append(Signal("LIVRAISON_ESTIMEE", "livraison estimée d'après votre barème : à confirmer sur le site", bloquant=False))
    if offre.livraison is not None and offre.prix and offre.livraison / offre.prix > seuils.frais_port_eleves:
        part = (offre.livraison / offre.prix * 100).quantize(Decimal("1"))
        signaux.append(Signal("FRAIS_PORT_ELEVES", f"frais de port élevés ({part} % du prix affiché)", bloquant=False))

    if offre.type_vendeur not in (TypeVendeur.AMAZON, TypeVendeur.ENSEIGNE):
        if not offre.vendeur or offre.type_vendeur is TypeVendeur.INCONNU or offre.note_vendeur is None or offre.nb_avis_vendeur is None:
            signaux.append(Signal("VENDEUR_INCONNU", "vendeur à la réputation inconnue"))
        elif not vendeur_fiable(offre, seuils):
            signaux.append(Signal(
                "VENDEUR_PEU_FIABLE",
                f"réputation du vendeur insuffisante ({offre.note_vendeur} % sur {offre.nb_avis_vendeur} avis)",
            ))
    if offre.type_vendeur is TypeVendeur.AMAZON_TIERS:
        signaux.append(Signal("VENDEUR_TIERS_AMAZON", f"offre d'un vendeur tiers sur Amazon ({offre.vendeur or 'nom inconnu'})", bloquant=False))

    if not (offre.ean or offre.asin or offre.ref_fabricant):
        signaux.append(Signal("SANS_REFERENCE", "aucune référence produit (EAN, ASIN ou référence) dans l'annonce"))
    if correspondance.statut is Correspondance.A_VERIFIER:
        signaux.append(Signal("CORRESPONDANCE_A_VERIFIER", f"correspondance à vérifier : {correspondance.raison}"))
    if offre.disponibilite is Disponibilite.INCONNUE:
        signaux.append(Signal("DISPONIBILITE_INCONNUE", "disponibilité non confirmée", bloquant=False))
    if offre.signalement:
        date = f" le {format_paris(offre.verifie_le)}" if offre.verifie_le else ""
        signaux.append(Signal(
            "SIGNALEMENT_COMMUNAUTE",
            f"bon plan publié par la communauté{date} : prix, stock, vendeur et livraison à vérifier chez le marchand",
            bloquant=False,
        ))

    if preferences:
        langue = normaliser_langue(offre.langue)
        if preferences.langue and langue and langue != preferences.langue:
            signaux.append(Signal("LANGUE_DIFFERENTE", f"langue {NOMS_LANGUES.get(langue, langue)} ≠ langue souhaitée"))
        if preferences.etat and offre.etat is not Etat.INCONNU and offre.etat is not preferences.etat:
            signaux.append(Signal("ETAT_DIFFERENT", f"état « {offre.etat.value} » ≠ état souhaité « {preferences.etat.value} »"))
    return signaux


def signal_prix_anormal(total: Decimal, reference: Decimal, seuils: Seuils) -> Signal | None:
    if reference > 0 and total < reference * seuils.prix_anormal:
        part = (total / reference * 100).quantize(Decimal("1"))
        return Signal(
            "PRIX_ANORMAL",
            f"prix anormalement bas ({part} % de la référence du marché) : erreur, contrefaçon ou arnaque possible",
        )
    return None
