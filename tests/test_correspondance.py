import unittest

from pokebot.correspondance import Correspondance, comparer, normaliser_gtin
from pokebot.models import Produit, TypeProduit

from .outils import EAN_AUTRE, EAN_ETB, offre, produit_etb


class TestGtin(unittest.TestCase):
    def test_ean13_valide(self):
        self.assertEqual(normaliser_gtin("2000000000015"), "02000000000015")

    def test_upc12_equivaut_ean13_avec_zero(self):
        self.assertEqual(normaliser_gtin("036000291452"), normaliser_gtin("0036000291452"))

    def test_cle_de_controle_fausse_ignoree(self):
        self.assertIsNone(normaliser_gtin("2000000000016"))

    def test_espaces_et_tirets_toleres(self):
        self.assertEqual(normaliser_gtin("2 000000 000015"), "02000000000015")


class TestCorrespondance(unittest.TestCase):
    def test_ean_identique_exacte(self):
        r = comparer(produit_etb(), offre(titre="Titre marketing très différent"))
        self.assertIs(r.statut, Correspondance.EXACTE)

    def test_ean_different_meme_nom_differente(self):
        r = comparer(produit_etb(), offre(ean=EAN_AUTRE))
        self.assertIs(r.statut, Correspondance.DIFFERENTE)

    def test_ean_identique_mais_langue_contradictoire_a_verifier(self):
        r = comparer(produit_etb(), offre(langue="en"))
        self.assertIs(r.statut, Correspondance.A_VERIFIER)

    def test_asin_identique_exacte(self):
        r = comparer(produit_etb(), offre(ean=None, asin="b0test0001", titre="autre titre"))
        self.assertIs(r.statut, Correspondance.EXACTE)

    def test_nom_exact_sans_identifiant(self):
        r = comparer(produit_etb(), offre(ean=None, titre="POKÉMON JCC – Coffret dresseur d'Élite test"))
        self.assertIs(r.statut, Correspondance.EXACTE)

    def test_nom_exact_langue_inconnue_a_verifier(self):
        r = comparer(produit_etb(), offre(ean=None, langue=None))
        self.assertIs(r.statut, Correspondance.A_VERIFIER)

    def test_nom_exact_autre_langue_differente(self):
        r = comparer(produit_etb(), offre(ean=None, langue="japonais"))
        self.assertIs(r.statut, Correspondance.DIFFERENTE)

    def test_nom_proche_a_verifier(self):
        r = comparer(produit_etb(), offre(ean=None, titre="Coffret Dresseur d'élite Test lot de 2"))
        self.assertIs(r.statut, Correspondance.A_VERIFIER)

    def test_meme_extension_autre_produit_differente(self):
        r = comparer(produit_etb(), offre(ean=None, titre="Booster Test"))
        self.assertIs(r.statut, Correspondance.DIFFERENTE)

    def test_contenu_exige_si_defini(self):
        p = produit_etb(ean=None, contenu="9 boosters")
        self.assertIs(comparer(p, offre(ean=None)).statut, Correspondance.A_VERIFIER)
        self.assertIs(comparer(p, offre(ean=None, contenu="9 boosters")).statut, Correspondance.EXACTE)
        self.assertIs(comparer(p, offre(ean=None, contenu="6 boosters")).statut, Correspondance.DIFFERENTE)


class TestCartes(unittest.TestCase):
    def setUp(self):
        self.carte = Produit(id="c", nom="Pikachu promo", categorie="carte", type=TypeProduit.CARTE,
                             langue="fr", ref_fabricant="TEST-001", etat_carte="NM")
        self.gradee = Produit(id="g", nom="Pikachu promo", categorie="carte gradée", type=TypeProduit.CARTE_GRADEE,
                              langue="fr", ref_fabricant="TEST-001", societe_gradation="PSA", note_gradation="10")

    def _offre_carte(self, **kw):
        base = dict(ean=None, titre="Pikachu promo", ref_fabricant="TEST-001", type=TypeProduit.CARTE, etat_carte="NM")
        base.update(kw)
        return offre(**base)

    def test_meme_carte_meme_etat_exacte(self):
        self.assertIs(comparer(self.carte, self._offre_carte()).statut, Correspondance.EXACTE)

    def test_autre_etat_differente(self):
        self.assertIs(comparer(self.carte, self._offre_carte(etat_carte="EX")).statut, Correspondance.DIFFERENTE)

    def test_etat_non_precise_a_verifier(self):
        self.assertIs(comparer(self.carte, self._offre_carte(etat_carte=None)).statut, Correspondance.A_VERIFIER)

    def test_gradee_meme_societe_meme_note(self):
        o = self._offre_carte(type=TypeProduit.CARTE_GRADEE, etat_carte=None, societe_gradation="PSA", note_gradation="10")
        self.assertIs(comparer(self.gradee, o).statut, Correspondance.EXACTE)

    def test_gradee_autre_note_ou_societe_differente(self):
        for soc, note in (("PSA", "9"), ("CGC", "10")):
            o = self._offre_carte(type=TypeProduit.CARTE_GRADEE, etat_carte=None, societe_gradation=soc, note_gradation=note)
            self.assertIs(comparer(self.gradee, o).statut, Correspondance.DIFFERENTE, (soc, note))

    def test_carte_brute_vs_gradee_differente(self):
        self.assertIs(comparer(self.gradee, self._offre_carte()).statut, Correspondance.DIFFERENTE)


if __name__ == "__main__":
    unittest.main()
