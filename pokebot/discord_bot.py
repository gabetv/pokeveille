"""Bot Discord en français (discord.py 2.x, commandes slash).

Les commandes qui touchent à vos données (préférences, alertes, favoris) répondent en message
éphémère : seul l'auteur de la commande les voit. Les alertes sont envoyées en message privé,
ou à défaut dans le salon où l'alerte a été créée.
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import tasks

from .affichage import (
    BANNIERE_DEMO, LIMITE_DISCORD, decouper, euros, formater_notification, formater_offres_libres,
    formater_rapport, formater_resume,
)
from .affichage_veille import formater_annonce, formater_drops, formater_sorties
from .alertes import evaluer_alerte
from .base import AlerteEnregistree, BaseDonnees
from .comparateur import Comparateur
from .config import Parametres
from .models import NOMS_LANGUES, Etat, Preferences, etat_depuis, normaliser_langue, parser_decimal
from .service_veille import Envoi, ServiceVeille

log = logging.getLogger(__name__)
MAX_FICHES_DETAILLEES = 2

AIDE = """**PokéVeille 30** — veille et comparaison de prix des produits Pokémon du 30e anniversaire (marché français, référence Amazon.fr).

**Commandes**
`/recherche mot_cle:coffret` — rechercher un produit
`/anniversaire` — produits repérés de la gamme 30e anniversaire
`/fiche produit:…` — comparatif détaillé d'un produit
`/alerte produit:… prix_max:49,90` — alerte de prix (baisse sous le prix max, retour en stock, bon plan Le CrocoDeal)
`/alertes` · `/supprimer_alerte numero:…` — vos alertes
`/suivre` · `/retirer` · `/favoris` — produits suivis
`/sorties` — calendrier des sorties (dates annoncées, reports)
`/drop produit:… magasin:… ville:…` — signaler un arrivage en magasin · `/drops` — arrivages récents
`/preferences` — prix max, catégorie, état, langue, sites, fréquence (« aucun » pour retirer un réglage)
`/sources` — état des sources de prix et de la veille
`/oubliermoi` — effacer vos préférences, favoris et alertes

**Avis du bot** : 🟢 très bonne affaire · 🔵 prix raisonnable · 🟠 un peu cher · 🔴 cher · ⚠️ à vérifier · ⚪ comparaison insuffisante.
**Veille** : pour un produit en alerte ou en favori, vous êtes prévenu des reports de date 📅, de la veille d'une sortie ⏰, des articles « où acheter » 📰 et des arrivages signalés 🏬.
Le bot n'achète jamais rien et ne demande jamais vos coordonnées bancaires."""


@dataclass
class Contexte:
    parametres: Parametres
    comparateur: Comparateur
    base: BaseDonnees
    veille: ServiceVeille | None = None

    def __post_init__(self):
        if self.veille is None:
            self.veille = ServiceVeille(self.parametres, self.comparateur, self.base)


async def repondre(interaction: discord.Interaction, texte: str, ephemere: bool = False) -> None:
    """Envoie un texte éventuellement long (découpé en messages de moins de 2 000 caractères)."""
    for morceau in decouper(texte, LIMITE_DISCORD):
        if interaction.response.is_done():
            await interaction.followup.send(morceau, ephemeral=ephemere, suppress_embeds=True)
        else:
            await interaction.response.send_message(morceau, ephemeral=ephemere, suppress_embeds=True)


def enregistrer_commandes(tree: app_commands.CommandTree, c: Contexte) -> dict[str, app_commands.Command]:
    p = c.parametres

    async def autorise(interaction: discord.Interaction) -> bool:
        if p.utilisateurs_autorises and interaction.user.id not in p.utilisateurs_autorises:
            await interaction.response.send_message("Accès non autorisé pour ce compte.", ephemeral=True)
            return False
        return True

    async def auto_produit(interaction: discord.Interaction, saisie: str) -> list[app_commands.Choice[str]]:
        produits = c.comparateur.chercher_dans_catalogue(saisie) if saisie.strip() else c.comparateur.catalogue
        return [app_commands.Choice(name=f"{pr.nom} ({pr.id})"[:100], value=pr.id) for pr in produits[:25]]

    async def rapports(produits, prefs):
        return [await asyncio.to_thread(c.comparateur.rapport, pr, prefs) for pr in produits]

    @tree.command(name="aide", description="Liste des commandes et explication des avis")
    async def aide(interaction: discord.Interaction):
        if await autorise(interaction):
            banniere = f"**{BANNIERE_DEMO}**\n\n" if p.demo else ""
            await repondre(interaction, banniere + AIDE, ephemere=True)

    @tree.command(name="recherche", description="Rechercher un produit Pokémon et comparer ses prix")
    @app_commands.describe(mot_cle="Nom, catégorie, EAN ou identifiant (ex. coffret, booster, pikachu)")
    async def recherche(interaction: discord.Interaction, mot_cle: str):
        if not await autorise(interaction):
            return
        await interaction.response.defer(thinking=True)
        prefs = c.base.preferences(interaction.user.id)
        produits = c.comparateur.chercher_dans_catalogue(mot_cle, prefs.categorie)
        if not produits:
            offres, _ = await asyncio.to_thread(c.comparateur.recherche_libre, mot_cle, prefs.sites or None)
            await repondre(interaction, formater_offres_libres(offres, demo=p.demo))
            return
        liste = await rapports(produits, prefs)
        if len(liste) <= MAX_FICHES_DETAILLEES:
            texte = "\n\n".join(formater_rapport(r, max_offres=p.max_offres_par_produit, preferences=prefs) for r in liste)
        else:
            texte = formater_resume(liste, titre=f"{len(liste)} produits trouvés pour « {mot_cle} »")
        await repondre(interaction, texte)

    @tree.command(name="anniversaire", description="Produits repérés de la gamme 30e anniversaire")
    async def anniversaire(interaction: discord.Interaction):
        if not await autorise(interaction):
            return
        prefs = c.base.preferences(interaction.user.id)
        produits = c.comparateur.produits_anniversaire(prefs.categorie)
        if not produits:
            msg = "Aucun produit de la gamme 30e anniversaire dans le catalogue."
            if not p.demo:
                msg += " Ajoutez les produits vérifiés sur pokemon.com/fr dans `data/catalogue.csv`."
            await repondre(interaction, msg)
            return
        await interaction.response.defer(thinking=True)
        liste = await rapports(produits, prefs)
        await repondre(interaction, formater_resume(liste, titre="Gamme 30e anniversaire — produits repérés"))

    @tree.command(name="fiche", description="Comparatif détaillé d'un produit")
    @app_commands.describe(produit="Produit du catalogue")
    @app_commands.autocomplete(produit=auto_produit)
    async def fiche(interaction: discord.Interaction, produit: str):
        if not await autorise(interaction):
            return
        trouve = c.comparateur.produit(produit)
        if not trouve:
            await repondre(interaction, "Produit inconnu. Choisissez-le dans la liste proposée.", ephemere=True)
            return
        await interaction.response.defer(thinking=True)
        prefs = c.base.preferences(interaction.user.id)
        rapport = await asyncio.to_thread(c.comparateur.rapport, trouve, prefs)
        await repondre(interaction, formater_rapport(rapport, max_offres=p.max_offres_par_produit, preferences=prefs))

    @tree.command(name="alerte", description="Être prévenu quand un produit passe sous un prix ou revient en stock")
    @app_commands.describe(produit="Produit du catalogue", prix_max="Prix total maximum en euros, ex. 49,90")
    @app_commands.autocomplete(produit=auto_produit)
    async def alerte(interaction: discord.Interaction, produit: str, prix_max: str):
        if not await autorise(interaction):
            return
        try:
            seuil = parser_decimal(prix_max)
        except ValueError:
            seuil = None
        if seuil is None or seuil <= 0:
            await repondre(interaction, "Prix maximum invalide. Exemple : `49,90`.", ephemere=True)
            return
        trouves = [c.comparateur.produit(produit)] if c.comparateur.produit(produit) else c.comparateur.chercher_dans_catalogue(produit)
        if len(trouves) != 1:
            if not trouves:
                msg = "Aucun produit trouvé. Choisissez-le dans la liste proposée."
            else:
                msg = "Plusieurs produits correspondent :\n" + "\n".join(f"• `{pr.id}` — {pr.nom}" for pr in trouves)
            await repondre(interaction, msg, ephemere=True)
            return
        cible = trouves[0]
        uid = interaction.user.id
        prefs = c.base.preferences(uid)
        frequence = max(prefs.frequence_minutes or p.frequence_defaut_minutes, p.frequence_min_minutes)
        numero = c.base.creer_alerte(uid, cible.id, seuil, frequence, prefs.etat or Etat.NEUF,
                                     prefs.langue or cible.langue, prefs.sites, salon_id=interaction.channel_id)
        c.base.ajouter_favori(uid, cible.id)
        await repondre(interaction, (
            f"✅ Alerte n°{numero} créée : **{cible.nom}** à {euros(seuil)} maximum "
            f"(livraison comprise quand elle est connue).\nVérification toutes les {frequence} min. "
            "Vous serez prévenu en message privé si le prix passe sous ce seuil ou si le produit revient en stock."
        ), ephemere=True)

    @tree.command(name="alertes", description="Lister vos alertes")
    async def alertes(interaction: discord.Interaction):
        if not await autorise(interaction):
            return
        liste = c.base.alertes(interaction.user.id)
        if not liste:
            await repondre(interaction, "Aucune alerte. Créez-en une avec `/alerte`.", ephemere=True)
            return
        lignes = ["**Vos alertes**"]
        for a in liste:
            pr = c.comparateur.produit(a.produit_id)
            lignes.append(f"n°{a.id} — {pr.nom if pr else a.produit_id} ≤ {euros(a.prix_max)} · toutes les {a.frequence_minutes} min")
        lignes.append("Supprimer : `/supprimer_alerte numero:<n°>`")
        await repondre(interaction, "\n".join(lignes), ephemere=True)

    @tree.command(name="supprimer_alerte", description="Supprimer une de vos alertes")
    @app_commands.describe(numero="Numéro de l'alerte (voir /alertes)")
    async def supprimer_alerte(interaction: discord.Interaction, numero: int):
        if await autorise(interaction):
            ok = c.base.supprimer_alerte(interaction.user.id, numero)
            await repondre(interaction, "Alerte supprimée." if ok else "Alerte introuvable.", ephemere=True)

    @tree.command(name="suivre", description="Ajouter un produit à vos favoris")
    @app_commands.autocomplete(produit=auto_produit)
    async def suivre(interaction: discord.Interaction, produit: str):
        if not await autorise(interaction):
            return
        trouve = c.comparateur.produit(produit)
        if not trouve:
            await repondre(interaction, "Produit inconnu. Choisissez-le dans la liste proposée.", ephemere=True)
            return
        c.base.ajouter_favori(interaction.user.id, trouve.id)
        await repondre(interaction, f"⭐ {trouve.nom} ajouté à vos favoris.", ephemere=True)

    @tree.command(name="retirer", description="Retirer un produit de vos favoris")
    @app_commands.autocomplete(produit=auto_produit)
    async def retirer(interaction: discord.Interaction, produit: str):
        if await autorise(interaction):
            ok = c.base.retirer_favori(interaction.user.id, produit.strip())
            await repondre(interaction, "Retiré des favoris." if ok else "Ce produit n'est pas dans vos favoris.", ephemere=True)

    @tree.command(name="favoris", description="Vos produits suivis et leur meilleur prix")
    async def favoris(interaction: discord.Interaction):
        if not await autorise(interaction):
            return
        uid = interaction.user.id
        produits = [pr for pr in (c.comparateur.produit(i) for i in c.base.favoris(uid)) if pr]
        if not produits:
            await repondre(interaction, "Aucun favori. Ajoutez-en avec `/suivre` ou en créant une alerte.", ephemere=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        liste = await rapports(produits, c.base.preferences(uid))
        await repondre(interaction, formater_resume(liste, titre="⭐ Vos produits suivis"), ephemere=True)

    @tree.command(name="preferences", description="Voir ou modifier vos préférences (« aucun » pour retirer un réglage)")
    @app_commands.describe(
        prix_max="Prix maximum affiché, ex. 60 (ou « aucun »)",
        categorie="Catégorie, ex. coffret, booster, peluche (ou « aucun »)",
        etat="État souhaité",
        langue="Langue souhaitée",
        sites="Sites à surveiller, séparés par des virgules, ex. amazon.fr,fnac.com (ou « aucun »)",
        frequence="Fréquence des alertes en minutes",
    )
    async def preferences(
        interaction: discord.Interaction,
        prix_max: Optional[str] = None,
        categorie: Optional[str] = None,
        etat: Optional[Literal["neuf", "occasion", "ouvert", "indifférent"]] = None,
        langue: Optional[Literal["fr", "en", "ja", "indifférente"]] = None,
        sites: Optional[str] = None,
        frequence: Optional[app_commands.Range[int, 1, 10080]] = None,
    ):
        if not await autorise(interaction):
            return
        uid = interaction.user.id
        prefs = c.base.preferences(uid)
        erreurs = []
        valeurs = {"prixmax": prix_max, "categorie": categorie, "etat": etat, "langue": langue, "sites": sites,
                   "frequence": str(frequence) if frequence is not None else None}
        for cle, valeur in valeurs.items():
            if valeur is None:
                continue
            try:
                err = appliquer_preference(prefs, cle, valeur.strip())
            except ValueError as exc:
                err = str(exc)
            if err:
                erreurs.append(err)
        modifie = any(v is not None for v in valeurs.values())
        if modifie and not erreurs:
            if prefs.frequence_minutes is not None and prefs.frequence_minutes < p.frequence_min_minutes:
                prefs.frequence_minutes = p.frequence_min_minutes
            c.base.enregistrer_preferences(uid, prefs)
        texte = formater_preferences(prefs, p)
        if erreurs:
            texte = "❌ " + " ; ".join(erreurs) + "\n\n" + texte
        await repondre(interaction, texte, ephemere=True)

    @tree.command(name="sources", description="État des sources de prix et de la veille")
    async def sources(interaction: discord.Interaction):
        if not await autorise(interaction):
            return
        lignes = ["**Sources de prix**"]
        for con in c.comparateur.connecteurs:
            lignes.append(f"{'✅' if con.actif else '⛔'} **{con.libelle}** — {con.statut()}")
        lignes.append("\n**Veille des sorties et des drops**")
        v = c.veille
        for src in ([v.calendrier] if v.calendrier else []) + v.flux:
            etat = v.erreurs.get(src.id) or ("actif" if src.config.actif else "désactivé dans config/parametres.toml")
            lignes.append(f"{'✅' if src.config.actif and src.id not in v.erreurs else '⛔'} **{src.libelle}** — {etat}")
        if p.demo:
            lignes.append("⛔ Mode démo : la veille en ligne est désactivée (seuls les /drop fonctionnent).")
        salons = ", ".join(f"<#{s}>" for s in p.salons_veille) or "aucun (DISCORD_SALONS_VEILLE vide)"
        lignes.append(f"{'✅' if p.salons_veille else '⛔'} **Salons Discord suivis** — {salons}")
        lignes.append("✅ **Arrivages signalés par les membres** — commande /drop")
        await repondre(interaction, "\n".join(lignes), ephemere=True)

    @tree.command(name="sorties", description="Calendrier des sorties de la gamme 30e anniversaire")
    async def sorties(interaction: discord.Interaction):
        if not await autorise(interaction):
            return
        # Affiche ce que la tâche de veille a déjà lu (elle seule envoie les notifications).
        await repondre(interaction, formater_sorties(c.veille.sorties(), c.veille.erreurs, demo=p.demo))

    @tree.command(name="drop", description="Signaler un arrivage en magasin (prévient les membres qui suivent le produit)")
    @app_commands.describe(
        produit="Produit du catalogue", magasin="Enseigne et magasin, ex. Carrefour Écully, Maison de la Presse Lyon 3",
        ville="Ville ou code postal (facultatif)", details="Quantité, rayon, limite par client… (facultatif)",
    )
    @app_commands.autocomplete(produit=auto_produit)
    async def drop(interaction: discord.Interaction, produit: str, magasin: str,
                   ville: Optional[str] = None, details: Optional[str] = None):
        if not await autorise(interaction):
            return
        trouve = c.comparateur.produit(produit)
        if not trouve:
            await repondre(interaction, "Produit inconnu. Choisissez-le dans la liste proposée.", ephemere=True)
            return
        annonce, envois, erreur = c.veille.signaler_drop(interaction.user.id, trouve, magasin, ville, details)
        if erreur or annonce is None:
            await repondre(interaction, f"❌ {erreur}.", ephemere=True)
            return
        texte = formater_annonce(annonce, [trouve]) + f"\n*Signalé par <@{interaction.user.id}>.*"
        await repondre(interaction, texte)
        await interaction.client.distribuer(envois)  # type: ignore[attr-defined]

    @tree.command(name="drops", description="Arrivages signalés récemment (et jours où ils reviennent le plus)")
    @app_commands.describe(produit="Produit du catalogue (facultatif)")
    @app_commands.autocomplete(produit=auto_produit)
    async def drops(interaction: discord.Interaction, produit: Optional[str] = None):
        if not await autorise(interaction):
            return
        cible = c.comparateur.produit(produit) if produit else None
        if produit and not cible:
            await repondre(interaction, "Produit inconnu. Choisissez-le dans la liste proposée.", ephemere=True)
            return
        liste, stats = c.veille.drops(cible)
        catalogue = {pr.id: pr for pr in c.comparateur.catalogue}
        await repondre(interaction, formater_drops(liste, stats, catalogue, cible))

    @tree.command(name="oubliermoi", description="Effacer vos préférences, favoris et alertes")
    async def oubliermoi(interaction: discord.Interaction):
        c.base.oublier_utilisateur(interaction.user.id)
        await repondre(interaction, "🗑️ Vos préférences, favoris et alertes ont été effacés.", ephemere=True)

    return {cmd.name: cmd for cmd in tree.get_commands()}  # type: ignore[misc]


def appliquer_preference(prefs: Preferences, cle: str, valeur: str) -> Optional[str]:
    """Modifie prefs ; renvoie un message d'erreur ou None."""
    vide = valeur.lower() in ("aucun", "aucune", "tous", "toutes", "indifferent", "indifférent",
                              "indifferente", "indifférente", "")
    if cle == "prixmax":
        prefs.prix_max = None if vide else parser_decimal(valeur)
    elif cle == "categorie":
        prefs.categorie = None if vide else valeur
    elif cle == "etat":
        nouvel_etat = None if vide else etat_depuis(valeur)
        if nouvel_etat is Etat.INCONNU:
            return "état possible : neuf, occasion, ouvert"
        prefs.etat = nouvel_etat
    elif cle == "langue":
        prefs.langue = None if vide else normaliser_langue(valeur)
    elif cle == "sites":
        prefs.sites = [] if vide else [s.strip().lower() for s in valeur.replace(";", ",").split(",") if s.strip()]
    elif cle == "frequence":
        if not valeur.isdigit():
            return "fréquence en minutes, ex. 60"
        prefs.frequence_minutes = int(valeur)
    else:
        return f"réglage inconnu : {cle}"
    return None


def formater_preferences(prefs: Preferences, p: Parametres) -> str:
    frequence = prefs.frequence_minutes or p.frequence_defaut_minutes
    langue = NOMS_LANGUES.get(prefs.langue, prefs.langue) if prefs.langue else "indifférente"
    return (
        "**Vos préférences**\n"
        f"Prix maximum : {euros(prefs.prix_max) if prefs.prix_max else 'aucun'}\n"
        f"Catégorie : {prefs.categorie or 'toutes'}\n"
        f"État : {prefs.etat.value if prefs.etat else 'indifférent'}\n"
        f"Langue : {langue}\n"
        f"Sites : {', '.join(prefs.sites) if prefs.sites else 'tous'}\n"
        f"Fréquence des alertes : {frequence} min (minimum {p.frequence_min_minutes} min)"
    )


class BotDiscord(discord.Client):
    def __init__(self, contexte: Contexte):
        intents = discord.Intents.default()
        # Lire les annonces relayées dans les salons suivis exige l'intention privilégiée « Message Content »
        # (à activer sur le Developer Portal). Elle n'est demandée que si DISCORD_SALONS_VEILLE est rempli.
        intents.message_content = bool(contexte.parametres.salons_veille)
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.c = contexte
        self.tree = app_commands.CommandTree(self)
        self.commandes = enregistrer_commandes(self.tree, contexte)
        self.verification = tasks.loop(seconds=contexte.parametres.intervalle_tache_secondes)(self.verifier_alertes)
        self.verification.before_loop(self.wait_until_ready)
        self.tache_veille = tasks.loop(minutes=contexte.parametres.intervalle_veille_minutes)(self.verifier_veille)
        self.tache_veille.before_loop(self.wait_until_ready)

    async def setup_hook(self) -> None:
        guild_id = self.c.parametres.discord_guild_id
        if guild_id:
            # Synchronisation immédiate sur votre serveur (la synchro globale peut prendre plus de temps).
            serveur = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=serveur)
            await self.tree.sync(guild=serveur)
        else:
            await self.tree.sync()
        self.verification.start()
        self.tache_veille.start()

    async def on_ready(self) -> None:
        log.info("Connecté à Discord en tant que %s (mode %s)", self.user, self.c.parametres.mode)

    async def envoyer(self, utilisateur_id: int, salon_id: int | None, texte: str) -> None:
        """Message privé ; si l'utilisateur les a désactivés, envoi dans le salon d'origine."""
        try:
            utilisateur = self.get_user(utilisateur_id) or await self.fetch_user(utilisateur_id)
            for morceau in decouper(texte, LIMITE_DISCORD):
                await utilisateur.send(morceau, suppress_embeds=True)
            return
        except discord.HTTPException:
            if not salon_id:
                raise
        salon = self.get_channel(salon_id) or await self.fetch_channel(salon_id)
        mention = discord.AllowedMentions(users=True)
        for n, morceau in enumerate(decouper(texte, LIMITE_DISCORD - 30)):
            prefixe = f"<@{utilisateur_id}> " if n == 0 else ""
            await salon.send(prefixe + morceau, suppress_embeds=True, allowed_mentions=mention)  # type: ignore[union-attr]

    async def envoyer_alerte(self, alerte: AlerteEnregistree, texte: str) -> None:
        await self.envoyer(alerte.utilisateur_id, alerte.salon_id, texte)

    async def distribuer(self, envois: list[Envoi]) -> None:
        catalogue = {pr.id: pr for pr in self.c.comparateur.catalogue}
        for e in envois:
            produits = [catalogue[pid] for pid in e.annonce.produit_ids if pid in catalogue]
            try:
                await self.envoyer(e.utilisateur_id, e.salon_id, formater_annonce(e.annonce, produits))
            except discord.HTTPException:
                log.warning("Notification de veille non délivrée à %s", e.utilisateur_id)

    async def verifier_veille(self) -> None:
        try:
            envois = await asyncio.to_thread(self.c.veille.actualiser)
        except Exception:
            log.exception("Échec de la veille des sorties")
            return
        await self.distribuer(envois)

    async def on_message(self, message: discord.Message) -> None:
        """Annonces relayées par la fonction « Suivre » de Discord dans les salons configurés."""
        if message.channel.id not in self.c.parametres.salons_veille or message.author == self.user:
            return
        morceaux = [message.content or ""]
        for embed in message.embeds:
            morceaux += [embed.title or "", embed.description or ""]
            morceaux += [f"{champ.name} {champ.value}" for champ in embed.fields]
        texte = "\n".join(m for m in morceaux if m).strip()
        if not texte:
            return
        envois = self.c.veille.traiter_message(str(message.id), texte, message.jump_url, message.created_at)
        await self.distribuer(envois)

    async def verifier_alertes(self) -> None:
        c = self.c
        for alerte in c.base.alertes_a_verifier(c.parametres.frequence_min_minutes):
            produit = c.comparateur.produit(alerte.produit_id)
            if produit is None:
                continue
            try:
                rapport = await asyncio.to_thread(c.comparateur.rapport, produit, alerte.preferences())
                notifications, nouvel_etat = evaluer_alerte(rapport, alerte.prix_max, alerte.etat_alerte)
                for n in notifications:
                    await self.envoyer_alerte(alerte, formater_notification(n, rapport, alerte.prix_max))
                c.base.maj_etat_alerte(alerte.id, nouvel_etat)
            except Exception:
                log.exception("Échec de la vérification de l'alerte %s", alerte.id)


PORT_INSTANCE_UNIQUE = 47613  # deux bots avec le même jeton enverraient chaque alerte en double
CODE_DEJA_LANCE = 3


def _verrou_instance_unique():
    """Réserve un port local : si un autre PokéVeille tourne déjà, on s'arrête proprement."""
    import socket

    verrou = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        verrou.bind(("127.0.0.1", PORT_INSTANCE_UNIQUE))
    except OSError:
        verrou.close()
        print("PokéVeille tourne déjà sur cet ordinateur : rien à faire.", file=sys.stderr)
        raise SystemExit(CODE_DEJA_LANCE)
    return verrou


def lancer(parametres: Parametres) -> None:
    if not parametres.discord_token:
        raise SystemExit("DISCORD_BOT_TOKEN manquant dans .env (voir README, section Discord).")
    verrou = _verrou_instance_unique()  # gardé ouvert tant que le bot tourne
    base = BaseDonnees(parametres.chemin_db)
    bot = BotDiscord(Contexte(parametres, Comparateur(parametres, base=base), base))
    try:
        bot.run(parametres.discord_token, log_handler=None)
    except discord.PrivilegedIntentsRequired as exc:
        raise SystemExit(
            "DISCORD_SALONS_VEILLE est rempli : activez « Message Content Intent » dans le Developer Portal "
            "(votre application > Bot > Privileged Gateway Intents), ou videz DISCORD_SALONS_VEILLE."
        ) from exc
    finally:
        verrou.close()
