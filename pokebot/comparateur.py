"""Service principal : catalogue + connecteurs + analyse + historique."""

from __future__ import annotations

import logging
from decimal import Decimal

from .analyse import Rapport, construire_rapport
from .base import BaseDonnees
from .config import ConfigSource, Parametres
from .connecteurs import Connecteur, ErreurSource, Requete, construire_connecteurs
from .csv_io import lire_catalogue
from .models import Offre, Preferences, Produit, StatutLivraison
from .texte import normaliser_texte

log = logging.getLogger(__name__)


def appliquer_bareme(offre: Offre, config: ConfigSource) -> None:
    """Livraison inconnue + barème saisi par l'utilisateur => livraison « estimée » (jamais « connue »)."""
    if offre.statut_livraison is not StatutLivraison.INCONNUE or offre.prix is None:
        return
    if config.livraison_gratuite_des is not None and offre.prix >= config.livraison_gratuite_des:
        offre.livraison, offre.statut_livraison = Decimal("0"), StatutLivraison.ESTIMEE
    elif config.livraison_estimee is not None:
        offre.livraison, offre.statut_livraison = config.livraison_estimee, StatutLivraison.ESTIMEE


class Comparateur:
    def __init__(
        self,
        parametres: Parametres,
        connecteurs: list[Connecteur] | None = None,
        catalogue: list[Produit] | None = None,
        base: BaseDonnees | None = None,
    ):
        self.p = parametres
        self.connecteurs = connecteurs if connecteurs is not None else construire_connecteurs(parametres)
        if catalogue is None:
            chemin = parametres.chemin_catalogue_demo if parametres.demo else parametres.chemin_catalogue
            catalogue = lire_catalogue(chemin, demo=parametres.demo)
        self.catalogue = catalogue
        self.base = base

    # --- Catalogue ---------------------------------------------------------
    def produit(self, identifiant: str) -> Produit | None:
        return next((p for p in self.catalogue if p.id.lower() == identifiant.strip().lower()), None)

    def chercher_dans_catalogue(self, texte: str, categorie: str | None = None) -> list[Produit]:
        texte = texte.strip()
        exact = self.produit(texte)
        if exact:
            return [exact]
        mots = normaliser_texte(texte).split()
        resultats = []
        for p in self.catalogue:
            if categorie and normaliser_texte(categorie) not in normaliser_texte(p.categorie):
                continue
            if texte and (texte == p.ean or texte.upper() == (p.asin or "").upper()):
                resultats.append(p)
                continue
            botte = normaliser_texte(f"{p.nom} {p.categorie} {p.mots_cles} {p.gamme}")
            if mots and all(m in botte.split() or m in botte for m in mots):
                resultats.append(p)
        return resultats

    def produits_anniversaire(self, categorie: str | None = None) -> list[Produit]:
        return [
            p for p in self.catalogue
            if "anniversaire" in normaliser_texte(p.gamme)
            and (not categorie or normaliser_texte(categorie) in normaliser_texte(p.categorie))
        ]

    # --- Sources -------------------------------------------------------------
    def connecteurs_actifs(self) -> list[Connecteur]:
        return [c for c in self.connecteurs if c.actif]

    def statut_amazon(self, erreurs: dict[str, str] | None = None) -> str:
        if self.p.demo:
            return "mode démo : prix Amazon FICTIFS, aucune donnée réelle"
        if erreurs and "amazon.fr" in erreurs:
            return f"prix Amazon non vérifié : {erreurs['amazon.fr']}"
        amazon = next((c for c in self.connecteurs if c.id == "amazon_fr"), None)
        if amazon is None or not amazon.actif:
            return "prix Amazon non vérifié : accès à la Creators API non configuré"
        return "prix Amazon vérifié via la Creators API officielle"

    def _collecter(self, requete: Requete, sites: list[str] | None) -> tuple[list[Offre], dict[str, str]]:
        offres: list[Offre] = []
        erreurs: dict[str, str] = {}
        for c in self.connecteurs_actifs():
            if sites and c.site != "*" and c.site not in sites:
                continue
            cle = c.site if c.site != "*" else c.id  # une source multi-sites est nommée par son identifiant
            try:
                trouvees = c.rechercher(requete)
            except ErreurSource as exc:
                erreurs[cle] = str(exc)
                continue
            except Exception as exc:  # une source en panne ne doit pas bloquer les autres
                log.exception("Erreur du connecteur %s", c.id)
                erreurs[cle] = f"erreur inattendue ({type(exc).__name__})"
                continue
            for o in trouvees:
                appliquer_bareme(o, self.p.source(o.source))
            offres.extend(trouvees)
        if sites:
            offres = [o for o in offres if o.site in sites]
        return offres, erreurs

    def rapport(self, produit: Produit, preferences: Preferences | None = None) -> Rapport:
        requete = Requete(
            mots_cles=produit.nom, ean=produit.ean, asin=produit.asin,
            ref_fabricant=produit.ref_fabricant, code_postal=self.p.code_postal,
        )
        # Toutes les sources sont interrogées : la référence Amazon et la médiane portent sur tout le marché.
        offres, erreurs = self._collecter(requete, None)
        rapport = construire_rapport(
            produit, offres, self.p.seuils, preferences,
            statut_amazon=self.statut_amazon(erreurs),
            statuts_sources=erreurs,
            demo=self.p.demo,
        )
        if self.base is not None:
            self.base.enregistrer_rapport(rapport)
        if preferences and preferences.sites:
            # Le choix des sites ne filtre que les offres affichées et alertées.
            rapport.lignes = [l for l in rapport.lignes if l.offre.site in preferences.sites]
            rapport.ventes_reelles = [l for l in rapport.ventes_reelles if l.offre.site in preferences.sites]
        return rapport

    def recherche_libre(self, texte: str, sites: list[str] | None = None) -> tuple[list[Offre], dict[str, str]]:
        """Recherche sans produit de référence : toutes les correspondances restent « à vérifier »."""
        return self._collecter(Requete(mots_cles=texte, code_postal=self.p.code_postal), sites)
