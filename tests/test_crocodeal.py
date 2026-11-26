"""Connecteur Le CrocoDeal : flux RSS FICTIF (aucun appel réseau), signalements et alertes dédiées."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pokebot.affichage import formater_notification, formater_rapport
from pokebot.alertes import EtatAlerte, evaluer_alerte
from pokebot.analyse import Avis, construire_rapport
from pokebot.base import BaseDonnees
from pokebot.config import ConfigSource, Parametres, Seuils
from pokebot.connecteurs import Requete, construire_connecteurs
from pokebot.connecteurs.base import ErreurSource
from pokebot.connecteurs.lecrocodeal import ConnecteurCrocoDeal, enseigne, lire_flux, pertinent, prix_annonce
from pokebot.models import Disponibilite, StatutLivraison, TypeVendeur

from .outils import D, offre, offre_amazon, produit_etb

UTC = timezone.utc
MAINTENANT = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
PREAMBULE = "&lt;p&gt;Ce deal a été publié par un membre de la communauté Le CrocoDeal.&lt;/p&gt;"


def item(titre, desc, date="Wed, 25 Nov 2026 10:00:00 +0000", lien="https://lecrocodeal.com/deal-fictif"):
    return (f"<item><title>{titre}</title><link>{lien}</link><pubDate>{date}</pubDate>"
            f"<description>{PREAMBULE}&lt;p&gt;{desc}&lt;/p&gt;</description></item>")


FLUX = ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>FICTIF</title>" + "".join([
    item("Coffret Dresseur d’élite Test à 44,99€", "Bon plan chez Fnac : le coffret passe à 44,99€ au lieu de 59,99€.",
         lien="https://lecrocodeal.com/etb-test-fnac"),
    item("Où acheter le Coffret Dresseur d’élite Test ?", "Disponible à 59,99€ chez Amazon.",
         lien="https://lecrocodeal.com/etb-test-ou-acheter"),
    item("Coffret Dresseur d’élite Test", "Chez FNAC et chez Amazon, il est disponible à 49,99€ au lieu de 59,99€.",
         lien="https://lecrocodeal.com/etb-test-deux-enseignes"),
    item("Coffret Dresseur d’élite Test à 39,99€", "Ancien bon plan chez Cdiscount.",
         date="Thu, 01 Oct 2026 10:00:00 +0000", lien="https://lecrocodeal.com/etb-test-ancien"),
    item("Peluche Pikachu géante", "Nouvelle peluche annoncée.", lien="https://lecrocodeal.com/peluche"),
    item("Coffret Dresseur d’élite Test à 19,99€", "Chez Cdiscount.", lien="https://exemple.invalid/ailleurs"),
]) + "</channel></rss>").encode("utf-8")


def signalement(prix: str, date: datetime, titre="Coffret Dresseur d'élite Test", **kw):
    kw = {
        "source": "lecrocodeal", "site": "fnac.com", "titre": titre, "url": "https://lecrocodeal.com/x",
        "prix": D(prix), "livraison": None, "statut_livraison": StatutLivraison.INCONNUE, "vendeur": None,
        "type_vendeur": TypeVendeur.INCONNU, "disponibilite": Disponibilite.INCONNUE, "ean": None,
        "verifie_le": date, "signalement": True, **kw,
    }
    return offre(**kw)


class TestLectureFlux(unittest.TestCase):
    def test_bons_plans_retenus(self):
        offres = lire_flux(FLUX, age_max=timedelta(days=14), maintenant=MAINTENANT)
        self.assertEqual([(o.url.rsplit("/", 1)[1], o.site, o.prix) for o in offres], [
            ("etb-test-fnac", "fnac.com", D("44.99")),
            ("etb-test-deux-enseignes", "lecrocodeal.com", D("49.99")),  # deux enseignes citées : non attribué
        ])
        self.assertTrue(all(o.signalement and o.type_vendeur is TypeVendeur.INCONNU for o in offres))
        self.assertTrue(all(o.livraison is None and o.disponibilite is Disponibilite.INCONNUE for o in offres))
        self.assertNotIn("Ce deal a été publié", offres[0].description)

    def test_sans_limite_d_age_l_ancien_bon_plan_revient(self):
        self.assertEqual(len(lire_flux(FLUX, maintenant=MAINTENANT)), 3)

    def test_prix_annonce_jamais_le_prix_barre(self):
        self.assertEqual(prix_annonce("Sac à dos", "passe à 14,99€ au lieu de 27,99€"), D("14.99"))
        self.assertEqual(prix_annonce("Casque à 266,93€", "au lieu de 359,99€"), D("266.93"))
        self.assertIsNone(prix_annonce("Coffret", "Prix habituel : au lieu de 27,99€"))
        self.assertIsNone(prix_annonce("Garage à 50 voitures", "rangement"))

    def test_enseigne(self):
        self.assertEqual(enseigne("Bon plan Amazon !"), "amazon.fr")
        self.assertEqual(enseigne("chez King Jouet"), "king-jouet.com")
        self.assertIsNone(enseigne("chez FNAC et chez Amazon"))
        self.assertIsNone(enseigne("aucune enseigne"))

    def test_xml_invalide(self):
        with self.assertRaises(ErreurSource):
            lire_flux(b"<html>erreur</html")


class TestConnecteur(unittest.TestCase):
    def test_un_seul_telechargement_et_pertinence(self):
        appels = []

        def telecharger(terme):
            appels.append(terme)
            return FLUX

        c = ConnecteurCrocoDeal(ConfigSource(delai_entre_requetes_secondes=0, cache_secondes=600), telecharger)
        trouves = c.rechercher(Requete("Coffret Dresseur d'élite Test"))
        self.assertGreaterEqual(len(trouves), 2)
        self.assertEqual(c.rechercher(Requete("Peluche Ronflex")), [])
        self.assertEqual(appels, ["pokemon"])  # flux lu une seule fois pour toutes les recherches

    def test_pertinence_titre_long(self):
        o = signalement("48.99", MAINTENANT, titre="LEGO Pokémon Smart Play 72164 – Pikachu et la cabane d’entraînement")
        self.assertTrue(pertinent(o, "lego pikachu"))
        self.assertFalse(pertinent(o, "lego dracaufeu"))

    def test_enregistre_en_mode_reel_seulement(self):
        reel = [c.id for c in construire_connecteurs(Parametres(mode="reel"))]
        demo = [c.id for c in construire_connecteurs(Parametres(mode="demo"))]
        self.assertIn("lecrocodeal", reel)
        self.assertNotIn("lecrocodeal", demo)


class TestAnalyseEtAlertes(unittest.TestCase):
    def rapport(self, *offres):
        return construire_rapport(produit_etb(), list(offres), Seuils())

    def test_jamais_reference_ni_mediane(self):
        r = self.rapport(offre_amazon("59.99"), signalement("44.99", MAINTENANT))
        self.assertEqual(r.ref_amazon.montant, D("59.99"))
        ligne = next(l for l in r.lignes if l.offre.signalement)
        self.assertIs(ligne.avis, Avis.A_VERIFIER)
        self.assertIn("SIGNALEMENT_COMMUNAUTE", [s.code for s in ligne.signaux])
        texte = formater_rapport(r, markdown=False)
        self.assertIn("bon plan Le CrocoDeal", texte)
        self.assertIn("publié le", texte)

    def test_signalement_notifie_une_fois(self):
        avant = MAINTENANT - timedelta(days=1)
        # Première vérification : on mémorise la date sans notifier les bons plans déjà publiés.
        notifs, etat = evaluer_alerte(self.rapport(signalement("44.99", avant)), D("50"), EtatAlerte())
        self.assertEqual(notifs, [])
        self.assertGreaterEqual(etat.dernier_signalement, avant)

        etat = EtatAlerte(dernier_signalement=avant)
        r = self.rapport(signalement("44.99", MAINTENANT))
        notifs, etat = evaluer_alerte(r, D("50"), etat)
        self.assertEqual([n.type for n in notifs], ["signalement"])
        self.assertEqual(etat.dernier_signalement, MAINTENANT)
        message = formater_notification(notifs[0], r, D("50"))
        self.assertIn("Le CrocoDeal", message)
        self.assertIn("non vérifié", message)
        notifs, _ = evaluer_alerte(r, D("50"), etat)
        self.assertEqual(notifs, [])  # déjà vu

    def test_signalement_ecarte(self):
        etat = EtatAlerte(dernier_signalement=MAINTENANT - timedelta(days=1))
        for o in (
            signalement("54.99", MAINTENANT),  # au-dessus du prix maximum
            signalement("44.99", MAINTENANT, titre="Coffret Dresseur d'élite Test proxy"),  # copie
            signalement("44.99", MAINTENANT, titre="Peluche Ronflex géante"),  # autre produit
        ):
            notifs, _ = evaluer_alerte(self.rapport(o), D("50"), etat)
            self.assertEqual(notifs, [], o.titre)

    def test_signalement_ne_declenche_pas_l_alerte_prix(self):
        etat = EtatAlerte(dernier_signalement=MAINTENANT)
        notifs, etat = evaluer_alerte(self.rapport(signalement("44.99", MAINTENANT)), D("50"), etat)
        self.assertEqual(notifs, [])
        self.assertIsNone(etat.dernier_total_notifie)


class TestMigrationBase(unittest.TestCase):
    def test_colonne_ajoutee_a_une_base_existante(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "ancienne.sqlite3"
            cnx = sqlite3.connect(chemin)
            cnx.execute(
                "CREATE TABLE alertes (id INTEGER PRIMARY KEY AUTOINCREMENT, utilisateur_id INTEGER NOT NULL,"
                " salon_id INTEGER, produit_id TEXT NOT NULL, prix_max TEXT NOT NULL, etat TEXT, langue TEXT,"
                " sites TEXT NOT NULL DEFAULT '[]', frequence_minutes INTEGER NOT NULL, derniere_verif TEXT,"
                " dernier_total_notifie TEXT, etait_disponible INTEGER, active INTEGER NOT NULL DEFAULT 1,"
                " creee_le TEXT NOT NULL)"
            )
            cnx.commit()
            cnx.close()
            base = BaseDonnees(chemin)
            ident = base.creer_alerte(1, "etb", D("50"), 60)
            base.maj_etat_alerte(ident, EtatAlerte(dernier_signalement=MAINTENANT))
            self.assertEqual(base.alertes(1)[0].etat_alerte.dernier_signalement, MAINTENANT)


if __name__ == "__main__":
    unittest.main()
