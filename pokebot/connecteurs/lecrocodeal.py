"""Connecteur Le CrocoDeal (lecrocodeal.com) : bons plans publiés par sa communauté, lus dans son flux RSS.

Accès utilisé : le flux RSS public de recherche WordPress (https://lecrocodeal.com/?s=…&feed=rss2),
un format prévu pour la syndication. Une seule requête par période de cache, avec un User-Agent
identifiable. Les liens de redirection /go/ et /visit/ (interdits par leur robots.txt) ne sont
jamais suivis : le bot renvoie vers l'article du bon plan sur lecrocodeal.com.

Ce qui est repris : titre, lien, date de publication, enseigne citée et prix annoncé dans le texte.
Ce qui ne l'est pas : stock, vendeur exact, frais de livraison. Ces bons plans sont donc des
« signalements » : toujours affichés « à vérifier », jamais utilisés comme référence de prix ni
dans la médiane. Ils déclenchent une alerte dédiée « bon plan signalé ».

Les articles d'information (« Où acheter… ? », dates de sortie) n'ont pas de prix : ils sont ignorés.
"""

from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Callable

from .. import __version__
from ..config import ConfigSource
from ..correspondance import normaliser_gtin
from ..models import Offre, TypeVendeur
from ..texte import jetons, normaliser_texte, similarite
from .base import Connecteur, ErreurSource, Requete

URL_SITE = "https://lecrocodeal.com/"
USER_AGENT = f"PokeVeille/{__version__} (veille de prix personnelle ; lit uniquement le flux RSS)"
SEUIL_PERTINENCE = 0.3

# Enseignes reconnues dans le texte d'un bon plan (texte normalisé, sans accents) -> domaine affiché.
ENSEIGNES = {
    "amazon": "amazon.fr", "fnac": "fnac.com", "cdiscount": "cdiscount.com", "cultura": "cultura.com",
    "joueclub": "joueclub.fr", "king jouet": "king-jouet.com", "leclerc": "e.leclerc",
    "carrefour": "carrefour.fr", "auchan": "auchan.fr", "micromania": "micromania.fr",
    "grande recre": "lagranderecre.fr", "smyths": "smythstoys.com", "philibert": "philibertnet.com",
    "1001hobbies": "1001hobbies.fr", "rakuten": "fr.shopping.rakuten.com", "boulanger": "boulanger.com",
    "darty": "darty.com", "intermarche": "intermarche.com",
}
_MOTIF_ENSEIGNES = re.compile(r"\b(" + "|".join(re.escape(k) for k in ENSEIGNES) + r")\b")

# Articles d'information sans prix de vente (guides « où acheter », annonces de sortie).
_MOTIF_INFO = re.compile(
    r"\bou (acheter|commander|trouver|le commander|les commander|les trouver)\b|date de sortie|"
    r"liens d achat|devoile|informations et liens"
)
_NOMBRE = r"(\d{1,4}(?:[.,]\d{1,2})?)\s?€"
# Prix annoncé : « à 4,68€ », « au prix de 266,93€ », « pour 9,99 € ». Jamais « au lieu de … ».
_MOTIF_PRIX = re.compile(r"(?:\bà|\bau prix de|\bpour)\s+(?:seulement\s+|partir de\s+)?" + _NOMBRE, re.IGNORECASE)
_MOTIF_EAN = re.compile(r"\b0?\d{12,13}\b")
_PREAMBULE = "Ce deal a été publié par un membre de la communauté Le CrocoDeal."


def texte_brut(fragment: str | None) -> str:
    """HTML de la description RSS -> texte simple."""
    sans_balises = re.sub(r"<[^>]+>", " ", fragment or "")
    texte = " ".join(html.unescape(sans_balises).split())
    return texte.replace(_PREAMBULE, "").strip()


def prix_annonce(titre: str, description: str) -> Decimal | None:
    """Prix annoncé dans le titre, sinon dans la description. None si aucun prix clair."""
    for texte in (titre, description):
        m = _MOTIF_PRIX.search(texte)
        if m:
            return Decimal(m.group(1).replace(",", "."))
    return None


def enseigne(texte: str) -> str | None:
    """Domaine de l'enseigne citée, seulement si une seule enseigne est nommée."""
    trouvees = {ENSEIGNES[m.group(1)] for m in _MOTIF_ENSEIGNES.finditer(normaliser_texte(texte))}
    return trouvees.pop() if len(trouvees) == 1 else None


def est_article_information(titre: str) -> bool:
    return bool(_MOTIF_INFO.search(normaliser_texte(titre)))


def lire_flux(contenu: bytes, age_max: timedelta | None = None, maintenant: datetime | None = None) -> list[Offre]:
    """Transforme le flux RSS en signalements (un par bon plan comportant un prix)."""
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError as exc:
        raise ErreurSource("flux Le CrocoDeal illisible (XML invalide)") from exc
    instant = maintenant or datetime.now(timezone.utc)
    offres: list[Offre] = []
    for item in racine.findall("./channel/item"):
        titre = html.unescape(item.findtext("title") or "").strip()
        lien = (item.findtext("link") or "").strip()
        if not titre or not lien.startswith(URL_SITE) or est_article_information(titre):
            continue
        try:
            publie = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue  # sans date, impossible de savoir si le bon plan est encore d'actualité
        if publie.tzinfo is None:
            publie = publie.replace(tzinfo=timezone.utc)
        if age_max is not None and instant - publie > age_max:
            continue
        description = texte_brut(item.findtext("description"))
        prix = prix_annonce(titre, description)
        if prix is None:
            continue
        site = enseigne(f"{titre} {description}")
        eans = [e for e in _MOTIF_EAN.findall(description) if normaliser_gtin(e)]
        offres.append(Offre(
            source="lecrocodeal",
            site=site or "lecrocodeal.com",
            titre=titre,
            url=lien,
            prix=prix,
            vendeur=None,  # l'enseigne est citée par la communauté, le vendeur exact n'est pas confirmé
            type_vendeur=TypeVendeur.INCONNU,
            description=description[:600],
            ean=eans[0] if len(set(eans)) == 1 else None,
            verifie_le=publie,
            signalement=True,
        ))
    return offres


def _telecharger(terme: str) -> bytes:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise ErreurSource("le paquet httpx est requis : pip install -r requirements.txt") from exc
    try:
        rep = httpx.get(
            URL_SITE,
            params={"s": terme, "feed": "rss2", "orderby": "date", "order": "DESC"},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise ErreurSource(f"Le CrocoDeal injoignable ({type(exc).__name__})") from exc
    if rep.status_code == 429:
        raise ErreurSource("Le CrocoDeal limite les requêtes (HTTP 429) : augmentez cache_secondes")
    if rep.status_code != 200 or "xml" not in rep.headers.get("content-type", ""):
        raise ErreurSource(f"flux Le CrocoDeal indisponible (HTTP {rep.status_code})")
    return rep.content


class ConnecteurCrocoDeal(Connecteur):
    id = "lecrocodeal"
    site = "*"  # couvre plusieurs enseignes (celle citée dans chaque bon plan)
    libelle = "Le CrocoDeal (bons plans communautaires, flux RSS)"
    nature = "signalement"

    def __init__(self, config: ConfigSource | None = None, telecharger: Callable[[str], bytes] | None = None):
        super().__init__(config or ConfigSource(delai_entre_requetes_secondes=5, cache_secondes=1800))
        self.telecharger = telecharger or _telecharger
        self._flux: tuple[float, list[Offre]] | None = None

    @property
    def terme(self) -> str:
        return self.config.recherche or "pokemon"

    def disponibilite(self) -> tuple[bool, str]:
        age = f", bons plans de moins de {self.config.age_max_jours} jours" if self.config.age_max_jours else ""
        return True, f"actif — flux RSS « {self.terme} »{age} ; prix communautaires, toujours à vérifier"

    def _signalements(self) -> list[Offre]:
        """Le flux est téléchargé une fois par période de cache, quel que soit le nombre de produits suivis."""
        if self._flux and time.monotonic() - self._flux[0] < self.config.cache_secondes:
            return self._flux[1]
        age = timedelta(days=self.config.age_max_jours) if self.config.age_max_jours else None
        offres = lire_flux(self.telecharger(self.terme), age_max=age)
        self._flux = (time.monotonic(), offres)
        return offres

    def _rechercher(self, requete: Requete) -> list[Offre]:
        ean = normaliser_gtin(requete.ean) if requete.ean else None
        return [o for o in self._signalements() if pertinent(o, requete.mots_cles, ean)]


def pertinent(offre: Offre, mots_cles: str, ean: str | None = None) -> bool:
    """Même EAN, titre proche, ou titre qui contient tous les mots cherchés (titres de bons plans souvent longs)."""
    if ean and normaliser_gtin(offre.ean) == ean:
        return True
    cherches = set(jetons(mots_cles))
    return similarite(mots_cles, offre.titre) >= SEUIL_PERTINENCE or (
        bool(cherches) and cherches <= set(jetons(offre.titre))
    )
