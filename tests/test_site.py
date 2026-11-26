"""Version « site + webhook » : suivi.toml, envoi par webhook, génération du site (sans réseau)."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pokebot.base import BaseDonnees
from pokebot.comparateur import Comparateur
from pokebot.config import Parametres
from pokebot.service_veille import ServiceVeille
from pokebot.tache import SALON, charger_suivi, executer, synchroniser
from pokebot.webhook import ErreurWebhook, Webhook

URL = "https://discord.com/api/webhooks/123/abc"


class FauxDiscord:
    def __init__(self, statuts=None):
        self.recus, self.statuts = [], list(statuts or [])

    def __call__(self, url, corps):
        statut = self.statuts.pop(0) if self.statuts else 204
        if statut < 400:
            self.recus.append(corps)
        return statut, {"retry_after": 0.01}


class TestWebhook(unittest.TestCase):
    def test_envoi_decoupe_sans_mention_ni_apercu(self):
        faux = FauxDiscord()
        Webhook(URL, faux, pause=lambda s: None).envoyer("a" * 1500 + "\n\n" + "b" * 1500)
        self.assertEqual(len(faux.recus), 2)
        self.assertEqual(faux.recus[0]["allowed_mentions"], {"parse": []})
        self.assertEqual(faux.recus[0]["flags"], 4)

    def test_limite_de_debit_puis_succes(self):
        faux = FauxDiscord([429, 204])
        Webhook(URL, faux, pause=lambda s: None).envoyer("salut")
        self.assertEqual(len(faux.recus), 1)

    def test_url_invalide(self):
        self.assertFalse(Webhook("https://exemple.invalid/x").configure)
        with self.assertRaises(ErreurWebhook):
            Webhook(None).envoyer("x")


class TestTache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        racine = Path(self.tmp.name)
        self.p = Parametres(mode="demo", chemin_db=racine / "s.sqlite3")
        self.base = BaseDonnees(self.p.chemin_db)
        self.comp = Comparateur(self.p, base=self.base)
        self.suivi = racine / "suivi.toml"
        self.site = racine / "site"

    def tearDown(self):
        self.tmp.cleanup()

    def test_suivi_et_synchronisation(self):
        self.suivi.write_text('produits = ["demo_etb", "inconnu"]\n[prix_max]\ndemo_etb = 55\n', encoding="utf-8")
        s = charger_suivi(self.suivi, self.comp)
        self.assertEqual((s.produits, s.prix_max), (["demo_etb"], {"demo_etb": Decimal("55")}))
        synchroniser(self.base, s)
        synchroniser(self.base, s)  # idempotent
        self.assertEqual(self.base.favoris(SALON), ["demo_etb"])
        self.assertEqual([a.prix_max for a in self.base.alertes(SALON)], [Decimal("55")])
        self.suivi.write_text('produits = "tous"\n', encoding="utf-8")
        synchroniser(self.base, charger_suivi(self.suivi, self.comp))
        self.assertEqual(self.base.alertes(SALON), [])
        self.assertEqual(len(self.base.favoris(SALON)), 7)

    def test_execution_complete(self):
        self.suivi.write_text('produits = "tous"\n[prix_max]\ndemo_booster = 7.50\n', encoding="utf-8")
        faux = FauxDiscord()
        veille = ServiceVeille(self.p, self.comp, self.base)  # démo : aucune requête réseau
        bilan = executer(self.p, self.comp, self.base, Webhook(URL, faux, pause=lambda s: None), self.site,
                         veille=veille, chemin_suivi=self.suivi)
        self.assertEqual(bilan.envoyes, len(bilan.messages))
        self.assertTrue(any("Sous votre prix maximum" in c["content"] for c in faux.recus))
        index = (self.site / "index.html").read_text(encoding="utf-8")
        self.assertIn("Calendrier des sorties", index)
        self.assertIn("DONNÉES FICTIVES", index)
        fiche = (self.site / "produits" / "demo_etb.html").read_text(encoding="utf-8")
        self.assertIn('rel="noopener nofollow"', fiche)
        self.assertNotIn("<script", fiche)
        # Deuxième passage : rien de neuf, rien d'envoyé.
        n = len(faux.recus)
        executer(self.p, self.comp, self.base, Webhook(URL, faux, pause=lambda s: None), self.site,
                 veille=veille, chemin_suivi=self.suivi)
        self.assertEqual(len(faux.recus), n)

    def test_dossier_etranger_protege(self):
        self.site.mkdir()
        (self.site / "important.txt").write_text("x", encoding="utf-8")
        self.suivi.write_text('produits = "tous"\n', encoding="utf-8")
        with self.assertRaises(SystemExit):
            executer(self.p, self.comp, self.base, Webhook(None), self.site, chemin_suivi=self.suivi, envoyer=False)
        self.assertTrue((self.site / "important.txt").exists())


if __name__ == "__main__":
    unittest.main()
