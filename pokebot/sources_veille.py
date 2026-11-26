"""Sources de la veille des sorties : calendrier Poképédia et flux RSS d'annonces.

- Poképédia (pokepedia.fr) : API MediaWiki publique. Le bot lit l'infobox « Produit JCC » des pages
  produits (champ date-france et EAN). Contenu sous licence CC BY-NC-SA 3.0 : la source est toujours
  citée et le bot reste un usage personnel, non commercial. Une lecture toutes les 12 h par défaut.
- Le CrocoDeal : articles « Où acheter… ? » / dates de sortie du flux RSS public (les bons plans avec
  prix sont lus par le connecteur de prix).
- Fnac — L'Éclaireur (leclaireur.fnac.com) : flux RSS du blog, filtré sur « Pokémon » (ventes
  spéciales, tirages au sort Fnac+, dates de mise en vente).

Les dates lues sont des dates ANNONCÉES : elles changent souvent (reports). Le bot les affiche avec
leur source et signale les changements, sans jamais les présenter comme une garantie de stock.
"""

from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote

from . import __version__
from .config import ConfigSource
from .connecteurs.base import ErreurSource
from .connecteurs.lecrocodeal import est_article_information, texte_brut
from .correspondance import normaliser_gtin
from .models import Produit
from .veille import INFO, Annonce, DateSortie, dates_citees, produits_cites

USER_AGENT = f"PokeVeille/{__version__} (veille personnelle des sorties Pokemon ; usage non commercial)"  # ASCII
API_POKEPEDIA = "https://www.pokepedia.fr/api.php"
URL_POKEPEDIA = "https://www.pokepedia.fr/"
MODELE_PRODUIT = "Modèle:Infobox Produit JCC"


def telecharger(url: str, params: dict | None = None) -> bytes:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise ErreurSource("le paquet httpx est requis : pip install -r requirements.txt") from exc
    try:
        rep = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=25, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise ErreurSource(f"{url.split('/')[2]} injoignable ({type(exc).__name__})") from exc
    if rep.status_code != 200:
        raise ErreurSource(f"{url.split('/')[2]} indisponible (HTTP {rep.status_code})")
    return rep.content


class _AvecCache:
    def __init__(self, config: ConfigSource):
        self.config = config
        self._cache: tuple[float, object] | None = None

    def _en_cache(self, calcul: Callable[[], object]) -> object:
        if self._cache and time.monotonic() - self._cache[0] < self.config.cache_secondes:
            return self._cache[1]
        valeur = calcul()
        self._cache = (time.monotonic(), valeur)
        return valeur


# --- Poképédia ----------------------------------------------------------------------------------
def lire_infobox(wikitexte: str, reference: date) -> tuple[date | None, str | None]:
    """(date de sortie en France, EAN) lus dans l'infobox « Produit JCC »."""
    sortie = None
    ligne = re.search(r"\|\s*date-france\s*=([^\n]*)", wikitexte)
    if ligne:
        iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", ligne.group(1))
        if iso:
            try:
                sortie = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            except ValueError:
                sortie = None
        else:
            dates = dates_citees(ligne.group(1), reference)
            sortie = dates[0] if dates else None
    ean = re.search(r"\|\s*EAN\s*=\s*(\d{12,14})", wikitexte)
    return sortie, (normaliser_gtin(ean.group(1)) and ean.group(1)) if ean else None


class CalendrierPokepedia(_AvecCache):
    id = "pokepedia"
    libelle = "Poképédia (dates de sortie en France, API MediaWiki, CC BY-NC-SA)"

    def __init__(self, config: ConfigSource | None = None, get: Callable[[str, dict], bytes] | None = None):
        super().__init__(config or ConfigSource(cache_secondes=43200))
        self.get = get or telecharger

    def _api(self, **params) -> dict:
        params = {"format": "json", "formatversion": 2, "maxlag": 5, **params}
        donnees = json.loads(self.get(API_POKEPEDIA, params))
        if "error" in donnees:
            raise ErreurSource(f"Poképédia : {donnees['error'].get('info', 'erreur API')}")
        return donnees

    def _titres(self) -> list[str]:
        titres, suite = [], {}
        while True:
            d = self._api(action="query", list="embeddedin", eititle=MODELE_PRODUIT, einamespace=0, eilimit=500, **suite)
            titres += [x["title"] for x in d["query"]["embeddedin"]]
            if "continue" not in d:
                return titres
            suite = d["continue"]

    def _calculer(self, catalogue: list[Produit]) -> list[DateSortie]:
        par_ean = {normaliser_gtin(p.ean): p for p in catalogue if p.ean and normaliser_gtin(p.ean)}
        utiles = [t for t in self._titres() if produits_cites(t, catalogue)]
        resultats: list[DateSortie] = []
        aujourd_hui = datetime.now(timezone.utc).date()
        for i in range(0, len(utiles), 50):
            d = self._api(action="query", prop="revisions", rvprop="content", rvslots="main",
                          titles="|".join(utiles[i:i + 50]))
            for page in d["query"].get("pages", []):
                revs = page.get("revisions") or []
                if not revs:
                    continue
                sortie, ean = lire_infobox(revs[0]["slots"]["main"]["content"], aujourd_hui)
                if sortie is None:
                    continue
                cibles = {p.id: p for p in produits_cites(page["title"], catalogue)}
                if ean and normaliser_gtin(ean) in par_ean:
                    p = par_ean[normaliser_gtin(ean)]
                    cibles.setdefault(p.id, p)
                url = URL_POKEPEDIA + quote(page["title"].replace(" ", "_"))
                resultats += [DateSortie(pid, sortie, self.id, url, page["title"]) for pid in cibles]
        return resultats

    def dates(self, catalogue: list[Produit]) -> list[DateSortie]:
        if not self.config.actif:
            return []
        return self._en_cache(lambda: self._calculer(catalogue))  # type: ignore[return-value]


# --- Flux RSS d'annonces -------------------------------------------------------------------------
def lire_annonces_rss(
    contenu: bytes, source: str, catalogue: list[Produit], garder: Callable[[str, str], bool],
    age_max: timedelta | None = None, maintenant: datetime | None = None,
) -> list[Annonce]:
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError as exc:
        raise ErreurSource(f"flux {source} illisible (XML invalide)") from exc
    instant = maintenant or datetime.now(timezone.utc)
    annonces = []
    for item in racine.findall("./channel/item"):
        titre = html.unescape(item.findtext("title") or "").strip()
        lien = (item.findtext("link") or "").strip()
        try:
            publie = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if publie.tzinfo is None:
            publie = publie.replace(tzinfo=timezone.utc)
        if not titre or not lien or (age_max and instant - publie > age_max):
            continue
        texte = texte_brut(item.findtext("description"))
        if not garder(titre, texte):
            continue
        annonces.append(Annonce(
            source=source, cle=lien, type=INFO, titre=titre, url=lien, publie_le=publie, texte=texte[:500],
            dates=dates_citees(f"{titre} {texte}", publie.date()),
            # Produits reconnus dans le TITRE seulement : les résumés citent souvent d'autres produits.
            produit_ids=[p.id for p in produits_cites(titre, catalogue)],
        ))
    return annonces


class FluxAnnonces(_AvecCache):
    def __init__(
        self, id: str, libelle: str, url: str, garder: Callable[[str, str], bool],
        params: dict | None = None, config: ConfigSource | None = None,
        get: Callable[[str, dict | None], bytes] | None = None,
    ):
        super().__init__(config or ConfigSource(cache_secondes=1800))
        self.id, self.libelle, self.url, self.params, self.garder = id, libelle, url, params, garder
        self.get = get or telecharger

    def annonces(self, catalogue: list[Produit]) -> list[Annonce]:
        if not self.config.actif:
            return []
        brut = self._en_cache(lambda: self.get(self.url, self.params))
        age = timedelta(days=self.config.age_max_jours) if self.config.age_max_jours else None
        return lire_annonces_rss(brut, self.id, catalogue, self.garder, age_max=age)  # type: ignore[arg-type]


_POKEMON = re.compile(r"pok[eé]mon", re.IGNORECASE)


def flux_crocodeal(config: ConfigSource | None = None, get=None) -> FluxAnnonces:
    terme = (config.recherche if config and config.recherche else None) or "pokemon"
    if config is not None:
        # La limite d'âge des bons plans ne s'applique pas aux guides « où acheter », mis à jour longtemps.
        config = replace(config, age_max_jours=None, cache_secondes=max(config.cache_secondes, 1800))
    return FluxAnnonces(
        "lecrocodeal", "Le CrocoDeal — articles « où acheter » et dates de sortie (flux RSS)",
        "https://lecrocodeal.com/", lambda titre, _texte: est_article_information(titre),
        params={"s": terme, "feed": "rss2", "orderby": "date", "order": "DESC"}, config=config, get=get,
    )


def flux_fnac_eclaireur(config: ConfigSource | None = None, get=None) -> FluxAnnonces:
    return FluxAnnonces(
        "fnac_eclaireur", "Fnac — blog L'Éclaireur, articles Pokémon (flux RSS)",
        "https://leclaireur.fnac.com/feed/", lambda titre, texte: bool(_POKEMON.search(f"{titre} {texte}")),
        config=config, get=get,
    )
