"""Mise en forme de la veille des sorties et des drops (Markdown Discord ou texte brut)."""

from __future__ import annotations

from datetime import date

from .affichage import BANNIERE_DEMO, Rendu
from .models import Produit
from .service_veille import LigneSortie
from .temps import format_paris, maintenant
from .veille import DROP, SORTIE, Annonce

EMOJI = {SORTIE: "📅", DROP: "🏬"}
AVERTISSEMENT_DATE = "Date annoncée par la source : elle peut encore changer (reports fréquents)."
AVERTISSEMENT_DROP = "Arrivage signalé, non vérifié par le bot : stock limité, appelez le magasin avant de vous déplacer."


def _jour(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def formater_annonce(a: Annonce, produits: list[Produit], markdown: bool = True) -> str:
    r = Rendu(markdown)
    emoji = EMOJI.get(a.type, "📰")
    if a.titre.startswith("Sortie prévue demain"):
        emoji = "⏰"
    lignes = [f"{emoji} " + r.b(a.titre)]
    if produits and a.source not in ("pokepedia", "membre"):
        lignes.append(r.t("Produit(s) : " + ", ".join(p.nom for p in produits)))
    if a.type == DROP and (a.magasin or a.ville):
        lignes.append(r.t("Où : " + " · ".join(x for x in (a.magasin, a.ville) if x)))
    if a.texte:
        lignes.append(r.retrait + r.t(a.texte[:300]))
    if a.dates and a.type != SORTIE:
        lignes.append(r.t("Dates citées : " + ", ".join(_jour(d) for d in a.dates[:4])))
    lignes.append(r.t(f"Source : {a.libelle_source} · {format_paris(a.publie_le)}"))
    if a.url:
        lignes.append("🔗 " + r.lien("Voir la source", a.url))
    lignes.append(r.i(AVERTISSEMENT_DROP if a.type == DROP else AVERTISSEMENT_DATE if a.type == SORTIE
                      else "Information publiée par la source citée : vérifiez-la avant de vous déplacer."))
    return "\n".join(lignes)


def formater_sorties(lignes: list[LigneSortie], erreurs: dict[str, str] | None = None,
                     markdown: bool = True, demo: bool = False) -> str:
    r = Rendu(markdown)
    aujourd_hui = maintenant().date()
    sortie = [r.b(BANNIERE_DEMO)] if demo else []
    sortie.append(r.b("📅 Calendrier des sorties — gamme 30e anniversaire"))
    for l in lignes:
        if l.date_sortie is None:
            quand = "date non trouvée"
        else:
            ecart = (l.date_sortie - aujourd_hui).days  # type: ignore[operator]
            quand = _jour(l.date_sortie) + (  # type: ignore[arg-type]
                " (aujourd'hui)" if ecart == 0 else f" (dans {ecart} j)" if ecart > 0 else " (sorti)")
        ligne = f"• {r.b(l.produit.nom)} — " + r.t(quand)
        if l.url:
            ligne += " · " + r.lien("Poképédia", l.url)
        sortie.append(ligne)
        for a in l.annonces[:1]:
            infos = f"dernière info : {a.titre[:90]} ({a.libelle_source}, {a.publie_le:%d/%m})"
            sortie.append(r.retrait + (r.lien(infos, a.url) if a.url else r.t(infos)))
    if not lignes:
        sortie.append(r.t("Aucun produit de la gamme dans le catalogue."))
    for source, err in (erreurs or {}).items():
        sortie.append(r.t(f"⚠️ {source} : {err}"))
    sortie.append(r.i("Dates de sortie lues sur Poképédia (CC BY-NC-SA) ; reports signalés par Le CrocoDeal "
                      "et la Fnac. Le stock en magasin n'est jamais garanti."))
    return "\n".join(sortie)


def formater_drops(liste: list[Annonce], stats: list[tuple[str, str, int]], catalogue: dict[str, Produit],
                   produit: Produit | None = None, jours: int = 30, markdown: bool = True) -> str:
    r = Rendu(markdown)
    titre = f"🏬 Arrivages signalés ({jours} derniers jours)" + (f" — {produit.nom}" if produit else "")
    sortie = [r.b(titre)]
    for a in liste[:15]:
        noms = ", ".join(catalogue[p].nom if p in catalogue else p for p in a.produit_ids)
        ou = " · ".join(x for x in (a.magasin, a.ville) if x) or "lieu non précisé"
        ligne = f"• {format_paris(a.publie_le)} — {ou} — {noms} ({a.libelle_source})"
        sortie.append(r.lien(ligne, a.url) if a.url else r.t(ligne))
    if not liste:
        sortie.append(r.t("Aucun arrivage signalé. Signalez-en un avec /drop."))
    if stats:
        sortie.append(r.b("Jours où les arrivages sont le plus signalés"))
        sortie += [r.t(f"• {m} : le {j} ({n} signalement{'s' if n > 1 else ''})") for m, j, n in stats]
        sortie.append(r.i("Tendance tirée des signalements des membres, pas une information officielle."))
    sortie.append(r.i("Arrivages non vérifiés par le bot : appelez le magasin avant de vous déplacer."))
    return "\n".join(sortie)
