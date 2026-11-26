import unittest
from decimal import Decimal

from pokebot.analyse import Avis, avis_prix, prix_total
from pokebot.comparateur import appliquer_bareme
from pokebot.config import ConfigSource, Seuils
from pokebot.models import StatutLivraison

from .outils import D, offre

S = Seuils()


class TestPrixTotal(unittest.TestCase):
    def test_livraison_connue(self):
        t = prix_total(offre(prix=D("49.99"), livraison=D("4.99")))
        self.assertEqual(t.montant, D("54.98"))
        self.assertTrue(t.exact)

    def test_frais_obligatoires_ajoutes(self):
        t = prix_total(offre(prix=D("10"), livraison=D("2"), frais_obligatoires=D("0.75")))
        self.assertEqual(t.montant, D("12.75"))

    def test_livraison_inconnue_jamais_exacte(self):
        t = prix_total(offre(prix=D("49.99"), livraison=None, statut_livraison=StatutLivraison.INCONNUE))
        self.assertEqual(t.montant, D("49.99"))
        self.assertFalse(t.exact)
        self.assertEqual(t.mention, "frais de livraison à vérifier")

    def test_livraison_estimee_non_exacte(self):
        t = prix_total(offre(prix=D("20"), livraison=D("3"), statut_livraison=StatutLivraison.ESTIMEE))
        self.assertEqual(t.montant, D("23.00"))
        self.assertFalse(t.exact)

    def test_prix_inconnu(self):
        t = prix_total(offre(prix=None))
        self.assertIsNone(t.montant)

    def test_bareme_utilisateur_donne_une_estimation(self):
        conf = ConfigSource(livraison_estimee=D("4.99"), livraison_gratuite_des=D("35"))
        bas = offre(prix=D("20"), livraison=None, statut_livraison=StatutLivraison.INCONNUE)
        haut = offre(prix=D("40"), livraison=None, statut_livraison=StatutLivraison.INCONNUE)
        appliquer_bareme(bas, conf)
        appliquer_bareme(haut, conf)
        self.assertEqual((bas.livraison, bas.statut_livraison), (D("4.99"), StatutLivraison.ESTIMEE))
        self.assertEqual((haut.livraison, haut.statut_livraison), (D("0"), StatutLivraison.ESTIMEE))

    def test_bareme_ne_remplace_pas_une_livraison_connue(self):
        o = offre(prix=D("20"), livraison=D("1"))
        appliquer_bareme(o, ConfigSource(livraison_estimee=D("9")))
        self.assertEqual(o.livraison, D("1"))


class TestAvis(unittest.TestCase):
    AMZ, MED = D("100"), D("100")

    def avis(self, total, amz=AMZ, med=MED, **kw):
        return avis_prix(D(total), amz, med, S, **kw)[0]

    def test_tres_bonne_affaire_aux_seuils(self):
        self.assertIs(self.avis("90"), Avis.TRES_BONNE_AFFAIRE)

    def test_tres_bonne_affaire_exige_les_deux_conditions(self):
        # 90 % d'Amazon mais 97,8 % de la médiane : pas une très bonne affaire.
        self.assertIs(self.avis("88", amz=D("97.78"), med=D("90")), Avis.RAISONNABLE)

    def test_raisonnable_jusqua_plus_5_pourcent(self):
        self.assertIs(self.avis("105"), Avis.RAISONNABLE)
        self.assertIs(self.avis("100"), Avis.RAISONNABLE)

    def test_un_peu_cher(self):
        self.assertIs(self.avis("108"), Avis.UN_PEU_CHER)
        self.assertIs(self.avis("110"), Avis.UN_PEU_CHER)

    def test_cher_au_dela_de_10_pourcent_des_deux(self):
        self.assertIs(self.avis("110.01"), Avis.CHER)

    def test_pas_cher_si_une_seule_reference_depassee(self):
        self.assertIs(self.avis("112", amz=D("100"), med=D("104")), Avis.UN_PEU_CHER)

    def test_raisonnable_si_proche_d_une_seule_reference(self):
        self.assertIs(self.avis("112", amz=D("100"), med=D("108")), Avis.RAISONNABLE)

    def test_une_seule_reference_plafonne_a_raisonnable(self):
        avis, note = avis_prix(D("50"), D("100"), None, S)
        self.assertIs(avis, Avis.RAISONNABLE)
        self.assertIn("une seule référence", note)

    def test_une_seule_reference_si_option_desactivee(self):
        souple = Seuils(exiger_deux_references=False)
        self.assertIs(avis_prix(D("50"), D("100"), None, souple)[0], Avis.TRES_BONNE_AFFAIRE)

    def test_sans_reference_comparaison_insuffisante(self):
        self.assertIs(avis_prix(D("50"), None, None, S)[0], Avis.INSUFFISANT)

    def test_signal_bloquant_donne_a_verifier(self):
        self.assertIs(self.avis("50", a_verifier=True), Avis.A_VERIFIER)

    def test_carte_ignore_amazon(self):
        self.assertIs(avis_prix(D("50"), D("100"), None, S, carte=True)[0], Avis.INSUFFISANT)
        self.assertIs(avis_prix(D("9"), D("1"), D("10"), S, carte=True)[0], Avis.TRES_BONNE_AFFAIRE)

    def test_seuils_modifiables(self):
        strict = Seuils(tres_bonne_affaire_amazon=Decimal("0.80"))
        self.assertIs(avis_prix(D("85"), D("100"), D("100"), strict)[0], Avis.RAISONNABLE)

    def test_seuil_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            Seuils.depuis_dict({"seuil_imaginaire": 1})


if __name__ == "__main__":
    unittest.main()
