"""Veille des sorties et des drops : annonces, dates citées, produits reconnus dans un texte libre.

Une « annonce » est tout ce qui renseigne sur QUAND et OÙ trouver un produit, sans être une offre
de prix : date de sortie officielle (Poképédia), article « où acheter » (Le CrocoDeal), communiqué
d'enseigne (blog Fnac L'Éclaireur), arrivage en magasin signalé par un membre (/drop) ou relayé
depuis un salon Discord suivi. Rien n'y est inventé : une annonce cite toujours sa source, et un
arrivage signalé reste « à confirmer ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .correspondance import normaliser_gtin
from .models import Produit
from .texte import jetons, normaliser_texte

# Types d'annonce
SORTIE = "sortie"  # date de sortie officielle ou modifiée
INFO = "info"  # article, guide « où acheter », communiqué
DROP = "drop"  # arrivage en magasin ou restock signalé

LIBELLES_SOURCES = {
    "pokepedia": "Poképédia",
    "lecrocodeal": "Le CrocoDeal",
    "fnac_eclaireur": "Fnac — L'Éclaireur",
    "discord": "salon Discord suivi",
    "membre": "signalé par un membre",
}

# Mots qui ne distinguent pas un produit d'un autre de la même gamme.
GENERIQUES = {
    "coffret", "collection", "jcc", "pokemon", "ex", "avec", "pour", "sur", "chez", "ou", "acheter",
    "commander", "trouver", "stock", "date", "sortie", "prix", "lien", "achat", "nouveau", "nouvelle",
    "modele", "aleatoire", "ou",
}
# Formats de produit : si le texte en nomme un, le produit doit l'avoir aussi (évite ETB ↔ Pokébox).
FORMATS = {
    "pokebox", "deck", "classeur", "poster", "figurine", "mini", "tin", "blister", "duopack", "bundle",
    "lot", "autocollant", "sticker", "upc", "etb", "metamorph", "display", "booster",
}
FORMATS_DISTINCTIFS = {
    "etb", "upc", "pokebox", "classeur", "poster", "metamorph", "duopack", "bundle", "figurine", "autocollant",
}

MOIS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
_DATE_LETTRES = re.compile(r"\b(\d{1,2})(?:er)?\s+(" + "|".join(MOIS) + r")(?:\s+(\d{4}))?\b")
# « 09/12 », « 9/12/2026 » ; le mois sur deux chiffres évite de lire « 1/2 » ou « 116/128 » comme des dates.
_DATE_CHIFFRES = re.compile(r"\b(\d{1,2})/(\d{2})(?:/(\d{4}|\d{2}))?\b(?!/)")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_CODE_POSTAL = re.compile(r"\b((?:0[1-9]|[1-8]\d|9[0-5])\d{3})\b")


@dataclass
class Annonce:
    source: str  # pokepedia, lecrocodeal, fnac_eclaireur, discord, membre
    cle: str  # identifiant unique (URL, identifiant de message…), pour ne jamais notifier deux fois
    type: str  # SORTIE, INFO ou DROP
    titre: str
    publie_le: datetime
    url: str | None = None
    texte: str = ""
    dates: list[date] = field(default_factory=list)  # dates citées dans le texte
    produit_ids: list[str] = field(default_factory=list)
    magasin: str | None = None
    ville: str | None = None
    utilisateur_id: int | None = None  # auteur d'un /drop (effacé par /oubliermoi)

    @property
    def libelle_source(self) -> str:
        return LIBELLES_SOURCES.get(self.source, self.source)


@dataclass
class DateSortie:
    produit_id: str
    date_sortie: date
    source: str
    url: str | None = None
    titre_source: str = ""


def _racines(texte: str | None) -> set[str]:
    """Jetons normalisés, pluriel simple retiré (coffrets -> coffret)."""
    return {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in jetons(texte)}


def _indice_gamme(produit: Produit, mots: set[str]) -> bool:
    """Le texte doit évoquer la gamme du produit (« 30 ans », « 30e anniversaire »…)."""
    gamme = _racines(produit.gamme) - {"demo"}
    if not gamme:
        return True
    variantes = gamme | {t.rstrip("e") for t in gamme if t[:1].isdigit()}
    return bool(variantes & mots)


def correspond(produit: Produit, texte: str, variantes_connues: set[str] | None = None) -> bool:
    """Le texte parle-t-il de ce produit ? (EAN, ou nom distinctif + gamme + variante).

    variantes_connues : mots de toutes les variantes du catalogue. Un texte qui n'en cite aucune
    (« coffrets autocollant 30 ans ») concerne toutes les variantes d'un produit ; un texte qui en
    cite une autre (« figurine Mewtwo ») exclut celle-ci (Mew).
    """
    for brut in re.findall(r"\b\d{12,14}\b", texte):
        if produit.ean and normaliser_gtin(brut) and normaliser_gtin(brut) == normaliser_gtin(produit.ean):
            return True
    if produit.asin and re.search(rf"\b{re.escape(produit.asin)}\b", texte, re.IGNORECASE):
        return True  # alertes Amazon (ex. Alert&Go : « ASIN: B0H8SZV8L7 »)
    mots = _racines(texte)
    if not _indice_gamme(produit, mots):
        return False
    gamme = _racines(produit.gamme)
    propres = _racines(f"{produit.nom} {produit.mots_cles} {produit.variante or ''}")
    formats_cites = mots & FORMATS
    if formats_cites and not formats_cites & propres:
        return False
    variante = _racines(produit.variante) - GENERIQUES - gamme
    variante_citee = bool(variante & mots)
    if variante and not variante_citee and (variantes_connues is None or variantes_connues & mots):
        return False
    coeur = _racines(produit.nom) - GENERIQUES - gamme - variante
    if coeur <= mots and (coeur or variante_citee):
        return True
    alias = _racines(produit.mots_cles) - GENERIQUES - gamme - variante
    # Un sigle de format sans ambiguïté (« ETB 30 ans », « UPC Mentali ») suffit avec la gamme et la variante.
    return bool(alias & mots & FORMATS_DISTINCTIFS) or len(alias & mots) >= 2


def produits_cites(texte: str, catalogue: list[Produit]) -> list[Produit]:
    variantes: set[str] = set()
    for p in catalogue:
        variantes |= _racines(p.variante) - GENERIQUES - _racines(p.gamme)
    return [p for p in catalogue if correspond(p, texte, variantes)]


def _annee(jour: int, mois: int, reference: date) -> date | None:
    """Date sans année : on prend celle qui tombe entre 2 mois avant et 10 mois après la référence."""
    for annee in (reference.year - 1, reference.year, reference.year + 1):
        try:
            d = date(annee, mois, jour)
        except ValueError:
            return None
        if reference - timedelta(days=62) <= d <= reference + timedelta(days=310):
            return d
    return None


def dates_citees(texte: str, reference: date) -> list[date]:
    """Dates écrites dans le texte (« 27 novembre », « 6 novembre 2026 », « 09/12 »), triées, sans doublon."""
    trouvees: set[date] = set()
    t = normaliser_texte(texte)
    for j, m, a in _DATE_LETTRES.findall(t):
        try:
            trouvees.add(date(int(a), MOIS[m], int(j)) if a else _annee(int(j), MOIS[m], reference))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            continue
    for j, m, a in _DATE_CHIFFRES.findall(texte):
        if not (1 <= int(m) <= 12 and 1 <= int(j) <= 31):
            continue
        try:
            if a:
                trouvees.add(date(int(a) + (2000 if len(a) == 2 else 0), int(m), int(j)))
            else:
                d = _annee(int(j), int(m), reference)
                if d:
                    trouvees.add(d)
        except ValueError:
            continue
    for a, m, j in _DATE_ISO.findall(texte):
        try:
            trouvees.add(date(int(a), int(m), int(j)))
        except ValueError:
            continue
    trouvees.discard(None)  # type: ignore[arg-type]
    return sorted(trouvees)


def code_postal(texte: str) -> str | None:
    m = _CODE_POSTAL.search(texte)
    return m.group(1) if m else None


# Enseignes physiques citées dans un message de drop (texte normalisé -> nom affiché).
MAGASINS = {
    "maison de la presse": "Maison de la Presse", "relay": "Relay", "carrefour": "Carrefour",
    "leclerc": "E.Leclerc", "auchan": "Auchan", "intermarche": "Intermarché", "super u": "Super U",
    "hyper u": "Hyper U", "cultura": "Cultura", "fnac": "Fnac", "joueclub": "JouéClub",
    "king jouet": "King Jouet", "la grande recre": "La Grande Récré", "micromania": "Micromania",
    "monoprix": "Monoprix", "casino": "Casino", "cora": "Cora", "lidl": "Lidl", "action": "Action",
    "smyths": "Smyths Toys", "toys r us": "Toys\"R\"Us", "picwic": "Picwic", "boulanger": "Boulanger",
}
_MOTIF_MAGASINS = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(MAGASINS, key=len, reverse=True)) + r")\b")


def magasin_cite(texte: str) -> str | None:
    m = _MOTIF_MAGASINS.search(normaliser_texte(texte))
    return MAGASINS[m.group(1)] if m else None
