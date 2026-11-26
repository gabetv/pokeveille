"""Bout en bout en mode démo : données fictives, base SQLite temporaire, sans clé API."""

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from pokebot import __main__ as cli
from pokebot.affichage import decouper, formater_rapport, formater_resume
from pokebot.analyse import Avis
from pokebot.base import BaseDonnees
from pokebot.comparateur import Comparateur
from pokebot.config import Parametres
from pokebot.connecteurs import Requete
from pokebot.connecteurs.amazon import convertir_items
from pokebot.csv_io import COLONNES_CATALOGUE, COLONNES_OFFRES
from pokebot.models import Disponibilite, Etat, Preferences, TypeVendeur

RACINE = Path(__file__).resolve().parent.parent


class TestDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p = Parametres(mode="demo", chemin_db=Path(cls.tmp.name) / "test.sqlite3")
        cls.base = BaseDonnees(cls.p.chemin_db)
        cls.comp = Comparateur(cls.p, base=cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def avis_par_site(self, produit_id):
        r = self.comp.rapport(self.comp.produit(produit_id))
        return r, [(l.offre.site, l.avis) for l in r.lignes]

    def test_fichiers_demo_bien_formes(self):
        for nom, colonnes in (("catalogue_demo.csv", COLONNES_CATALOGUE), ("offres_demo.csv", COLONNES_OFFRES)):
            with (RACINE / "data" / "demo" / nom).open(encoding="utf-8") as f:
                lignes = list(csv.reader(f))
            self.assertEqual(lignes[0], colonnes, nom)
            for n, ligne in enumerate(lignes[1:], start=2):
                self.assertEqual(len(ligne), len(colonnes), f"{nom} ligne {n}")

    def test_toutes_les_donnees_demo_sont_marquees_fictives(self):
        self.assertTrue(all(p.demo and p.nom.startswith("DÉMO") for p in self.comp.catalogue))
        r = self.comp.rapport(self.comp.produit("demo_etb"))
        self.assertTrue(r.demo)
        self.assertTrue(all(l.offre.demo and ".invalid/" in l.offre.url for l in r.lignes))
        self.assertIn("DONNÉES FICTIVES", formater_rapport(r, markdown=False))

    def test_coffret(self):
        r, lignes = self.avis_par_site("demo_etb")
        self.assertEqual(lignes[0], ("joueclub.fr", Avis.TRES_BONNE_AFFAIRE))
        self.assertEqual(r.ref_amazon.montant, Decimal("59.99"))
        self.assertFalse(r.ref_amazon.vendeur_tiers)
        self.assertEqual(r.mediane, Decimal("59.89"))
        # L'offre à 24,90 € (vendeur inconnu) n'est jamais une bonne affaire.
        arnaque = next(l for l in r.lignes if l.offre.prix == Decimal("24.90"))
        self.assertIs(arnaque.avis, Avis.A_VERIFIER)

    def test_booster_reference_tiers_et_cher(self):
        r, lignes = self.avis_par_site("demo_booster")
        self.assertTrue(r.ref_amazon.vendeur_tiers)  # Amazon en rupture
        self.assertIn(("king-jouet.com", Avis.CHER), lignes)

    def test_version_import_separee(self):
        r, lignes = self.avis_par_site("demo_etb_en")
        self.assertEqual({s for s, _ in lignes}, {"amazon.fr", "fnac.com"})
        self.assertIn(("fnac.com", Avis.UN_PEU_CHER), lignes)

    def test_cartes(self):
        r, lignes = self.avis_par_site("demo_carte")
        self.assertIsNone(r.ref_amazon)
        self.assertEqual(r.mediane, Decimal("13.20"))
        self.assertEqual(lignes[0][1], Avis.TRES_BONNE_AFFAIRE)
        self.assertEqual(len(r.ventes_reelles), 3)
        self.assertEqual(r.mediane_ventes, Decimal("11.00"))
        r, lignes = self.avis_par_site("demo_carte_psa10")
        self.assertEqual(lignes, [("cardmarket.com", Avis.INSUFFISANT)])

    def test_filtre_sites(self):
        r = self.comp.rapport(self.comp.produit("demo_etb"), Preferences(sites=["fnac.com"]))
        self.assertTrue(r.lignes)
        self.assertTrue(all(l.offre.site == "fnac.com" for l in r.lignes))
        # La référence Amazon et la médiane restent calculées sur tout le marché.
        self.assertEqual(r.ref_amazon.montant, Decimal("59.99"))
        self.assertEqual(r.mediane, Decimal("59.89"))

    def test_recherche_catalogue(self):
        self.assertEqual(len(self.comp.chercher_dans_catalogue("coffret")), 3)
        self.assertEqual([p.id for p in self.comp.chercher_dans_catalogue("peluche")], ["demo_peluche"])
        self.assertEqual(len(self.comp.chercher_dans_catalogue("pikachu", categorie="carte gradée")), 1)
        self.assertEqual(len(self.comp.produits_anniversaire()), 7)

    def test_affichage_markdown_et_decoupage(self):
        rapports = [self.comp.rapport(p) for p in self.comp.produits_anniversaire()]
        texte = formater_resume(rapports)
        self.assertIn("**", texte)
        self.assertIn("`/fiche produit:demo_etb`", texte)
        fiche = formater_rapport(rapports[0])
        self.assertIn("(<https://exemple.invalid/", fiche)  # liens masqués, sans aperçu
        self.assertIn("Dresseur d'élite", fiche)
        long = "\n\n".join(formater_rapport(r) for r in rapports)
        morceaux = decouper(long)
        self.assertGreater(len(morceaux), 1)
        self.assertTrue(all(len(m) <= 2000 for m in morceaux))

    def test_echappement_markdown(self):
        from pokebot.affichage import Rendu
        self.assertEqual(Rendu(True).t("a*b_c`d"), r"a\*b\_c\`d")
        self.assertEqual(Rendu(False).t("a*b"), "a*b")

    def test_historique_enregistre_sans_doublon(self):
        produit = self.comp.produit("demo_upc")
        self.comp.rapport(produit)
        n = len(self.base.historique("demo_upc"))
        self.assertGreater(n, 0)
        self.comp.rapport(produit)
        self.assertEqual(len(self.base.historique("demo_upc")), n)

    def test_cli_demo(self):
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            code = cli.main(["demo"])
        self.assertEqual(code, 0)
        self.assertIn("Gamme 30e anniversaire", sortie.getvalue())


class TestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = BaseDonnees(Path(self.tmp.name) / "b.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_preferences_favoris_alertes(self):
        self.base.enregistrer_preferences(1, Preferences(prix_max=Decimal("50"), etat=Etat.NEUF, sites=["fnac.com"]))
        prefs = self.base.preferences(1)
        self.assertEqual((prefs.prix_max, prefs.etat, prefs.sites), (Decimal("50"), Etat.NEUF, ["fnac.com"]))
        self.base.ajouter_favori(1, "demo_etb")
        self.assertEqual(self.base.favoris(1), ["demo_etb"])
        ident = self.base.creer_alerte(1, "demo_etb", Decimal("49.90"), 60)
        self.assertEqual(len(self.base.alertes_a_verifier(15)), 1)
        self.base.maj_etat_alerte(ident, self.base.alertes(1)[0].etat_alerte)
        self.assertEqual(self.base.alertes_a_verifier(15), [])
        plus_tard = datetime.now(timezone.utc) + timedelta(minutes=61)
        self.assertEqual(len(self.base.alertes_a_verifier(15, plus_tard)), 1)
        self.assertFalse(self.base.supprimer_alerte(2, ident))  # pas l'alerte d'un autre utilisateur
        self.base.oublier_utilisateur(1)
        self.assertEqual((self.base.favoris(1), self.base.alertes(1)), ([], []))


class TestAmazon(unittest.TestCase):
    def test_conversion_reponse_creators_api(self):
        items = [{
            "asin": "B0TEST0001",
            "detailPageURL": "https://www.amazon.fr/dp/B0TEST0001?tag=exemple-21",
            "itemInfo": {"title": {"displayValue": "Coffret test"},
                         "externalIds": {"eans": {"displayValues": ["2000000000015"]}}},
            "offersV2": {"listings": [
                {"price": {"money": {"amount": 59.99, "currency": "EUR"}}, "merchantInfo": {"name": "Amazon.fr"},
                 "availability": {"type": "IN_STOCK"}, "condition": {"value": "New"}},
                {"price": {"money": {"amount": 49.0, "currency": "EUR"}}, "merchantInfo": {"name": "Boutique"},
                 "availability": {"type": "PREORDER"}, "condition": {"value": "New"}},
                {"price": {"money": {"amount": 10.0, "currency": "USD"}}},
            ]},
        }]
        offres = convertir_items(items)
        self.assertEqual(len(offres), 2)  # le prix en dollars est ignoré
        self.assertEqual((offres[0].type_vendeur, offres[0].disponibilite, offres[0].etat),
                         (TypeVendeur.AMAZON, Disponibilite.EN_STOCK, Etat.NEUF))
        self.assertEqual(offres[0].prix, Decimal("59.99"))
        self.assertEqual(offres[0].ean, "2000000000015")
        self.assertIs(offres[1].type_vendeur, TypeVendeur.AMAZON_TIERS)
        self.assertIsNone(offres[0].livraison)  # jamais inventée

    def test_amazon_non_configure_signale(self):
        p = Parametres(mode="reel", chemin_catalogue=RACINE / "data" / "catalogue.csv")
        comp = Comparateur(p)
        self.assertIn("non vérifié", comp.statut_amazon())
        amazon = next(c for c in comp.connecteurs if c.id == "amazon_fr")
        self.assertFalse(amazon.actif)
        self.assertEqual(amazon.rechercher(Requete("x")), [])


if __name__ == "__main__":
    unittest.main()
