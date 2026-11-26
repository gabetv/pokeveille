"""Sources non intégrées automatiquement, faute de méthode d'accès autorisée confirmée.

Ces connecteurs restent désactivés : le bot ne fait ni scraping, ni contournement de CAPTCHA
ou de protection anti-robots. Solution de secours : data/offres_manuelles.csv.
Pour en activer un, implémentez `_rechercher` avec l'API ou le flux produits obtenu
auprès de l'enseigne, et retirez la surcharge de `disponibilite`.
"""

from __future__ import annotations

from .base import ConnecteurNonIntegre

_SECOURS = "En attendant : saisie manuelle dans data/offres_manuelles.csv."


class ConnecteurFnac(ConnecteurNonIntegre):
    id, site, libelle = "fnac", "fnac.com", "Fnac"
    raison = ("non intégré : aucune API publique de recherche produit documentée. À activer uniquement avec "
              "un flux produits ou un programme partenaire autorisé par la Fnac. " + _SECOURS)


class ConnecteurCultura(ConnecteurNonIntegre):
    id, site, libelle = "cultura", "cultura.com", "Cultura"
    raison = ("non intégré : aucune API publique de recherche produit documentée. À activer uniquement avec "
              "un flux produits ou un programme partenaire autorisé par Cultura. " + _SECOURS)


class ConnecteurJoueClub(ConnecteurNonIntegre):
    id, site, libelle = "joueclub", "joueclub.fr", "JouéClub"
    raison = ("non intégré : aucune API publique de recherche produit documentée. À activer uniquement avec "
              "un flux produits ou un programme partenaire autorisé par JouéClub. " + _SECOURS)


class ConnecteurKingJouet(ConnecteurNonIntegre):
    id, site, libelle = "king_jouet", "king-jouet.com", "King Jouet"
    raison = ("non intégré : aucune API publique de recherche produit documentée. À activer uniquement avec "
              "un flux produits ou un programme partenaire autorisé par King Jouet. " + _SECOURS)


class ConnecteurCardmarket(ConnecteurNonIntegre):
    id, site, libelle = "cardmarket", "cardmarket.com", "Cardmarket (marché secondaire)"
    nature = "marche_secondaire"
    raison = ("non intégré : Cardmarket propose une API dont l'accès est soumis à son accord (conditions à "
              "vérifier auprès de Cardmarket). Pas de scraping du site. " + _SECOURS)


class ConnecteurPokemonOfficiel(ConnecteurNonIntegre):
    id, site, libelle = "pokemon_officiel", "pokemon.com/fr", "Pokémon (source officielle)"
    nature = "officiel"
    raison = ("non automatisé : pas d'API produits publique documentée. Le catalogue officiel se tient à la "
              "main dans data/catalogue.csv, avec le lien vers la page pokemon.com/fr de chaque produit.")
