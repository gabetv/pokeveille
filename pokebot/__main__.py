"""Ligne de commande : py -m pokebot <commande>

  demo                      affiche la gamme anniversaire puis une fiche détaillée (mode démo forcé)
  anniversaire              résumé des produits de la gamme 30e anniversaire
  recherche <mots-clés>     recherche un produit et affiche le comparatif
  fiche <id>                comparatif détaillé d'un produit
  alerte-test <id> <prix>   simule deux vérifications d'alerte successives
  sources                   état des sources de prix
  sorties                   lit la veille (Poképédia, Le CrocoDeal, Fnac) et affiche le calendrier des sorties
  drops [id]                arrivages signalés récemment
  tache [--sans-envoi]      version site + webhook : veille, prix, envoi Discord, génération du site
  bot                       lance le bot Discord
Option --demo pour forcer le mode démo quel que soit BOT_MODE.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .affichage import (
    formater_notification, formater_offres_libres, formater_rapport, formater_resume,
)
from .alertes import EtatAlerte, evaluer_alerte
from .base import BaseDonnees
from .comparateur import Comparateur
from .config import Parametres
from .models import parser_decimal


def _console_utf8() -> None:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _console_utf8()
    parser = argparse.ArgumentParser(prog="pokebot", description="PokéVeille 30 — comparateur de prix Pokémon")
    parser.add_argument("--demo", action="store_true", help="forcer le mode démo (données fictives)")
    parser.add_argument("-v", "--verbeux", action="store_true")
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("demo")
    sous.add_parser("anniversaire")
    sous.add_parser("sources")
    sous.add_parser("bot")
    sous.add_parser("sorties")
    p_drops = sous.add_parser("drops")
    p_drops.add_argument("id", nargs="?")
    p_tache = sous.add_parser("tache")
    p_tache.add_argument("--sans-envoi", action="store_true", help="ne rien poster sur Discord")
    p_tache.add_argument("--dossier", default="site", help="dossier du site généré (défaut : site)")
    p_rech = sous.add_parser("recherche")
    p_rech.add_argument("mots", nargs="+")
    p_fiche = sous.add_parser("fiche")
    p_fiche.add_argument("id")
    p_alerte = sous.add_parser("alerte-test")
    p_alerte.add_argument("id")
    p_alerte.add_argument("prix")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbeux else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    forcer_demo = args.demo or args.commande in ("demo", "alerte-test")
    parametres = Parametres.charger(mode="demo" if forcer_demo else None)

    if args.commande == "bot":
        from .discord_bot import lancer  # import tardif : discord.py n'est requis que pour le bot

        lancer(parametres)
        return 0

    if args.commande == "tache":
        import os
        from pathlib import Path

        from .config import RACINE
        from .tache import executer
        from .webhook import Webhook

        # Base séparée de celle du bot Discord : l'abonné n°0 (le salon du webhook) n'y existe pas.
        if not os.environ.get("CHEMIN_BASE"):
            parametres.chemin_db = RACINE / "data" / ("pokeveille_site_demo.sqlite3" if parametres.demo
                                                      else "pokeveille_site.sqlite3")
        base = BaseDonnees(parametres.chemin_db)
        comp = Comparateur(parametres, base=base)
        dossier = Path(args.dossier)
        bilan = executer(parametres, comp, base, Webhook(os.environ.get("DISCORD_WEBHOOK_URL")),
                         dossier if dossier.is_absolute() else RACINE / dossier, envoyer=not args.sans_envoi)
        print(f"Site généré dans {args.dossier}/ ({len(bilan.rapports)} produit(s)). "
              f"{len(bilan.messages)} notification(s), {bilan.envoyes} envoyée(s) sur Discord.")
        for source, err in bilan.erreurs.items():
            print(f"⚠️ {source} : {err}")
        if args.sans_envoi:
            for m in bilan.messages:
                print("\n" + m)
        return 0

    base = BaseDonnees(parametres.chemin_db)
    comp = Comparateur(parametres, base=base)
    max_offres = parametres.max_offres_par_produit

    if args.commande == "sources":
        print(f"Mode : {parametres.mode}")
        for c in comp.connecteurs:
            print(f"{'[actif]  ' if c.actif else '[inactif]'} {c.libelle} — {c.statut()}")
        return 0

    if args.commande in ("sorties", "drops"):
        from .affichage_veille import formater_annonce, formater_drops, formater_sorties
        from .service_veille import ServiceVeille

        veille = ServiceVeille(parametres, comp, base)
        catalogue = {p.id: p for p in comp.catalogue}
        if args.commande == "drops":
            cible = comp.produit(args.id) if args.id else None
            liste, stats = veille.drops(cible)
            print(formater_drops(liste, stats, catalogue, cible, markdown=False))
            return 0
        envois = veille.actualiser()
        print(formater_sorties(veille.sorties(), veille.erreurs, markdown=False, demo=parametres.demo))
        if envois:
            # La console ne peut pas les livrer : on les affiche (le bot ne les renverra pas).
            print(f"\n{len(envois)} notification(s) de veille (affichées ici, non envoyées sur Discord) :")
            for e in envois:
                produits = [catalogue[pid] for pid in e.annonce.produit_ids if pid in catalogue]
                print(f"\n→ membre {e.utilisateur_id}\n" + formater_annonce(e.annonce, produits, markdown=False))
        return 0

    if args.commande in ("demo", "anniversaire"):
        rapports = [comp.rapport(p) for p in comp.produits_anniversaire()]
        print(formater_resume(rapports, markdown=False, titre="Gamme 30e anniversaire — produits repérés"))
        if args.commande == "demo" and rapports:
            print("\n" + "=" * 70 + "\nExemple de fiche détaillée :\n")
            print(formater_rapport(rapports[0], markdown=False, max_offres=max_offres))
        return 0

    if args.commande == "fiche":
        produit = comp.produit(args.id)
        if not produit:
            print(f"Produit inconnu : {args.id}")
            return 1
        print(formater_rapport(comp.rapport(produit), markdown=False, max_offres=max_offres))
        return 0

    if args.commande == "recherche":
        texte = " ".join(args.mots)
        produits = comp.chercher_dans_catalogue(texte)
        if not produits:
            offres, _ = comp.recherche_libre(texte)
            print(formater_offres_libres(offres, markdown=False, demo=parametres.demo))
            return 0
        for p in produits:
            print(formater_rapport(comp.rapport(p), markdown=False, max_offres=max_offres))
            print("\n" + "-" * 70 + "\n")
        return 0

    if args.commande == "alerte-test":
        produit = comp.produit(args.id)
        prix = parser_decimal(args.prix)
        if not produit or prix is None:
            print("Utilisation : alerte-test <id> <prix>")
            return 1
        etat = EtatAlerte()
        for tour in (1, 2):
            rapport = comp.rapport(produit)
            notifications, etat = evaluer_alerte(rapport, prix, etat)
            print(f"--- Vérification n°{tour} : {len(notifications)} notification(s)")
            for n in notifications:
                print(formater_notification(n, rapport, prix, markdown=False) + "\n")
        print("(La 2e vérification ne renvoie rien si le prix n'a pas encore baissé : pas de notification en double.)")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
