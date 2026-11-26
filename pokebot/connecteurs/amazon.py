"""Connecteur Amazon.fr via l'API officielle « Creators API » (remplace PA-API 5, dépréciée).

Documentation : https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction
- Authentification OAuth 2.0 « client credentials » (Login with Amazon) avec les identifiants
  Credential ID / Credential Secret / Version générés dans Associates Central.
- POST https://creatorsapi.amazon/catalog/v1/searchItems et /getItems, en-tête x-marketplace.
- Quota de départ : 1 requête/seconde et 8 640 requêtes/jour (puis selon vos ventes).
- Conditions : compte Partenaires Amazon actif, ventes qualifiantes requises ; respecter les
  conditions du programme (ne pas modifier les liens detailPageURL, toujours fournir partnerTag).

Limites connues (OffersV2) : pas de frais de livraison ni de note vendeur dans la réponse.
Le bot affiche donc « frais de livraison à vérifier » pour Amazon, sauf barème saisi par vous.

Points à confirmer sur une vraie réponse (la documentation est ambiguë) : nom de l'enveloppe
GetItems (`itemsResult` ou `itemResults`) et structure de `itemInfo.externalIds`.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from ..config import ConfigSource, Parametres
from ..models import Disponibilite, Etat, Offre, TypeVendeur
from ..temps import maintenant
from .base import Connecteur, ErreurSource, Requete

log = logging.getLogger(__name__)

URL_API = "https://creatorsapi.amazon/catalog/v1"
URLS_JETON = {
    "3.1": "https://api.amazon.com/auth/o2/token",  # Amérique du Nord
    "3.2": "https://api.amazon.co.uk/auth/o2/token",  # Europe (dont FR)
    "3.3": "https://api.amazon.co.jp/auth/o2/token",  # Extrême-Orient
}
RESSOURCES = [
    "itemInfo.title",
    "itemInfo.externalIds",
    "offersV2.listings.price",
    "offersV2.listings.merchantInfo",
    "offersV2.listings.availability",
    "offersV2.listings.condition",
    "offersV2.listings.isBuyBoxWinner",
]
DISPOS = {
    "IN_STOCK": Disponibilite.EN_STOCK,
    "IN_STOCK_SCARCE": Disponibilite.EN_STOCK,
    "LEADTIME": Disponibilite.EN_STOCK,
    "PREORDER": Disponibilite.PRECOMMANDE,
    "AVAILABLE_DATE": Disponibilite.PRECOMMANDE,
    "OUT_OF_STOCK": Disponibilite.RUPTURE,
    "UNAVAILABLE": Disponibilite.RUPTURE,
}
ETATS = {"New": Etat.NEUF, "Used": Etat.OCCASION, "Refurbished": Etat.OCCASION}


def _get(d: object, *chemin: str) -> object:
    for cle in chemin:
        if not isinstance(d, dict):
            return None
        d = d.get(cle)
    return d


def _eans(item: dict) -> list[str]:
    ext = _get(item, "itemInfo", "externalIds")
    if not isinstance(ext, dict):
        return []
    for cle in ("eans", "EANs", "ean"):
        bloc = ext.get(cle)
        if isinstance(bloc, dict):
            valeurs = bloc.get("displayValues") or bloc.get("DisplayValues") or []
            return [str(v) for v in valeurs]
    return []


def convertir_items(items: list[dict], marketplace: str = "www.amazon.fr") -> list[Offre]:
    """Transforme les items de la réponse en offres (une offre par listing)."""
    offres: list[Offre] = []
    verifie = maintenant()
    for item in items:
        titre = _get(item, "itemInfo", "title", "displayValue") or ""
        eans = _eans(item)
        listings = _get(item, "offersV2", "listings") or []
        for listing in listings:  # type: ignore[union-attr]
            montant = _get(listing, "price", "money", "amount")
            devise = _get(listing, "price", "money", "currency")
            if montant is None or devise != "EUR":
                continue
            vendeur = _get(listing, "merchantInfo", "name")
            type_vendeur = (
                TypeVendeur.AMAZON if isinstance(vendeur, str) and vendeur.lower().startswith("amazon")
                else TypeVendeur.AMAZON_TIERS
            )
            offres.append(Offre(
                source="amazon_fr",
                site="amazon.fr",
                titre=str(titre),
                url=str(item.get("detailPageURL") or f"https://{marketplace}/dp/{item.get('asin')}"),
                prix=Decimal(str(montant)),
                vendeur=str(vendeur) if vendeur else None,
                type_vendeur=type_vendeur,
                etat=ETATS.get(str(_get(listing, "condition", "value")), Etat.INCONNU),
                disponibilite=DISPOS.get(str(_get(listing, "availability", "type")), Disponibilite.INCONNUE),
                asin=item.get("asin"),
                ean=eans[0] if eans else None,
                verifie_le=verifie,
            ))
    return offres


class ConnecteurAmazon(Connecteur):
    id = "amazon_fr"
    site = "amazon.fr"
    libelle = "Amazon.fr (Creators API officielle)"

    def __init__(self, parametres: Parametres, config: ConfigSource | None = None):
        super().__init__(config or ConfigSource(delai_entre_requetes_secondes=1.1))
        self.p = parametres
        self._jeton: str | None = None
        self._expiration = 0.0

    def disponibilite(self) -> tuple[bool, str]:
        if not self.p.amazon_configure:
            return False, ("non configuré : renseignez AMAZON_CREDENTIAL_ID, AMAZON_CREDENTIAL_SECRET, "
                           "AMAZON_CREDENTIAL_VERSION et AMAZON_PARTNER_TAG dans .env — prix Amazon non vérifié")
        if self.p.amazon_credential_version not in URLS_JETON:
            return False, f"version d'identifiants inconnue : {self.p.amazon_credential_version}"
        return True, "actif (Creators API)"

    def _client(self):
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ErreurSource("le paquet httpx est requis : pip install -r requirements.txt") from exc
        return httpx

    def _obtenir_jeton(self) -> str:
        if self._jeton and time.time() < self._expiration - 60:
            return self._jeton
        httpx = self._client()
        rep = httpx.post(
            URLS_JETON[self.p.amazon_credential_version],  # type: ignore[index]
            json={
                "grant_type": "client_credentials",
                "client_id": self.p.amazon_credential_id,
                "client_secret": self.p.amazon_credential_secret,
                "scope": "creatorsapi::default",
            },
            timeout=15,
        )
        if rep.status_code != 200:
            raise ErreurSource(f"authentification Amazon refusée (HTTP {rep.status_code})")
        donnees = rep.json()
        self._jeton = donnees["access_token"]
        self._expiration = time.time() + int(donnees.get("expires_in", 3600))
        return self._jeton  # type: ignore[return-value]

    def _appeler(self, operation: str, corps: dict) -> dict:
        httpx = self._client()
        for tentative in range(2):
            rep = httpx.post(
                f"{URL_API}/{operation}",
                json=corps,
                headers={
                    "Authorization": f"Bearer {self._obtenir_jeton()}",
                    "Content-Type": "application/json",
                    "x-marketplace": self.p.amazon_marketplace,
                },
                timeout=20,
            )
            if rep.status_code == 401 and tentative == 0:
                self._jeton = None  # jeton expiré : on en redemande un
                continue
            if rep.status_code == 429:
                raise ErreurSource("quota Amazon atteint (HTTP 429) : réessayez plus tard ou espacez les vérifications")
            if rep.status_code >= 400:
                raise ErreurSource(f"erreur Amazon HTTP {rep.status_code} sur {operation}")
            return rep.json()
        raise ErreurSource("authentification Amazon impossible")

    def _rechercher(self, requete: Requete) -> list[Offre]:
        commun = {
            "partnerTag": self.p.amazon_partner_tag,
            "marketplace": self.p.amazon_marketplace,
            "resources": RESSOURCES,
            "languagesOfPreference": ["fr_FR"],
        }
        if requete.asin:
            donnees = self._appeler("getItems", {**commun, "itemIds": [requete.asin], "itemIdType": "ASIN"})
            enveloppe = donnees.get("itemsResult") or donnees.get("itemResults") or {}
        else:
            donnees = self._appeler("searchItems", {
                **commun,
                "keywords": requete.mots_cles,
                "searchIndex": "ToysAndGames",
                "itemCount": 10,
                "condition": "New",
                "availability": "IncludeOutOfStock",
            })
            enveloppe = donnees.get("searchResult") or {}
        return convertir_items(enveloppe.get("items") or [], self.p.amazon_marketplace)
