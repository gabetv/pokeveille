"""Modèles de données : produits de référence, offres et préférences utilisateur."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TypeVar

from .texte import normaliser_texte


class TypeProduit(str, Enum):
    SCELLE = "scelle"  # produit JCC neuf scellé : booster, coffret, ETB, UPC, deck…
    DERIVE = "derive"  # figurine, peluche, jeu, accessoire…
    CARTE = "carte"  # carte à l'unité
    CARTE_GRADEE = "carte_gradee"


class Etat(str, Enum):
    NEUF = "neuf"  # pour un produit scellé : neuf scellé
    OUVERT = "ouvert"
    OCCASION = "occasion"
    INCONNU = "inconnu"


class Disponibilite(str, Enum):
    EN_STOCK = "en_stock"
    PRECOMMANDE = "precommande"
    RUPTURE = "rupture"
    INCONNUE = "inconnue"


class StatutLivraison(str, Enum):
    CONNUE = "connue"  # frais lus sur la source
    ESTIMEE = "estimee"  # barème saisi par l'utilisateur dans config/parametres.toml
    INCONNUE = "inconnue"


class TypeVendeur(str, Enum):
    AMAZON = "amazon"  # vendu et expédié par Amazon
    AMAZON_TIERS = "amazon_tiers"  # vendeur tiers sur Amazon
    ENSEIGNE = "enseigne"  # vendu par l'enseigne elle-même (Fnac, Cultura…)
    MARKETPLACE = "marketplace"  # vendeur tiers sur une place de marché
    PARTICULIER = "particulier"
    INCONNU = "inconnu"


LIBELLES_TYPE = {
    TypeProduit.SCELLE: "produit JCC scellé",
    TypeProduit.DERIVE: "produit dérivé",
    TypeProduit.CARTE: "carte à l'unité",
    TypeProduit.CARTE_GRADEE: "carte gradée",
}

LIBELLES_DISPO = {
    Disponibilite.EN_STOCK: "en stock",
    Disponibilite.PRECOMMANDE: "précommande",
    Disponibilite.RUPTURE: "indisponible / rupture",
    Disponibilite.INCONNUE: "disponibilité non confirmée",
}

LIBELLES_VENDEUR = {
    TypeVendeur.AMAZON: "vendu et expédié par Amazon",
    TypeVendeur.AMAZON_TIERS: "vendeur tiers sur Amazon",
    TypeVendeur.ENSEIGNE: "vendu par l'enseigne",
    TypeVendeur.MARKETPLACE: "vendeur tiers (place de marché)",
    TypeVendeur.PARTICULIER: "particulier",
    TypeVendeur.INCONNU: "type de vendeur inconnu",
}

_LANGUES = {
    "fr": "fr", "francais": "fr", "vf": "fr", "french": "fr",
    "en": "en", "anglais": "en", "english": "en", "eng": "en", "vo": "en",
    "ja": "ja", "jp": "ja", "japonais": "ja", "japanese": "ja",
    "de": "de", "allemand": "de", "it": "it", "italien": "it",
    "es": "es", "espagnol": "es", "ko": "ko", "coreen": "ko", "zh": "zh", "chinois": "zh",
}

NOMS_LANGUES = {
    "fr": "VF (français)", "en": "anglais", "ja": "japonais", "de": "allemand",
    "it": "italien", "es": "espagnol", "ko": "coréen", "zh": "chinois",
}

_ALIAS_ETAT = {
    "neuf": Etat.NEUF, "neuf scelle": Etat.NEUF, "scelle": Etat.NEUF, "new": Etat.NEUF,
    "occasion": Etat.OCCASION, "used": Etat.OCCASION, "reconditionne": Etat.OCCASION,
    "ouvert": Etat.OUVERT, "opened": Etat.OUVERT,
}
_ALIAS_DISPO = {
    "en stock": Disponibilite.EN_STOCK, "disponible": Disponibilite.EN_STOCK,
    "precommande": Disponibilite.PRECOMMANDE, "preorder": Disponibilite.PRECOMMANDE,
    "rupture": Disponibilite.RUPTURE, "indisponible": Disponibilite.RUPTURE,
    "epuise": Disponibilite.RUPTURE,
}

E = TypeVar("E", bound=Enum)


def enum_depuis(classe: type[E], valeur: str | None, alias: dict | None = None, defaut: E | None = None) -> E | None:
    if valeur is None or not str(valeur).strip():
        return defaut
    brut = str(valeur).strip().lower()
    for membre in classe:
        if membre.value == brut:
            return membre
    cle = normaliser_texte(brut)
    if alias and cle in alias:
        return alias[cle]
    cle_tiret = cle.replace(" ", "_")
    for membre in classe:
        if membre.value == cle_tiret:
            return membre
    raise ValueError(f"valeur inconnue pour {classe.__name__} : {valeur!r}")


def etat_depuis(valeur: str | None) -> Etat:
    return enum_depuis(Etat, valeur, _ALIAS_ETAT, Etat.INCONNU)  # type: ignore[return-value]


def dispo_depuis(valeur: str | None) -> Disponibilite:
    return enum_depuis(Disponibilite, valeur, _ALIAS_DISPO, Disponibilite.INCONNUE)  # type: ignore[return-value]


def normaliser_langue(valeur: str | None) -> str | None:
    if not valeur or not str(valeur).strip():
        return None
    cle = normaliser_texte(str(valeur))
    return _LANGUES.get(cle, cle)


def parser_decimal(valeur: str | float | int | Decimal | None) -> Decimal | None:
    """Accepte « 49,99 », « 49.99 € », 49.99… Renvoie None si vide."""
    if valeur is None:
        return None
    if isinstance(valeur, Decimal):
        return valeur
    texte = str(valeur).strip().replace("€", "").replace(" ", "").replace("\xa0", "").replace(" ", "")
    if not texte:
        return None
    texte = texte.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", texte):
        raise ValueError(f"montant invalide : {valeur!r}")
    try:
        return Decimal(texte)
    except InvalidOperation as exc:  # pragma: no cover - protégé par la regex
        raise ValueError(f"montant invalide : {valeur!r}") from exc


@dataclass
class Produit:
    """Produit de référence (catalogue vérifié sur la source officielle)."""

    id: str
    nom: str
    categorie: str
    type: TypeProduit
    langue: str | None = "fr"
    gamme: str = ""
    ean: str | None = None
    asin: str | None = None
    ref_fabricant: str | None = None  # pour une carte : numéro dans l'extension
    edition: str | None = None
    contenu: str | None = None
    variante: str | None = None
    etat_carte: str | None = None  # NM, EX… (cartes à l'unité)
    societe_gradation: str | None = None  # PSA, CGC, PCA…
    note_gradation: str | None = None
    lien_officiel: str | None = None
    prix_conseille: Decimal | None = None
    source_prix_conseille: str | None = None
    mots_cles: str = ""
    demo: bool = False


@dataclass
class Offre:
    """Annonce trouvée sur un site marchand ou un marché secondaire."""

    source: str  # identifiant du connecteur ou de la source (amazon_fr, fnac…)
    site: str  # domaine affiché (amazon.fr, fnac.com…)
    titre: str
    url: str
    prix: Decimal | None
    livraison: Decimal | None = None
    statut_livraison: StatutLivraison = StatutLivraison.INCONNUE
    frais_obligatoires: Decimal = Decimal("0")
    devise: str = "EUR"
    vendeur: str | None = None
    type_vendeur: TypeVendeur = TypeVendeur.INCONNU
    note_vendeur: Decimal | None = None  # en % d'avis positifs
    nb_avis_vendeur: int | None = None
    etat: Etat = Etat.INCONNU
    langue: str | None = None
    disponibilite: Disponibilite = Disponibilite.INCONNUE
    type: TypeProduit | None = None
    ean: str | None = None
    asin: str | None = None
    ref_fabricant: str | None = None
    edition: str | None = None
    contenu: str | None = None
    variante: str | None = None
    etat_carte: str | None = None
    societe_gradation: str | None = None
    note_gradation: str | None = None
    description: str = ""
    verifie_le: datetime | None = None
    vente_reelle: bool = False  # True = prix réellement payé (vente conclue), pas une annonce
    signalement: bool = False  # True = bon plan publié par une communauté (Le CrocoDeal), non vérifié
    demo: bool = False


@dataclass
class Preferences:
    prix_max: Decimal | None = None
    categorie: str | None = None
    etat: Etat | None = None
    langue: str | None = None
    sites: list[str] = field(default_factory=list)  # vide = tous les sites
    frequence_minutes: int | None = None

    def vers_dict(self) -> dict:
        return {
            "prix_max": str(self.prix_max) if self.prix_max is not None else None,
            "categorie": self.categorie,
            "etat": self.etat.value if self.etat else None,
            "langue": self.langue,
            "sites": list(self.sites),
            "frequence_minutes": self.frequence_minutes,
        }

    @classmethod
    def depuis_dict(cls, d: dict | None) -> "Preferences":
        d = d or {}
        return cls(
            prix_max=parser_decimal(d.get("prix_max")),
            categorie=d.get("categorie") or None,
            etat=Etat(d["etat"]) if d.get("etat") else None,
            langue=d.get("langue") or None,
            sites=list(d.get("sites") or []),
            frequence_minutes=d.get("frequence_minutes"),
        )
