import unittest

from pokebot.alertes import EtatAlerte, evaluer_alerte
from pokebot.analyse import construire_rapport
from pokebot.config import Seuils
from pokebot.models import Disponibilite, StatutLivraison, TypeVendeur

from .outils import D, offre, produit_etb

S = Seuils()


def rapport(*offres):
    return construire_rapport(produit_etb(), list(offres), S)


class TestAlertes(unittest.TestCase):
    def test_notifie_sous_le_prix_max_une_seule_fois(self):
        r = rapport(offre(prix=D("45")))
        notifs, etat = evaluer_alerte(r, D("50"), EtatAlerte())
        self.assertEqual([n.type for n in notifs], ["prix"])
        notifs, etat = evaluer_alerte(r, D("50"), etat)
        self.assertEqual(notifs, [])  # même prix : pas de doublon

    def test_renotifie_si_le_prix_baisse_encore(self):
        _, etat = evaluer_alerte(rapport(offre(prix=D("45"))), D("50"), EtatAlerte())
        notifs, _ = evaluer_alerte(rapport(offre(prix=D("42"))), D("50"), etat)
        self.assertEqual([n.type for n in notifs], ["prix"])

    def test_au_dessus_du_prix_max_pas_de_notification(self):
        notifs, etat = evaluer_alerte(rapport(offre(prix=D("55"))), D("50"), EtatAlerte())
        self.assertEqual(notifs, [])
        self.assertIsNone(etat.dernier_total_notifie)

    def test_retour_en_stock(self):
        _, etat = evaluer_alerte(rapport(offre(prix=D("60"), disponibilite=Disponibilite.RUPTURE)), D("50"), EtatAlerte())
        self.assertFalse(etat.etait_disponible)
        notifs, etat = evaluer_alerte(rapport(offre(prix=D("60"))), D("50"), etat)
        self.assertEqual([n.type for n in notifs], ["stock"])
        self.assertTrue(etat.etait_disponible)

    def test_pas_de_retour_en_stock_a_la_premiere_verification(self):
        notifs, _ = evaluer_alerte(rapport(offre(prix=D("60"))), D("50"), EtatAlerte())
        self.assertEqual(notifs, [])

    def test_copie_ne_declenche_jamais_d_alerte(self):
        notifs, _ = evaluer_alerte(rapport(offre(prix=D("10"), description="reproduction")), D("50"), EtatAlerte())
        self.assertEqual(notifs, [])

    def test_vendeur_inconnu_et_prix_anormal_ne_declenchent_pas_d_alerte(self):
        fiables = [offre(prix=D("60"), url=f"u{i}") for i in range(3)]
        arnaque = offre(prix=D("20"), vendeur="Inconnu", type_vendeur=TypeVendeur.MARKETPLACE, url="arnaque")
        notifs, _ = evaluer_alerte(rapport(*fiables, arnaque), D("50"), EtatAlerte())
        self.assertEqual(notifs, [])

    def test_livraison_inconnue_alerte_quand_meme(self):
        o = offre(prix=D("45"), livraison=None, statut_livraison=StatutLivraison.INCONNUE)
        notifs, _ = evaluer_alerte(rapport(o), D("50"), EtatAlerte())
        self.assertEqual([n.type for n in notifs], ["prix"])
        self.assertEqual(notifs[0].ligne.total.mention, "frais de livraison à vérifier")


if __name__ == "__main__":
    unittest.main()
