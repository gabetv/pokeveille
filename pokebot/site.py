"""Site statique (GitHub Pages) : calendrier des sorties, comparatif des produits suivis, dernières infos.

Pages en HTML autonome (aucune ressource externe, aucun traceur), clair/sombre selon le système.
Toutes les valeurs affichées sont échappées ; seuls les liens http(s) sont rendus cliquables.
"""

from __future__ import annotations

import html
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

from .affichage import BANNIERE_DEMO, euros, libelle_date, libelle_etat, libelle_langue, libelle_site
from .analyse import EMOJI_AVIS, Avis, Rapport, meilleure_offre
from .base import BaseDonnees
from .models import LIBELLES_DISPO, LIBELLES_VENDEUR, Produit
from .service_veille import LigneSortie
from .temps import format_paris, maintenant
from .veille import DROP, INFO, SORTIE

CLASSES_AVIS = {
    Avis.TRES_BONNE_AFFAIRE: "vert", Avis.RAISONNABLE: "bleu", Avis.UN_PEU_CHER: "orange",
    Avis.CHER: "rouge", Avis.A_VERIFIER: "alerte", Avis.INSUFFISANT: "gris",
}

CSS = """
:root{--fond:#f6f7fb;--carte:#fff;--texte:#1d2330;--doux:#5d6678;--bord:#e2e5ee;--accent:#d63b3b;
--vert:#1f8a4c;--bleu:#2563c9;--orange:#c46a00;--rouge:#c42b2b;--alerte:#9a6a00;--gris:#6b7280}
@media (prefers-color-scheme:dark){:root{--fond:#12151c;--carte:#1b2029;--texte:#e7eaf0;--doux:#9aa3b5;
--bord:#2b313d;--accent:#ff6b6b;--vert:#4cc27e;--bleu:#6aa1ff;--orange:#f0a040;--rouge:#ff6b6b;--alerte:#e5b94a;--gris:#9aa3b5}}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--texte);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.2rem;margin:32px 0 12px}
a{color:var(--bleu)}.doux{color:var(--doux);font-size:.92rem}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:12px;padding:14px 16px;margin:10px 0}
.grille{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.grille .carte{margin:0}
table{width:100%;border-collapse:collapse;background:var(--carte);border:1px solid var(--bord);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--bord);vertical-align:top}
th{font-size:.85rem;color:var(--doux);font-weight:600}tr:last-child td{border-bottom:0}
.tableau{overflow-x:auto}
.pastille{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.82rem;font-weight:600;border:1px solid currentColor}
.vert{color:var(--vert)}.bleu{color:var(--bleu)}.orange{color:var(--orange)}.rouge{color:var(--rouge)}
.alerte{color:var(--alerte)}.gris{color:var(--gris)}
.banniere{background:var(--accent);color:#fff;padding:8px 12px;border-radius:8px;font-weight:600}
.signal{font-size:.88rem;color:var(--doux);margin:2px 0}
footer{margin-top:40px;color:var(--doux);font-size:.85rem}
"""


def e(valeur: object) -> str:
    return html.escape(str(valeur), quote=True)


def lien(texte: str, url: str | None) -> str:
    if url and url.startswith(("https://", "http://")):
        return f'<a href="{e(url)}" rel="noopener nofollow" target="_blank">{e(texte)}</a>'
    return e(texte)


def pastille(avis: Avis) -> str:
    return f'<span class="pastille {CLASSES_AVIS[avis]}">{EMOJI_AVIS[avis]} {e(avis.value)}</span>'


def page(titre: str, corps: str, demo: bool, racine: str = "") -> str:
    banniere = f'<p class="banniere">{e(BANNIERE_DEMO)}</p>' if demo else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titre)}</title><meta name="robots" content="noindex"><style>{CSS}</style></head>
<body><main>{banniere}{corps}
<footer>Mis à jour le {e(format_paris(maintenant()))}. Prix et stocks à vérifier sur le site marchand avant
tout achat ; le site n'achète rien et ne collecte aucune donnée. Dates de sortie : Poképédia (CC BY-NC-SA) ;
infos : Le CrocoDeal, Fnac L'Éclaireur. <a href="{racine}index.html">Accueil</a></footer></main></body></html>"""


def _quand(jour: date | None) -> str:
    if jour is None:
        return '<span class="doux">date non trouvée</span>'
    ecart = (jour - maintenant().date()).days
    suite = "aujourd'hui" if ecart == 0 else f"dans {ecart} j" if ecart > 0 else "sorti"
    return f"{jour:%d/%m/%Y} <span class=\"doux\">({suite})</span>"


def _resume_prix(r: Rapport) -> str:
    m = meilleure_offre(r)
    morceaux = []
    if m:
        total = euros(m.total.montant) + ("" if m.total.exact else " (hors livraison)" if m.offre.livraison is None else " (estimé)")
        morceaux.append(f"Meilleure offre fiable : <b>{e(total)}</b> sur {e(m.offre.site)} {pastille(m.avis)}")
    else:
        morceaux.append('<span class="doux">Aucune offre fiable vérifiée pour l\'instant.</span>')
    if r.ref_amazon:
        morceaux.append(f"Référence Amazon : {e(euros(r.ref_amazon.montant))}")
    if r.mediane is not None:
        morceaux.append(f"Médiane : {e(euros(r.mediane))} ({r.nb_offres_mediane} offres)")
    return "<br>".join(morceaux)


def page_produit(r: Rapport, demo: bool) -> str:
    p = r.produit
    lignes = []
    for l in r.lignes:
        o = l.offre
        signaux = "".join(f'<div class="signal">{"⚠️" if s.bloquant else "ℹ️"} {e(s.message)}</div>' for s in l.signaux)
        total = e(euros(l.total.montant)) + ("" if l.total.exact else f' <span class="doux">({e(l.total.mention)})</span>')
        lignes.append(
            f"<tr><td>{lien(libelle_site(o), o.url)}<div class=\"doux\">{e(o.vendeur or 'vendeur non précisé')} · "
            f"{e(LIBELLES_VENDEUR[o.type_vendeur])}</div></td>"
            f"<td>{e(libelle_etat(o, p.type))}<div class=\"doux\">{e(libelle_langue(o.langue))} · "
            f"{e(LIBELLES_DISPO[o.disponibilite])}</div></td>"
            f"<td><b>{total}</b><div class=\"doux\">prix {e(euros(o.prix))}</div></td>"
            f"<td>{pastille(l.avis)}{signaux}<div class=\"doux\">{e(libelle_date(o))}</div></td></tr>"
        )
    tableau = (
        '<div class="tableau"><table><tr><th>Site / vendeur</th><th>État</th><th>Total</th><th>Avis</th></tr>'
        + "".join(lignes) + "</table></div>"
        if lignes else '<p class="doux">Aucune annonce correspondante sur les sources actives.</p>'
    )
    infos = [e(p.categorie), e(libelle_langue(p.langue))]
    if p.ean:
        infos.append(f"EAN {e(p.ean)}")
    if p.contenu:
        infos.append(e(p.contenu))
    corps = (
        f"<h1>{e(p.nom)}</h1><p class=\"doux\">{' · '.join(infos)}</p>"
        f"<div class=\"carte\">{_resume_prix(r)}<div class=\"doux\">{e(r.statut_amazon)}</div></div>"
        f"<h2>Offres</h2>{tableau}"
        + (f"<p>{lien('Page officielle', p.lien_officiel)}</p>" if p.lien_officiel else "")
    )
    return page(p.nom, corps, demo, racine="../")


def page_accueil(rapports: list[Rapport], sorties: list[LigneSortie], base: BaseDonnees,
                 catalogue: dict[str, Produit], erreurs: dict[str, str], demo: bool) -> str:
    lignes_sorties = "".join(
        f"<tr><td><a href=\"produits/{e(s.produit.id)}.html\">{e(s.produit.nom)}</a></td><td>{_quand(s.date_sortie)}"
        + (f' · {lien("Poképédia", s.url)}' if s.url else "") + "</td><td>"
        + ("".join(f"{lien(a.titre[:90], a.url)} <span class=\"doux\">({e(a.libelle_source)}, {a.publie_le:%d/%m})</span>"
                   for a in s.annonces[:1]) or '<span class="doux">—</span>') + "</td></tr>"
        for s in sorties
    )
    cartes = "".join(
        f'<div class="carte"><b><a href="produits/{e(r.produit.id)}.html">{e(r.produit.nom)}</a></b>'
        f'<div class="doux">{e(r.produit.categorie)}</div><p>{_resume_prix(r)}</p></div>'
        for r in rapports
    )
    annonces = base.annonces(types=(SORTIE, INFO, DROP), limite=15)
    liste_annonces = "".join(
        f'<div class="carte">{lien(a.titre, a.url)}<div class="doux">{e(a.libelle_source)} · '
        f'{e(format_paris(a.publie_le))}'
        + (" · " + e(", ".join(catalogue[i].nom for i in a.produit_ids if i in catalogue)) if a.produit_ids else "")
        + "</div></div>"
        for a in annonces
    ) or '<p class="doux">Aucune info pour l\'instant.</p>'
    bons_plans = [l for r in rapports for l in r.lignes if l.offre.signalement]
    liste_bons_plans = "".join(
        f'<div class="carte">{lien(l.offre.titre, l.offre.url)} — <b>{e(euros(l.offre.prix))}</b>'
        f'<div class="doux">{e(libelle_site(l.offre))} · {e(libelle_date(l.offre))} · prix communautaire à vérifier</div></div>'
        for l in sorted(bons_plans, key=lambda l: l.offre.verifie_le or maintenant(), reverse=True)[:10]
    ) or '<p class="doux">Aucun bon plan récent sur les produits suivis.</p>'
    alertes_sources = "".join(f'<p class="signal">⚠️ {e(k)} : {e(v)}</p>' for k, v in erreurs.items())
    corps = (
        "<h1>PokéVeille 30</h1><p class=\"doux\">Veille des produits Pokémon du 30e anniversaire (marché français) : "
        "dates de sortie, prix comparés, dernières infos.</p>" + alertes_sources
        + "<h2>📅 Calendrier des sorties</h2><div class=\"tableau\"><table><tr><th>Produit</th><th>Sortie annoncée</th>"
        "<th>Dernière info</th></tr>" + lignes_sorties + "</table></div>"
        + "<h2>📰 Dernières infos</h2>" + liste_annonces
        + "<h2>💸 Bons plans communautaires</h2>" + liste_bons_plans
        + "<h2>🎴 Produits suivis</h2><div class=\"grille\">" + cartes + "</div>"
    )
    return page("PokéVeille 30", corps, demo)


def generer_site(dossier: Path, rapports: list[Rapport], sorties: list[LigneSortie], base: BaseDonnees,
                 catalogue: dict[str, Produit], erreurs: dict[str, str] | None = None, demo: bool = False) -> Path:
    if dossier.exists():
        # Sécurité : on ne vide qu'un dossier déjà généré par ce module (ou vide).
        if any(dossier.iterdir()) and not (dossier / ".nojekyll").exists():
            raise SystemExit(f"{dossier} existe et n'est pas un site PokéVeille : choisissez un autre dossier")
        shutil.rmtree(dossier)
    (dossier / "produits").mkdir(parents=True)
    (dossier / "index.html").write_text(
        page_accueil(rapports, sorties, base, catalogue, erreurs or {}, demo), encoding="utf-8")
    for r in rapports:
        (dossier / "produits" / f"{r.produit.id}.html").write_text(page_produit(r, demo), encoding="utf-8")
    (dossier / ".nojekyll").write_text("", encoding="utf-8")
    return dossier
