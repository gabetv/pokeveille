"""Veille des sorties et des drops : reconnaissance des produits, dates, Poképédia, service (sans réseau)."""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pokebot.affichage_veille import formater_annonce, formater_drops, formater_sorties
from pokebot.base import BaseDonnees
from pokebot.comparateur import Comparateur
from pokebot.config import ConfigSource, Parametres
from pokebot.csv_io import lire_catalogue
from pokebot.service_veille import ServiceVeille
from pokebot.sources_veille import CalendrierPokepedia, FluxAnnonces, lire_infobox
from pokebot.veille import DROP, INFO, SORTIE, code_postal, dates_citees, magasin_cite, produits_cites

RACINE = Path(__file__).resolve().parent.parent
CATALOGUE = lire_catalogue(RACINE / "data" / "catalogue.csv")
UTC = timezone.utc


def ids(texte):
    return sorted(p.id for p in produits_cites(texte, CATALOGUE))


class TestReconnaissance(unittest.TestCase):
    def test_titres_reels_le_crocodeal(self):
        self.assertEqual(ids("Où commander les Pokébox Pokémon 30 ans Amphinobi-ex et Nymphali-ex ?"),
                         # le modèle aléatoire est l'un des deux : il est concerné aussi
                         ["ann30_pokebox_aleatoire", "ann30_pokebox_amphinobi", "ann30_pokebox_nymphali"])
        self.assertEqual(ids("Coffrets Pokémon 30 ans Nymphali et Amphinobi : où les trouver en stock ?"),
                         ["ann30_coffret_amphinobi", "ann30_coffret_nymphali"])
        self.assertEqual(ids("Coffrets Ultra-Premium Pokémon 30 ans Mentali et Noctali : date de sortie"),
                         ["ann30_upc_journee", "ann30_upc_soiree"])
        self.assertEqual(ids("Pokémon 30 ans : où acheter les coffrets avec Figurine Mew et Mewtwo ?"),
                         ["ann30_figurine_mew", "ann30_figurine_mewtwo"])
        self.assertEqual(ids("Coffret Classeur Pokémon 30ᵉ Anniversaire : informations et liens d’achat"),
                         ["ann30_classeur"])
        # Aucune variante nommée : toutes les variantes sont concernées.
        self.assertEqual(ids("Où acheter les coffrets Tech Stickers (Autocollant Réajustable) Pokémon 30 ans ?"),
                         ["ann30_autocollant_aleatoire", "ann30_autocollant_lucario", "ann30_autocollant_noadkoko"])
        # Une variante nommée exclut les autres.
        self.assertEqual(ids("Restock figurine Mewtwo 30 ans"), ["ann30_figurine_mewtwo"])
        self.assertEqual(ids("UPC 30 ans Noctali dispo"), ["ann30_upc_soiree"])
        self.assertEqual(ids("Coffret 30 ans en promo"), [])  # trop vague

    def test_autre_gamme_ignoree(self):
        self.assertEqual(ids("Où acheter le Coffret Dresseur d’Élite (ETB) Pokémon ME07 Poings Fluides ?"), [])
        self.assertEqual(ids("Peluche Pikachu 30 cm"), [])

    def test_message_de_restock(self):
        texte = "🚨 Restock ETB 30 ans chez Carrefour Écully (69130), 12 exemplaires en rayon"
        self.assertEqual(ids(texte), ["ann30_etb"])
        self.assertEqual(magasin_cite(texte), "Carrefour")
        self.assertEqual(code_postal(texte), "69130")
        self.assertEqual(magasin_cite("arrivage Maison de la Presse gare"), "Maison de la Presse")

    def test_ean_dans_le_texte(self):
        self.assertEqual(ids("Réassort EAN 0196214145221 dispo"), ["ann30_lot_boosters"])

    def test_alerte_style_alert_and_go(self):
        # Format observé dans le salon d'annonces « pokémon » d'Alert&Go (texte reformulé).
        texte = ("@CartesPokemon Invitation : Collection Ultra-Premium 30ᵉ Anniversaire – Soirée\n"
                 "Prix: 229,99 € Amazon FR ASIN: B0H8SZV8L7 • Lien 1 • Lien 2")
        self.assertEqual(ids(texte), ["ann30_upc_soiree"])
        self.assertEqual(ids("Vente réservée : MINI TIN - POKEMON - 30 ans & BUNDLE 6 BOOSTERS micromania"),
                         ["ann30_lot_boosters", "ann30_mini_boite"])


class TestDates(unittest.TestCase):
    def test_dates_citees(self):
        ref = date(2026, 10, 12)
        self.assertEqual(dates_citees("Prévus le vendredi 6 novembre, repoussés au 27 novembre", ref),
                         [date(2026, 11, 6), date(2026, 11, 27)])
        self.assertEqual(dates_citees("vente le 09/12 à 10h", date(2026, 11, 19)), [date(2026, 12, 9)])
        self.assertEqual(dates_citees("sortie le 1er février 2027", ref), [date(2027, 2, 1)])
        self.assertEqual(dates_citees("carte 116/128, 1/2 prix", ref), [])

    def test_infobox_pokepedia(self):
        wt = "{{Infobox Produit JCC\n| date-amnord = x\n| date-france = {{#time:d F Y|2026-09-16}}\n| EAN=0196214144835\n}}"
        self.assertEqual(lire_infobox(wt, date(2026, 11, 26)), (date(2026, 9, 16), "0196214144835"))
        self.assertEqual(lire_infobox("| date-france = 6 novembre 2026", date(2026, 11, 26)), (date(2026, 11, 6), None))


def faux_pokepedia(pages: dict[str, str]):
    """API MediaWiki simulée : pages = titre -> wikitexte."""
    def get(url, params):
        if params.get("list") == "embeddedin":
            return json.dumps({"query": {"embeddedin": [{"title": t} for t in pages]}}).encode()
        titres = params["titles"].split("|")
        return json.dumps({"query": {"pages": [
            {"title": t, "revisions": [{"slots": {"main": {"content": pages[t]}}}]} for t in titres
        ]}}).encode()
    return get


def infobox(jour: str, ean: str = "") -> str:
    return f"{{{{Infobox Produit JCC\n| date-france = {{{{#time:d F Y|{jour}}}}}\n| EAN={ean}\n}}}}"


class TestCalendrier(unittest.TestCase):
    def test_correspondance_par_titre_et_ean(self):
        cal = CalendrierPokepedia(ConfigSource(cache_secondes=0), get=faux_pokepedia({
            "Coffret Dresseur d'élite 30e Anniversaire": infobox("2026-09-16"),
            "Collection autocollant réajustable 30e Anniversaire Lucario": infobox("2026-11-06", "0196214144972"),
            "Coffret Dresseur d'élite Méga-Évolution": infobox("2026-01-30"),  # autre gamme : ignorée
        }))
        trouves = {(d.produit_id, d.date_sortie) for d in cal.dates(CATALOGUE)}
        self.assertEqual(trouves, {
            ("ann30_etb", date(2026, 9, 16)),
            ("ann30_autocollant_lucario", date(2026, 11, 6)),
            ("ann30_autocollant_aleatoire", date(2026, 11, 6)),  # rattaché par son EAN
        })


RSS = """<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>FICTIF</title>{items}</channel></rss>"""


def item(titre, lien, date_rss="Mon, 23 Nov 2026 10:00:00 +0000", desc="Résumé fictif."):
    return f"<item><title>{titre}</title><link>{lien}</link><pubDate>{date_rss}</pubDate><description>{desc}</description></item>"


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Parametres(mode="reel", chemin_db=Path(self.tmp.name) / "v.sqlite3",
                            chemin_catalogue=RACINE / "data" / "catalogue.csv")
        self.base = BaseDonnees(self.p.chemin_db)
        self.comp = Comparateur(self.p, connecteurs=[], base=self.base)
        self.pages = {"Coffret Dresseur d'élite 30e Anniversaire": infobox("2026-09-16")}
        self.rss = [item("Pokébox Pokémon 30 ans Nymphali-ex : où commander ?", "https://exemple.invalid/a")]
        self.cal = CalendrierPokepedia(ConfigSource(cache_secondes=0), get=lambda u, p: faux_pokepedia(self.pages)(u, p))
        flux = FluxAnnonces("lecrocodeal", "fictif", "https://exemple.invalid/rss", lambda t, x: True,
                            config=ConfigSource(cache_secondes=0),
                            get=lambda u, p: RSS.format(items="".join(self.rss)).encode())
        self.v = ServiceVeille(self.p, self.comp, self.base, calendrier=self.cal, flux=[flux])
        # Membre 1 : alerte sur l'ETB ; membre 2 : favori Pokébox Nymphali et ETB.
        self.base.creer_alerte(1, "ann30_etb", __import__("decimal").Decimal("60"), 60, salon_id=99)
        self.base.ajouter_favori(2, "ann30_pokebox_nymphali")
        self.base.ajouter_favori(2, "ann30_etb")

    def tearDown(self):
        self.tmp.cleanup()

    def test_premiere_lecture_silencieuse_puis_nouveautes(self):
        instant = datetime(2026, 11, 26, 12, tzinfo=UTC)
        self.assertEqual(self.v.actualiser(instant), [])  # existant mémorisé, rien envoyé
        self.assertEqual(self.v.actualiser(instant), [])  # rien de nouveau

        self.pages["Coffret Dresseur d'élite 30e Anniversaire"] = infobox("2026-12-04")  # report
        self.rss.append(item("Pokébox 30 ans Nymphali-ex : réassort annoncé le 3 décembre",
                             "https://exemple.invalid/b"))
        envois = self.v.actualiser(instant)
        par_type = sorted((e.annonce.type, e.utilisateur_id) for e in envois)
        self.assertEqual(par_type, [(INFO, 2), (SORTIE, 1), (SORTIE, 2)])
        report = next(e for e in envois if e.annonce.type == SORTIE)
        self.assertIn("16/09/2026 → 04/12/2026", report.annonce.titre)
        self.assertEqual(next(e for e in envois if e.utilisateur_id == 1).salon_id, 99)
        info = next(e.annonce for e in envois if e.annonce.type == INFO)
        self.assertEqual(info.dates, [date(2026, 12, 3)])

    def test_rappel_la_veille_une_seule_fois(self):
        self.v.actualiser(datetime(2026, 9, 1, tzinfo=UTC))
        veille = datetime(2026, 9, 15, 9, tzinfo=UTC)
        envois = self.v.actualiser(veille)
        self.assertEqual(sorted(e.utilisateur_id for e in envois), [1, 2])
        self.assertTrue(envois[0].annonce.titre.startswith("Sortie prévue demain"))
        self.assertEqual(self.v.actualiser(veille), [])

    def test_drop_membre(self):
        etb = self.comp.produit("ann30_etb")
        a, envois, err = self.v.signaler_drop(2, etb, "Carrefour Écully", "69130", "3 ETB en rayon")
        self.assertIsNone(err)
        self.assertEqual([e.utilisateur_id for e in envois], [1])  # l'auteur n'est pas notifié
        _, _, err = self.v.signaler_drop(2, etb, "Carrefour Écully")
        self.assertIn("déjà signalé", err)
        liste, stats = self.v.drops(etb)
        self.assertEqual(len(liste), 1)
        self.assertEqual(stats[0][0], "Carrefour Écully")
        texte = formater_annonce(a, [etb])
        self.assertIn("non vérifié", texte)
        self.assertIn("Carrefour Écully", formater_drops(liste, stats, {etb.id: etb}, etb))
        self.base.oublier_utilisateur(2)
        self.assertIsNone(self.base.annonces(types=(DROP,))[0].utilisateur_id)

    def test_message_salon_suivi(self):
        instant = datetime(2026, 11, 26, 8, tzinfo=UTC)
        texte = "RESTOCK 🔥\nETB 30 ans en rayon chez Leclerc Rennes (35000) ce matin"
        envois = self.v.traiter_message("123", texte, "https://discord.com/channels/1/2/123", instant)
        self.assertEqual(sorted(e.utilisateur_id for e in envois), [1, 2])
        a = envois[0].annonce
        self.assertEqual((a.type, a.magasin, a.ville), (DROP, "E.Leclerc", "35000"))
        self.assertEqual(self.v.traiter_message("123", texte, None, instant), [])  # même message : ignoré
        self.assertEqual(self.v.traiter_message("124", "Bonne journée à tous", None, instant), [])

    def test_calendrier_affiche(self):
        self.v.actualiser(datetime(2026, 11, 26, tzinfo=UTC))
        texte = formater_sorties(self.v.sorties(), {}, markdown=False)
        self.assertIn("Coffret Dresseur d'élite 30ᵉ Anniversaire — 16/09/2026", texte)
        self.assertIn("date non trouvée", texte)

    def test_demo_sans_reseau(self):
        p = Parametres(mode="demo", chemin_db=Path(self.tmp.name) / "d.sqlite3")
        base = BaseDonnees(p.chemin_db)
        v = ServiceVeille(p, Comparateur(p, base=base), base)
        self.assertIsNone(v.calendrier)
        self.assertEqual(v.flux, [])
        self.assertEqual(v.actualiser(), [])


if __name__ == "__main__":
    unittest.main()
