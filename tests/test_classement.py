import unittest

from pokebot.analyse import Avis, construire_rapport, meilleure_offre
from pokebot.config import Seuils
from pokebot.models import (
    Disponibilite, Etat, Preferences, StatutLivraison, TypeVendeur,
)

from .outils import D, offre, offre_amazon, produit_etb

S = Seuils()


def codes(ligne):
    return {s.code for s in ligne.signaux}


class TestRapport(unittest.TestCase):
    def setUp(self):
        self.produit = produit_etb()
        self.offres = [
            offre_amazon("60.00", url="https://exemple.invalid/amazon"),
            offre(site="fnac.com", prix=D("58.00"), url="https://exemple.invalid/fnac"),
            offre(site="cultura.com", prix=D("59.00"), url="https://exemple.invalid/cultura"),
            offre(site="joueclub.fr", prix=D("50.00"), url="https://exemple.invalid/joueclub"),
            offre(site="king-jouet.com", prix=D("40.00"), url="https://exemple.invalid/rupture",
                  disponibilite=Disponibilite.RUPTURE),
            offre(site="fnac.com", prix=D("55.00"), url="https://exemple.invalid/occasion", etat=Etat.OCCASION,
                  vendeur="V", type_vendeur=TypeVendeur.MARKETPLACE, note_vendeur=D("99"), nb_avis_vendeur=500),
            offre(site="fnac.com", prix=D("45.00"), url="https://exemple.invalid/proche", ean=None,
                  titre="Coffret Dresseur d'élite Test lot de 2"),
            offre(site="fnac.com", prix=D("20.00"), url="https://exemple.invalid/arnaque",
                  vendeur="Inconnu", type_vendeur=TypeVendeur.MARKETPLACE),
            offre(site="fnac.com", prix=D("30.00"), url="https://exemple.invalid/autre", ean="2000000000022",
                  titre="Booster Test"),
        ]
        self.r = construire_rapport(self.produit, self.offres, S)
        self.par_url = {l.offre.url.rsplit("/", 1)[1]: l for l in self.r.lignes}

    def test_produit_different_ecarte(self):
        self.assertEqual(self.r.annonces_ecartees, 1)
        self.assertNotIn("autre", self.par_url)

    def test_reference_amazon_et_mediane(self):
        self.assertEqual(self.r.ref_amazon.montant, D("60.00"))
        self.assertFalse(self.r.ref_amazon.vendeur_tiers)
        # Offres comparables, disponibles, de vendeurs fiables : 50, 58, 59, 60 → médiane 58,50.
        self.assertEqual(self.r.mediane, D("58.50"))
        self.assertEqual(self.r.nb_offres_mediane, 4)

    def test_classement(self):
        ordre = [l.offre.url.rsplit("/", 1)[1] for l in self.r.lignes]
        # D'abord les offres fiables en stock, du moins cher au plus cher…
        self.assertEqual(ordre[:4], ["joueclub", "fnac", "cultura", "amazon"])
        # …puis à vérifier, correspondance incertaine / état différent, et enfin les ruptures.
        self.assertEqual(ordre[4], "arnaque")
        self.assertEqual(set(ordre[5:7]), {"proche", "occasion"})
        self.assertEqual(ordre[-1], "rupture")
        self.assertEqual(meilleure_offre(self.r).offre.url, "https://exemple.invalid/joueclub")

    def test_avis(self):
        self.assertIs(self.par_url["joueclub"].avis, Avis.TRES_BONNE_AFFAIRE)
        self.assertIs(self.par_url["fnac"].avis, Avis.RAISONNABLE)
        self.assertIs(self.par_url["arnaque"].avis, Avis.A_VERIFIER)
        self.assertIn("PRIX_ANORMAL", codes(self.par_url["arnaque"]))
        self.assertIn("VENDEUR_INCONNU", codes(self.par_url["arnaque"]))
        self.assertIs(self.par_url["proche"].avis, Avis.A_VERIFIER)
        self.assertIs(self.par_url["occasion"].avis, Avis.INSUFFISANT)

    def test_ecart_amazon(self):
        l = self.par_url["joueclub"]
        self.assertEqual(l.ecart_amazon_eur, D("-10.00"))
        self.assertEqual(l.ecart_amazon_pct, D("-16.7"))


class TestReferenceAmazon(unittest.TestCase):
    def test_prefere_vendu_par_amazon_a_un_tiers_moins_cher(self):
        offres = [
            offre_amazon("60"),
            offre_amazon("55", vendeur="Tiers", type_vendeur=TypeVendeur.AMAZON_TIERS,
                         note_vendeur=D("99"), nb_avis_vendeur=1000),
        ]
        r = construire_rapport(produit_etb(), offres, S)
        self.assertEqual(r.ref_amazon.montant, D("60.00"))

    def test_tiers_fiable_si_amazon_en_rupture_et_signale(self):
        offres = [
            offre_amazon("50", disponibilite=Disponibilite.RUPTURE),
            offre_amazon("65", vendeur="Tiers", type_vendeur=TypeVendeur.AMAZON_TIERS,
                         note_vendeur=D("99"), nb_avis_vendeur=1000),
        ]
        r = construire_rapport(produit_etb(), offres, S)
        self.assertEqual(r.ref_amazon.montant, D("65.00"))
        self.assertTrue(r.ref_amazon.vendeur_tiers)
        tiers = next(l for l in r.lignes if l.offre.vendeur == "Tiers")
        self.assertIn("VENDEUR_TIERS_AMAZON", codes(tiers))

    def test_tiers_sans_reputation_jamais_reference(self):
        offres = [offre_amazon("30", vendeur="Tiers", type_vendeur=TypeVendeur.AMAZON_TIERS)]
        self.assertIsNone(construire_rapport(produit_etb(), offres, S).ref_amazon)

    def test_mediane_exige_trois_offres(self):
        r = construire_rapport(produit_etb(), [offre_amazon("60"), offre(prix=D("55"))], S)
        self.assertIsNone(r.mediane)
        fnac = next(l for l in r.lignes if l.offre.site == "fnac.com")
        self.assertIs(fnac.avis, Avis.RAISONNABLE)  # une seule référence : plafonné

    def test_livraison_inconnue_exclue_de_la_mediane_et_a_verifier(self):
        offres = [offre_amazon("60"), offre(prix=D("58")), offre(prix=D("59")),
                  offre(prix=D("40"), livraison=None, statut_livraison=StatutLivraison.INCONNUE, url="x")]
        r = construire_rapport(produit_etb(), offres, S)
        self.assertEqual(r.mediane, D("59.00"))
        inconnue = next(l for l in r.lignes if l.offre.url == "x")
        self.assertIs(inconnue.avis, Avis.A_VERIFIER)


class TestFaussesAffaires(unittest.TestCase):
    def test_mots_suspects(self):
        for mot in ("copie", "Reproduction", "PROXY", "personnalisé"):
            r = construire_rapport(produit_etb(), [offre(description=f"carte {mot}")], S)
            self.assertIn("MOTS_SUSPECTS", codes(r.lignes[0]), mot)
            self.assertIs(r.lignes[0].avis, Avis.A_VERIFIER)

    def test_ouvert_vendu_comme_scelle(self):
        r = construire_rapport(produit_etb(), [offre(titre="Coffret Dresseur d'élite Test (boîte ouverte)")], S)
        self.assertIn("OUVERT_VENDU_SCELLE", codes(r.lignes[0]))

    def test_sans_reference(self):
        r = construire_rapport(produit_etb(), [offre(ean=None)], S)
        self.assertIn("SANS_REFERENCE", codes(r.lignes[0]))

    def test_frais_de_port_eleves_signales(self):
        r = construire_rapport(produit_etb(), [offre(prix=D("10"), livraison=D("6"))], S)
        self.assertIn("FRAIS_PORT_ELEVES", codes(r.lignes[0]))

    def test_langue_et_etat_differents_des_preferences(self):
        prefs = Preferences(langue="fr", etat=Etat.NEUF)
        r = construire_rapport(produit_etb(), [offre(etat=Etat.OCCASION, langue="en")], S, prefs)
        self.assertTrue({"ETAT_DIFFERENT", "LANGUE_DIFFERENTE"} <= codes(r.lignes[0]))


if __name__ == "__main__":
    unittest.main()
