"""Base SQLite : historique des prix, préférences, favoris et alertes.

Données personnelles stockées : uniquement l'identifiant d'utilisateur Discord (utilisateur_id),
celui du salon où une alerte a été créée (salon_id, pour la livrer si les messages privés sont
fermés), les préférences choisies et l'auteur d'un arrivage signalé (/drop). Commande /oubliermoi
pour tout effacer (les /drop restent, sans auteur).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .alertes import EtatAlerte
from .analyse import Rapport
from .models import Etat, Preferences
from .veille import Annonce

SCHEMA = """
CREATE TABLE IF NOT EXISTS historique_prix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produit_id TEXT NOT NULL,
    source TEXT NOT NULL,
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    titre TEXT,
    vendeur TEXT,
    prix TEXT,
    livraison TEXT,
    statut_livraison TEXT,
    total TEXT,
    disponibilite TEXT,
    etat TEXT,
    langue TEXT,
    correspondance TEXT,
    vente_reelle INTEGER NOT NULL DEFAULT 0,
    demo INTEGER NOT NULL DEFAULT 0,
    verifie_le TEXT,
    enregistre_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_historique ON historique_prix(produit_id, source, url, id);

CREATE TABLE IF NOT EXISTS utilisateurs (
    utilisateur_id INTEGER PRIMARY KEY,
    preferences TEXT NOT NULL DEFAULT '{}',
    cree_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS favoris (
    utilisateur_id INTEGER NOT NULL,
    produit_id TEXT NOT NULL,
    ajoute_le TEXT NOT NULL,
    PRIMARY KEY (utilisateur_id, produit_id)
);

CREATE TABLE IF NOT EXISTS alertes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utilisateur_id INTEGER NOT NULL,
    salon_id INTEGER,
    produit_id TEXT NOT NULL,
    prix_max TEXT NOT NULL,
    etat TEXT,
    langue TEXT,
    sites TEXT NOT NULL DEFAULT '[]',
    frequence_minutes INTEGER NOT NULL,
    derniere_verif TEXT,
    dernier_total_notifie TEXT,
    etait_disponible INTEGER,
    dernier_signalement TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    creee_le TEXT NOT NULL
);

-- Veille des sorties et des drops : annonces datées (articles, dates officielles, arrivages signalés).
CREATE TABLE IF NOT EXISTS annonces (
    cle TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    titre TEXT NOT NULL,
    url TEXT,
    texte TEXT,
    dates TEXT NOT NULL DEFAULT '[]',
    produits TEXT NOT NULL DEFAULT '[]',
    magasin TEXT,
    ville TEXT,
    utilisateur_id INTEGER,
    publie_le TEXT NOT NULL,
    enregistre_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_annonces ON annonces(publie_le);

CREATE TABLE IF NOT EXISTS dates_sortie (
    produit_id TEXT NOT NULL,
    source TEXT NOT NULL,
    date_sortie TEXT NOT NULL,
    url TEXT,
    maj_le TEXT NOT NULL,
    PRIMARY KEY (produit_id, source)
);

CREATE TABLE IF NOT EXISTS veille_etat (
    cle TEXT PRIMARY KEY,
    valeur TEXT,
    maj_le TEXT NOT NULL
);
"""

# Colonnes ajoutées après la première version : ajoutées aux bases existantes à l'ouverture.
MIGRATIONS = {"alertes": {"dernier_signalement": "TEXT"}}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _maintenant_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AlerteEnregistree:
    id: int
    utilisateur_id: int
    salon_id: int | None
    produit_id: str
    prix_max: Decimal
    etat: Etat | None
    langue: str | None
    sites: list[str]
    frequence_minutes: int
    derniere_verif: datetime | None
    etat_alerte: EtatAlerte

    def preferences(self) -> Preferences:
        return Preferences(etat=self.etat, langue=self.langue, sites=self.sites)


class BaseDonnees:
    def __init__(self, chemin: Path | str):
        self.chemin = str(chemin)
        if self.chemin != ":memory:":
            Path(self.chemin).parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as cnx:
            cnx.executescript(SCHEMA)
            for table, colonnes in MIGRATIONS.items():
                existantes = {r["name"] for r in cnx.execute(f"PRAGMA table_info({table})")}
                for nom, type_sql in colonnes.items():
                    if nom not in existantes:
                        cnx.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {type_sql}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        cnx = sqlite3.connect(self.chemin, timeout=10)
        cnx.row_factory = sqlite3.Row
        try:
            yield cnx
            cnx.commit()
        except Exception:
            cnx.rollback()
            raise
        finally:
            cnx.close()

    # --- Historique des prix -------------------------------------------------
    def enregistrer_rapport(self, rapport: Rapport) -> int:
        """Ajoute une ligne d'historique pour chaque annonce dont le prix ou le stock a changé."""
        ajoutees = 0
        with self._transaction() as cnx:
            for l in rapport.lignes + rapport.ventes_reelles:
                o = l.offre
                valeurs = (
                    str(o.prix) if o.prix is not None else None,
                    str(o.livraison) if o.livraison is not None else None,
                    o.disponibilite.value,
                )
                derniere = cnx.execute(
                    "SELECT prix, livraison, disponibilite FROM historique_prix "
                    "WHERE produit_id=? AND source=? AND url=? ORDER BY id DESC LIMIT 1",
                    (rapport.produit.id, o.source, o.url),
                ).fetchone()
                if derniere is not None and tuple(derniere) == valeurs:
                    continue
                cnx.execute(
                    "INSERT INTO historique_prix (produit_id, source, site, url, titre, vendeur, prix, livraison,"
                    " statut_livraison, total, disponibilite, etat, langue, correspondance, vente_reelle, demo,"
                    " verifie_le, enregistre_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        rapport.produit.id, o.source, o.site, o.url, o.titre, o.vendeur, valeurs[0], valeurs[1],
                        o.statut_livraison.value,
                        str(l.total.montant) if l.total.montant is not None else None,
                        o.disponibilite.value, o.etat.value, o.langue, l.correspondance.statut.value,
                        int(o.vente_reelle), int(o.demo),
                        _iso(o.verifie_le) if o.verifie_le else None, _iso(_maintenant_utc()),
                    ),
                )
                ajoutees += 1
        return ajoutees

    def historique(self, produit_id: str, limite: int = 50) -> list[sqlite3.Row]:
        with self._transaction() as cnx:
            return cnx.execute(
                "SELECT * FROM historique_prix WHERE produit_id=? ORDER BY id DESC LIMIT ?", (produit_id, limite)
            ).fetchall()

    # --- Utilisateurs et préférences -----------------------------------------
    def assurer_utilisateur(self, utilisateur_id: int) -> None:
        with self._transaction() as cnx:
            cnx.execute(
                "INSERT OR IGNORE INTO utilisateurs (utilisateur_id, preferences, cree_le) VALUES (?, '{}', ?)",
                (utilisateur_id, _iso(_maintenant_utc())),
            )

    def preferences(self, utilisateur_id: int) -> Preferences:
        with self._transaction() as cnx:
            ligne = cnx.execute("SELECT preferences FROM utilisateurs WHERE utilisateur_id=?", (utilisateur_id,)).fetchone()
        return Preferences.depuis_dict(json.loads(ligne["preferences"]) if ligne else {})

    def enregistrer_preferences(self, utilisateur_id: int, prefs: Preferences) -> None:
        self.assurer_utilisateur(utilisateur_id)
        with self._transaction() as cnx:
            cnx.execute(
                "UPDATE utilisateurs SET preferences=? WHERE utilisateur_id=?",
                (json.dumps(prefs.vers_dict(), ensure_ascii=False), utilisateur_id),
            )

    def oublier_utilisateur(self, utilisateur_id: int) -> None:
        with self._transaction() as cnx:
            for table in ("alertes", "favoris", "utilisateurs"):
                cnx.execute(f"DELETE FROM {table} WHERE utilisateur_id=?", (utilisateur_id,))
            # Les arrivages signalés restent utiles aux autres membres, mais ne sont plus rattachés à vous.
            cnx.execute("UPDATE annonces SET utilisateur_id=NULL WHERE utilisateur_id=?", (utilisateur_id,))

    # --- Favoris --------------------------------------------------------------
    def ajouter_favori(self, utilisateur_id: int, produit_id: str) -> None:
        self.assurer_utilisateur(utilisateur_id)
        with self._transaction() as cnx:
            cnx.execute(
                "INSERT OR IGNORE INTO favoris (utilisateur_id, produit_id, ajoute_le) VALUES (?,?,?)",
                (utilisateur_id, produit_id, _iso(_maintenant_utc())),
            )

    def retirer_favori(self, utilisateur_id: int, produit_id: str) -> bool:
        with self._transaction() as cnx:
            return cnx.execute("DELETE FROM favoris WHERE utilisateur_id=? AND produit_id=?", (utilisateur_id, produit_id)).rowcount > 0

    def favoris(self, utilisateur_id: int) -> list[str]:
        with self._transaction() as cnx:
            return [r["produit_id"] for r in cnx.execute(
                "SELECT produit_id FROM favoris WHERE utilisateur_id=? ORDER BY ajoute_le", (utilisateur_id,)
            )]

    # --- Alertes ----------------------------------------------------------------
    def creer_alerte(
        self, utilisateur_id: int, produit_id: str, prix_max: Decimal, frequence_minutes: int,
        etat: Etat | None = None, langue: str | None = None, sites: list[str] | None = None,
        salon_id: int | None = None,
    ) -> int:
        self.assurer_utilisateur(utilisateur_id)
        with self._transaction() as cnx:
            cur = cnx.execute(
                "INSERT INTO alertes (utilisateur_id, salon_id, produit_id, prix_max, etat, langue, sites,"
                " frequence_minutes, creee_le) VALUES (?,?,?,?,?,?,?,?,?)",
                (utilisateur_id, salon_id, produit_id, str(prix_max), etat.value if etat else None, langue,
                 json.dumps(sites or []), frequence_minutes, _iso(_maintenant_utc())),
            )
            return int(cur.lastrowid)  # type: ignore[arg-type]

    @staticmethod
    def _alerte(r: sqlite3.Row) -> AlerteEnregistree:
        dispo = r["etait_disponible"]
        return AlerteEnregistree(
            id=r["id"],
            utilisateur_id=r["utilisateur_id"],
            salon_id=r["salon_id"],
            produit_id=r["produit_id"],
            prix_max=Decimal(r["prix_max"]),
            etat=Etat(r["etat"]) if r["etat"] else None,
            langue=r["langue"],
            sites=json.loads(r["sites"] or "[]"),
            frequence_minutes=r["frequence_minutes"],
            derniere_verif=datetime.fromisoformat(r["derniere_verif"]) if r["derniere_verif"] else None,
            etat_alerte=EtatAlerte(
                dernier_total_notifie=Decimal(r["dernier_total_notifie"]) if r["dernier_total_notifie"] else None,
                etait_disponible=None if dispo is None else bool(dispo),
                dernier_signalement=(
                    datetime.fromisoformat(r["dernier_signalement"]) if r["dernier_signalement"] else None
                ),
            ),
        )

    def alertes(self, utilisateur_id: int) -> list[AlerteEnregistree]:
        with self._transaction() as cnx:
            return [self._alerte(r) for r in cnx.execute(
                "SELECT * FROM alertes WHERE utilisateur_id=? AND active=1 ORDER BY id", (utilisateur_id,)
            )]

    def supprimer_alerte(self, utilisateur_id: int, alerte_id: int) -> bool:
        with self._transaction() as cnx:
            return cnx.execute("DELETE FROM alertes WHERE utilisateur_id=? AND id=?", (utilisateur_id, alerte_id)).rowcount > 0

    def alertes_a_verifier(self, frequence_min_minutes: int, maintenant: datetime | None = None) -> list[AlerteEnregistree]:
        instant = maintenant or _maintenant_utc()
        with self._transaction() as cnx:
            toutes = [self._alerte(r) for r in cnx.execute("SELECT * FROM alertes WHERE active=1 ORDER BY id")]
        dues = []
        for a in toutes:
            intervalle = timedelta(minutes=max(a.frequence_minutes, frequence_min_minutes))
            if a.derniere_verif is None or instant - a.derniere_verif >= intervalle:
                dues.append(a)
        return dues

    # --- Veille des sorties et des drops ---------------------------------------
    def abonnes(self, produit_id: str) -> list[tuple[int, int | None]]:
        """Membres à prévenir pour un produit : alerte active (avec son salon) ou favori (message privé)."""
        with self._transaction() as cnx:
            vus: dict[int, int | None] = {}
            for r in cnx.execute(
                "SELECT utilisateur_id, salon_id FROM alertes WHERE produit_id=? AND active=1 ORDER BY id", (produit_id,)
            ):
                vus.setdefault(r["utilisateur_id"], r["salon_id"])
            for r in cnx.execute("SELECT utilisateur_id FROM favoris WHERE produit_id=?", (produit_id,)):
                vus.setdefault(r["utilisateur_id"], None)
        return list(vus.items())

    def enregistrer_annonce(self, a: Annonce) -> bool:
        """Enregistre une annonce ; False si elle était déjà connue (jamais notifiée deux fois)."""
        with self._transaction() as cnx:
            cur = cnx.execute(
                "INSERT OR IGNORE INTO annonces (cle, source, type, titre, url, texte, dates, produits, magasin,"
                " ville, utilisateur_id, publie_le, enregistre_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.cle, a.source, a.type, a.titre, a.url, a.texte, json.dumps([d.isoformat() for d in a.dates]),
                 json.dumps(a.produit_ids), a.magasin, a.ville, a.utilisateur_id, _iso(a.publie_le),
                 _iso(_maintenant_utc())),
            )
            return cur.rowcount > 0

    def annonces(
        self, produit_id: str | None = None, types: tuple[str, ...] | None = None,
        depuis: datetime | None = None, limite: int = 20,
    ) -> list[Annonce]:
        requete, args = "SELECT * FROM annonces WHERE 1=1", []
        if types:
            requete += f" AND type IN ({','.join('?' * len(types))})"
            args += list(types)
        if depuis:
            requete += " AND publie_le >= ?"
            args.append(_iso(depuis))
        if produit_id:
            requete += " AND produits LIKE ?"
            args.append(f'%"{produit_id}"%')
        requete += " ORDER BY publie_le DESC LIMIT ?"
        args.append(limite)
        with self._transaction() as cnx:
            lignes = cnx.execute(requete, args).fetchall()
        return [Annonce(
            source=r["source"], cle=r["cle"], type=r["type"], titre=r["titre"], url=r["url"], texte=r["texte"] or "",
            dates=[date.fromisoformat(d) for d in json.loads(r["dates"])], produit_ids=json.loads(r["produits"]),
            magasin=r["magasin"], ville=r["ville"], utilisateur_id=r["utilisateur_id"],
            publie_le=datetime.fromisoformat(r["publie_le"]),
        ) for r in lignes]

    def date_sortie(self, produit_id: str, source: str) -> tuple[date, str | None] | None:
        with self._transaction() as cnx:
            r = cnx.execute("SELECT date_sortie, url FROM dates_sortie WHERE produit_id=? AND source=?",
                            (produit_id, source)).fetchone()
        return (date.fromisoformat(r["date_sortie"]), r["url"]) if r else None

    def dates_sortie(self) -> dict[str, tuple[date, str, str | None]]:
        """produit_id -> (date, source, url) ; une seule source par produit (Poképédia aujourd'hui)."""
        with self._transaction() as cnx:
            lignes = cnx.execute("SELECT * FROM dates_sortie ORDER BY maj_le").fetchall()
        return {r["produit_id"]: (date.fromisoformat(r["date_sortie"]), r["source"], r["url"]) for r in lignes}

    def maj_date_sortie(self, produit_id: str, source: str, nouvelle: date, url: str | None) -> date | None:
        """Enregistre la date ; renvoie l'ancienne date si elle a changé (report ou avancement), sinon None."""
        ancienne = self.date_sortie(produit_id, source)
        with self._transaction() as cnx:
            cnx.execute(
                "INSERT INTO dates_sortie (produit_id, source, date_sortie, url, maj_le) VALUES (?,?,?,?,?)"
                " ON CONFLICT(produit_id, source) DO UPDATE SET date_sortie=excluded.date_sortie,"
                " url=excluded.url, maj_le=excluded.maj_le",
                (produit_id, source, nouvelle.isoformat(), url, _iso(_maintenant_utc())),
            )
        return ancienne[0] if ancienne and ancienne[0] != nouvelle else None

    def etat_veille(self, cle: str) -> str | None:
        with self._transaction() as cnx:
            r = cnx.execute("SELECT valeur FROM veille_etat WHERE cle=?", (cle,)).fetchone()
        return r["valeur"] if r else None

    def marquer_veille(self, cle: str, valeur: str = "1") -> bool:
        """Mémorise une clé ; False si elle existait déjà (sert aussi d'anti-doublon pour les rappels)."""
        with self._transaction() as cnx:
            cur = cnx.execute("INSERT OR IGNORE INTO veille_etat (cle, valeur, maj_le) VALUES (?,?,?)",
                              (cle, valeur, _iso(_maintenant_utc())))
            return cur.rowcount > 0

    def dernier_drop(self, utilisateur_id: int, produit_id: str) -> datetime | None:
        with self._transaction() as cnx:
            r = cnx.execute(
                "SELECT MAX(publie_le) AS d FROM annonces WHERE type='drop' AND utilisateur_id=? AND produits LIKE ?",
                (utilisateur_id, f'%"{produit_id}"%'),
            ).fetchone()
        return datetime.fromisoformat(r["d"]) if r and r["d"] else None

    def maj_etat_alerte(self, alerte_id: int, etat: EtatAlerte, verifie_le: datetime | None = None) -> None:
        with self._transaction() as cnx:
            cnx.execute(
                "UPDATE alertes SET derniere_verif=?, dernier_total_notifie=?, etait_disponible=?,"
                " dernier_signalement=? WHERE id=?",
                (
                    _iso(verifie_le or _maintenant_utc()),
                    str(etat.dernier_total_notifie) if etat.dernier_total_notifie is not None else None,
                    None if etat.etait_disponible is None else int(etat.etait_disponible),
                    _iso(etat.dernier_signalement) if etat.dernier_signalement else None,
                    alerte_id,
                ),
            )
