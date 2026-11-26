"""Mise en forme des résultats en français (Markdown Discord ou texte brut pour la console)."""

from __future__ import annotations

import re
from decimal import Decimal

from .alertes import Notification
from .analyse import EMOJI_AVIS, LigneOffre, Rapport, meilleure_offre
from .models import (
    LIBELLES_DISPO, LIBELLES_TYPE, LIBELLES_VENDEUR, NOMS_LANGUES, Etat, Offre, Preferences,
    StatutLivraison, TypeProduit, normaliser_langue,
)
from .temps import format_paris

BANNIERE_DEMO = "🧪 MODE DÉMO — DONNÉES FICTIVES, aucun prix réel"
LIMITE_DISCORD = 1900  # un message Discord est limité à 2 000 caractères
_SPECIAUX_MARKDOWN = re.compile(r"([\\*_~`|\[\]<>#])")


def euros(montant: Decimal | None) -> str:
    if montant is None:
        return "—"
    texte = f"{montant:,.2f}".replace(",", " ").replace(".", ",")
    return f"{texte} €"


def signe_euros(montant: Decimal) -> str:
    return ("+" if montant > 0 else "−" if montant < 0 else "±") + euros(abs(montant))


def signe_pct(pct: Decimal) -> str:
    texte = f"{abs(pct)}".replace(".", ",")
    return ("+" if pct > 0 else "−" if pct < 0 else "±") + texte + " %"


class Rendu:
    """Produit du Markdown Discord ou du texte brut."""

    def __init__(self, markdown: bool):
        self.md = markdown
        self.retrait = "> " if markdown else "   "  # détails d'une offre : bloc de citation sur Discord

    def t(self, texte: object) -> str:
        return _SPECIAUX_MARKDOWN.sub(r"\\\1", str(texte)) if self.md else str(texte)

    def b(self, texte: object) -> str:
        return f"**{self.t(texte)}**" if self.md else str(texte)

    def i(self, texte: object) -> str:
        return f"*{self.t(texte)}*" if self.md else str(texte)

    def code(self, texte: object) -> str:
        return f"`{str(texte).replace('`', '')}`" if self.md else str(texte)

    def lien(self, texte: str, url: str) -> str:
        if self.md:
            # <url> : pas d'aperçu automatique du lien.
            return f"[{self.t(texte)}](<{url.replace('>', '%3E')}>)"
        return f"{texte} : {url}"


def libelle_langue(langue: str | None) -> str:
    code = normaliser_langue(langue)
    if not code:
        return "langue non précisée"
    nom = NOMS_LANGUES.get(code, code)
    return nom if code == "fr" else f"{nom} (version étrangère / import)"


def libelle_etat(offre: Offre, type_produit: TypeProduit) -> str:
    if type_produit in (TypeProduit.CARTE, TypeProduit.CARTE_GRADEE):
        if offre.societe_gradation:
            return f"gradée {offre.societe_gradation} {offre.note_gradation or '?'}"
        return f"état {offre.etat_carte}" if offre.etat_carte else "état de la carte non précisé"
    if offre.etat is Etat.NEUF:
        return "neuf scellé" if type_produit is TypeProduit.SCELLE else "neuf"
    return {Etat.OUVERT: "ouvert", Etat.OCCASION: "occasion"}.get(offre.etat, "état non précisé")


def _entete(r: Rendu, rapport: Rapport) -> list[str]:
    p = rapport.produit
    lignes = []
    if rapport.demo:
        lignes.append(r.b(BANNIERE_DEMO))
    lignes.append(f"🎴 {r.b(p.nom)}")
    details = f"{p.categorie} · {LIBELLES_TYPE[p.type]} · {libelle_langue(p.langue)}"
    if p.type is TypeProduit.CARTE_GRADEE:
        details += f" · {p.societe_gradation} {p.note_gradation}"
    elif p.type is TypeProduit.CARTE and p.etat_carte:
        details += f" · état {p.etat_carte}"
    lignes.append(r.t(details) + f" · id {r.code(p.id)}")
    lignes.append("Source officielle : " + (r.lien("page produit", p.lien_officiel) if p.lien_officiel else r.t("non renseignée")))
    if p.prix_conseille is not None:
        lignes.append(r.t(f"Prix conseillé officiel : {euros(p.prix_conseille)} (source : {p.source_prix_conseille})"))

    if p.type in (TypeProduit.CARTE, TypeProduit.CARTE_GRADEE):
        lignes.append(r.t("Référence Amazon.fr : non utilisée pour les cartes à l'unité"))
    elif rapport.ref_amazon:
        ref = rapport.ref_amazon
        qui = (f"⚠️ vendeur tiers : {ref.ligne.offre.vendeur}" if ref.vendeur_tiers
               else "vendu et expédié par Amazon")
        extra = ", hors frais de livraison" if ref.hors_livraison else ""
        lignes.append("Référence Amazon.fr : " + r.b(euros(ref.montant)) + r.t(f" ({qui}{extra})"))
    else:
        lignes.append(r.t(f"Référence Amazon.fr : aucune offre disponible, neuve et identique — {rapport.statut_amazon}"))
    if rapport.demo or rapport.ref_amazon:
        lignes.append(r.i(f"Amazon : {rapport.statut_amazon}"))

    if rapport.mediane is not None:
        lignes.append("Médiane du marché : " + r.b(euros(rapport.mediane))
                      + r.t(f" ({rapport.nb_offres_mediane} offres comparables de vendeurs fiables)"))
    else:
        lignes.append(r.t(f"Médiane du marché : non calculable ({rapport.nb_offres_mediane} offre(s) "
                          "comparable(s) de vendeurs fiables, minimum requis non atteint)"))
    for site, erreur in rapport.statuts_sources.items():
        lignes.append(r.t(f"⚠️ {site} : {erreur}"))
    return lignes


def libelle_date(o: Offre) -> str:
    """Un bon plan communautaire est « publié », une offre lue sur une source est « vérifiée »."""
    return f"{'publié' if o.signalement else 'vérifié'} le {format_paris(o.verifie_le)}"


def libelle_site(o: Offre) -> str:
    return f"{o.site} (bon plan Le CrocoDeal)" if o.signalement and o.site != "lecrocodeal.com" else o.site


def formater_ligne(r: Rendu, n: int, l: LigneOffre, type_produit: TypeProduit) -> str:
    o = l.offre
    x = r.retrait
    numero = r.b(f"{n}.") if r.md else f"{n}."  # en gras : évite la renumérotation des listes Markdown
    morceaux = [f"{numero} {EMOJI_AVIS[l.avis]} {r.b(l.avis.value)} — {r.t(libelle_site(o))}"]
    vendeur = o.vendeur or "vendeur non précisé"
    morceaux.append(x + r.t(f"Vendeur : {vendeur} ({LIBELLES_VENDEUR[o.type_vendeur]})"))
    morceaux.append(x + r.t(f"{libelle_etat(o, type_produit)} · {libelle_langue(o.langue)} · {LIBELLES_DISPO[o.disponibilite]}"))
    if o.livraison is not None:
        livraison = euros(o.livraison) + (" (estimée)" if not l.total.exact else "")
    else:
        livraison = "frais de livraison à vérifier"
    if l.total.exact:
        total = euros(l.total.montant)
    elif o.statut_livraison is StatutLivraison.INCONNUE:
        total = euros(l.total.montant) + " hors livraison"
    else:
        total = euros(l.total.montant) + " (estimé)"
    frais = f" + frais {euros(o.frais_obligatoires)}" if o.frais_obligatoires else ""
    morceaux.append(x + r.t(f"Prix : {euros(o.prix)}{frais} · Livraison : {livraison} · Total : ") + r.b(total))
    if l.ecart_amazon_eur is not None and l.ecart_amazon_pct is not None:
        morceaux.append(x + r.t(f"vs Amazon : {signe_euros(l.ecart_amazon_eur)} ({signe_pct(l.ecart_amazon_pct)})"))
    if l.note_avis:
        morceaux.append(x + r.i(l.note_avis))
    for s in l.signaux:
        morceaux.append(x + r.t(f"{'⚠️' if s.bloquant else 'ℹ️'} {s.message}"))
    morceaux.append(x + r.t(f"Correspondance : {l.correspondance.raison} · {libelle_date(o)}"))
    morceaux.append(x + "🔗 " + r.lien("Voir le bon plan" if o.signalement else "Voir l'annonce", o.url))
    return "\n".join(morceaux)


def lignes_visibles(rapport: Rapport, preferences: Preferences | None) -> tuple[list[LigneOffre], int]:
    lignes = rapport.lignes
    if preferences and preferences.prix_max is not None:
        gardees = [l for l in lignes if l.total.montant is None or l.total.montant <= preferences.prix_max]
        return gardees, len(lignes) - len(gardees)
    return lignes, 0


def formater_rapport(rapport: Rapport, markdown: bool = True, max_offres: int = 8,
                     preferences: Preferences | None = None) -> str:
    r = Rendu(markdown)
    blocs = ["\n".join(_entete(r, rapport))]
    lignes, masquees = lignes_visibles(rapport, preferences)
    if not lignes:
        blocs.append(r.t("Aucune annonce correspondante trouvée sur les sources actives."))
    for n, l in enumerate(lignes[:max_offres], start=1):
        blocs.append(formater_ligne(r, n, l, rapport.produit.type))
    notes = []
    if len(lignes) > max_offres:
        notes.append(f"{len(lignes) - max_offres} autre(s) annonce(s) non affichée(s).")
    if masquees:
        notes.append(f"{masquees} annonce(s) au-dessus de votre prix maximum masquée(s).")
    if rapport.annonces_ecartees:
        notes.append(f"{rapport.annonces_ecartees} annonce(s) écartée(s) : autre produit, variante, langue, état ou note différents.")
    if rapport.ventes_reelles:
        ventes = ", ".join(euros(l.total.montant) for l in rapport.ventes_reelles[:5])
        med = euros(rapport.mediane_ventes) if rapport.mediane_ventes is not None else "non calculable"
        notes.append(f"Ventes réellement conclues (prix payés, pas des annonces) : {ventes} — médiane : {med}.")
    if notes:
        blocs.append(r.i(" ".join(notes)))
    blocs.append(r.i(f"Rapport généré le {format_paris(rapport.genere_le)}. Aucun achat n'est effectué par le bot."))
    return "\n\n".join(blocs)


def formater_resume(rapports: list[Rapport], markdown: bool = True, titre: str = "") -> str:
    r = Rendu(markdown)
    lignes = []
    if rapports and rapports[0].demo:
        lignes.append(r.b(BANNIERE_DEMO))
    if titre:
        lignes.append(r.b(titre))
    for rap in rapports:
        p = rap.produit
        meilleure = meilleure_offre(rap)
        if meilleure:
            info = (f"meilleure offre fiable : {euros(meilleure.total.montant)}"
                    f"{'' if meilleure.total.exact else ' (estimé)'} sur {meilleure.offre.site} "
                    f"{EMOJI_AVIS[meilleure.avis]} {meilleure.avis.value}")
        else:
            info = "aucune offre fiable vérifiée"
        ref = f" · Amazon : {euros(rap.ref_amazon.montant)}" if rap.ref_amazon else ""
        lignes.append(f"• {r.b(p.nom)} " + r.t(f"({p.categorie}, {libelle_langue(p.langue)})"))
        commande = f"/fiche produit:{p.id}" if markdown else f"py -m pokebot fiche {p.id}"
        lignes.append(r.retrait + r.t(f"{info}{ref}") + " → " + r.code(commande))
    if not rapports:
        lignes.append(r.t("Aucun produit trouvé."))
    return "\n".join(lignes)


def formater_offres_libres(offres: list[Offre], markdown: bool = True, demo: bool = False, max_offres: int = 10) -> str:
    r = Rendu(markdown)
    x = r.retrait
    blocs = []
    if demo:
        blocs.append(r.b(BANNIERE_DEMO))
    blocs.append(r.t("Produit absent du catalogue de référence : correspondance à vérifier, prix non comparés."))
    for n, o in enumerate(offres[:max_offres], start=1):
        livraison = euros(o.livraison) if o.livraison is not None else "frais de livraison à vérifier"
        blocs.append("\n".join([
            f"{r.b(f'{n}.') if markdown else f'{n}.'} {r.b(o.titre)}",
            x + r.t(f"{libelle_site(o)} · {o.vendeur or 'vendeur non précisé'} · {LIBELLES_DISPO[o.disponibilite]}"),
            x + r.t(f"Prix : {euros(o.prix)} · Livraison : {livraison}"),
            x + r.t(libelle_date(o)[:1].upper() + libelle_date(o)[1:]),
            x + "🔗 " + r.lien("Voir le bon plan" if o.signalement else "Voir l'annonce", o.url),
        ]))
    if not offres:
        blocs.append(r.t("Aucune annonce trouvée sur les sources actives."))
    return "\n\n".join(blocs)


def formater_notification(n: Notification, rapport: Rapport, prix_max: Decimal, markdown: bool = True) -> str:
    r = Rendu(markdown)
    l, o = n.ligne, n.ligne.offre
    lignes = [r.b(BANNIERE_DEMO)] if rapport.demo else []
    if n.type == "signalement":
        enseigne = o.site if o.site != "lecrocodeal.com" else "enseigne non identifiée"
        lignes += [
            r.b(f"📣 Bon plan signalé sur Le CrocoDeal : {rapport.produit.nom}"),
            r.t(f"« {o.titre} »"),
            r.t(f"Prix annoncé : {euros(o.prix)} (votre maximum : {euros(prix_max)}) · {enseigne} · "
                f"{libelle_date(o)}"),
            r.t(f"Correspondance : {l.correspondance.raison}"),
            "🔗 " + r.lien("Voir le bon plan", o.url),
            r.i("Prix publié par la communauté, non vérifié par le bot : contrôlez prix, stock, vendeur "
                "et livraison sur le site marchand. Le bot n'achète jamais à votre place."),
        ]
        return "\n".join(lignes)
    if n.type == "stock":
        titre = f"📦 De retour en stock : {rapport.produit.nom}"
    else:
        titre = f"🔔 Sous votre prix maximum ({euros(prix_max)}) : {rapport.produit.nom}"
    lignes += [
        r.b(titre),
        r.t(f"{o.site} · {o.vendeur or 'vendeur non précisé'} · {LIBELLES_DISPO[o.disponibilite]}"),
        r.t(f"Total : {euros(l.total.montant)} ({l.total.mention}) · {EMOJI_AVIS[l.avis]} {l.avis.value}"),
    ]
    lignes += [r.t(f"{'⚠️' if s.bloquant else 'ℹ️'} {s.message}") for s in l.signaux]
    lignes.append("🔗 " + r.lien("Voir l'annonce", o.url))
    lignes.append(r.i("Vérifiez l'annonce avant d'acheter. Le bot n'achète jamais à votre place."))
    return "\n".join(lignes)


def decouper(texte: str, limite: int = LIMITE_DISCORD) -> list[str]:
    """Découpe un long message en morceaux ≤ limite, de préférence entre deux paragraphes."""
    morceaux, courant = [], ""
    for bloc in texte.split("\n\n"):
        candidat = f"{courant}\n\n{bloc}" if courant else bloc
        if len(candidat) <= limite:
            courant = candidat
            continue
        if courant:
            morceaux.append(courant)
        while len(bloc) > limite:
            coupe = bloc.rfind("\n", 0, limite)
            coupe = coupe if coupe > 0 else limite
            morceaux.append(bloc[:coupe])
            bloc = bloc[coupe:].lstrip("\n")
        courant = bloc
    if courant:
        morceaux.append(courant)
    return morceaux
