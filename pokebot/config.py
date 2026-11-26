"""Chargement de la configuration : fichier .env (secrets) + config/parametres.toml (réglages)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from decimal import Decimal
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def charger_env(chemin: Path) -> None:
    """Lecteur .env minimal (CLE=valeur). Les variables déjà définies ne sont pas écrasées."""
    if not chemin.exists():
        return
    for brut in chemin.read_text(encoding="utf-8").splitlines():
        ligne = brut.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle, valeur = cle.strip(), valeur.strip()
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
            valeur = valeur[1:-1]
        os.environ.setdefault(cle, valeur)


@dataclass(frozen=True)
class Seuils:
    """Seuils de l'avis du bot (modifiables dans config/parametres.toml, section [seuils])."""

    tres_bonne_affaire_amazon: Decimal = Decimal("0.90")  # ≤ 90 % de la référence Amazon
    tres_bonne_affaire_mediane: Decimal = Decimal("0.95")  # ET ≤ 95 % de la médiane
    tres_bonne_affaire_carte: Decimal = Decimal("0.90")  # cartes : ≤ 90 % de la médiane
    raisonnable: Decimal = Decimal("1.05")  # ≤ +5 % d'une des références
    cher: Decimal = Decimal("1.10")  # > +10 % de toutes les références
    prix_anormal: Decimal = Decimal("0.60")  # < 60 % de la référence du marché => à vérifier
    frais_port_eleves: Decimal = Decimal("0.25")  # livraison > 25 % du prix affiché
    min_offres_mediane: int = 3
    exiger_deux_references: bool = True  # « très bonne affaire » exige Amazon ET médiane
    note_vendeur_min: Decimal = Decimal("95")  # % d'avis positifs
    avis_vendeur_min: int = 50

    @classmethod
    def depuis_dict(cls, d: dict) -> "Seuils":
        base = cls()
        noms = {f.name for f in fields(cls)}
        inconnus = set(d) - noms
        if inconnus:
            raise ValueError(f"seuil(s) inconnu(s) dans parametres.toml : {', '.join(sorted(inconnus))}")
        valeurs = {}
        for nom, v in d.items():
            actuel = getattr(base, nom)
            if isinstance(actuel, bool):
                valeurs[nom] = bool(v)
            elif isinstance(actuel, int):
                valeurs[nom] = int(v)
            else:
                valeurs[nom] = Decimal(str(v))
        return cls(**valeurs)


@dataclass(frozen=True)
class ConfigSource:
    actif: bool = True
    delai_entre_requetes_secondes: float = 2.0  # respect des quotas (Amazon : 1 requête/s au départ)
    cache_secondes: int = 900  # une même recherche n'est pas relancée avant ce délai
    livraison_estimee: Decimal | None = None  # barème saisi par vous, affiché « estimé »
    livraison_gratuite_des: Decimal | None = None
    recherche: str | None = None  # terme de recherche du flux (sources de type flux RSS)
    age_max_jours: int | None = None  # ignorer les publications plus anciennes

    @classmethod
    def depuis_dict(cls, d: dict) -> "ConfigSource":
        def dec(cle: str) -> Decimal | None:
            return Decimal(str(d[cle])) if d.get(cle) is not None else None

        return cls(
            actif=bool(d.get("actif", True)),
            delai_entre_requetes_secondes=float(d.get("delai_entre_requetes_secondes", 2.0)),
            cache_secondes=int(d.get("cache_secondes", 900)),
            livraison_estimee=dec("livraison_estimee"),
            livraison_gratuite_des=dec("livraison_gratuite_des"),
            recherche=str(d["recherche"]) if d.get("recherche") else None,
            age_max_jours=int(d["age_max_jours"]) if d.get("age_max_jours") is not None else None,
        )


def _chemin(valeur: str | None, defaut: str) -> Path:
    p = Path(valeur or defaut)
    return p if p.is_absolute() else RACINE / p


@dataclass
class Parametres:
    mode: str = "demo"  # "demo" ou "reel"
    discord_token: str | None = None
    discord_guild_id: int | None = None  # serveur où synchroniser les commandes slash immédiatement
    utilisateurs_autorises: set[int] = field(default_factory=set)  # identifiants d'utilisateurs Discord
    code_postal: str | None = None
    chemin_db: Path = RACINE / "data" / "pokeveille.sqlite3"
    seuils: Seuils = field(default_factory=Seuils)
    sources: dict[str, ConfigSource] = field(default_factory=dict)
    amazon_credential_id: str | None = None
    amazon_credential_secret: str | None = None
    amazon_credential_version: str | None = None
    amazon_partner_tag: str | None = None
    amazon_marketplace: str = "www.amazon.fr"
    frequence_defaut_minutes: int = 60
    frequence_min_minutes: int = 15
    intervalle_tache_secondes: int = 60
    max_offres_par_produit: int = 8
    salons_veille: set[int] = field(default_factory=set)  # salons Discord où arrivent les annonces suivies
    intervalle_veille_minutes: int = 30  # lecture du calendrier et des flux d'annonces
    rappel_veille_sortie: bool = True  # rappel la veille d'une sortie annoncée
    delai_entre_drops_minutes: int = 30  # anti-spam : un même membre, un même produit
    chemin_catalogue: Path = RACINE / "data" / "catalogue.csv"
    chemin_offres_manuelles: Path = RACINE / "data" / "offres_manuelles.csv"
    chemin_catalogue_demo: Path = RACINE / "data" / "demo" / "catalogue_demo.csv"
    chemin_offres_demo: Path = RACINE / "data" / "demo" / "offres_demo.csv"

    @property
    def demo(self) -> bool:
        return self.mode == "demo"

    @property
    def amazon_configure(self) -> bool:
        return all([
            self.amazon_credential_id, self.amazon_credential_secret,
            self.amazon_credential_version, self.amazon_partner_tag,
        ])

    def source(self, identifiant: str) -> ConfigSource:
        return self.sources.get(identifiant, ConfigSource())

    @classmethod
    def charger(
        cls,
        fichier_env: Path | None = None,
        fichier_parametres: Path | None = None,
        mode: str | None = None,
    ) -> "Parametres":
        charger_env(fichier_env or RACINE / ".env")
        chemin_toml = fichier_parametres or RACINE / "config" / "parametres.toml"
        conf = tomllib.loads(chemin_toml.read_text(encoding="utf-8")) if chemin_toml.exists() else {}
        env = os.environ.get

        mode_final = (mode or env("BOT_MODE") or "demo").strip().lower()
        if mode_final not in ("demo", "reel"):
            raise ValueError("BOT_MODE doit valoir « demo » ou « reel »")

        autorises = {
            int(x) for x in (env("DISCORD_UTILISATEURS_AUTORISES") or "").replace(";", ",").split(",")
            if x.strip()
        }
        guild = (env("DISCORD_GUILD_ID") or "").strip()
        salons = {
            int(x) for x in (env("DISCORD_SALONS_VEILLE") or "").replace(";", ",").split(",") if x.strip()
        }
        alertes = conf.get("alertes", {})
        affichage = conf.get("affichage", {})
        veille = conf.get("veille", {})
        return cls(
            mode=mode_final,
            discord_token=env("DISCORD_BOT_TOKEN") or None,
            discord_guild_id=int(guild) if guild else None,
            utilisateurs_autorises=autorises,
            code_postal=env("CODE_POSTAL") or None,
            # La démo écrit dans une base séparée pour ne jamais mélanger fictif et réel.
            chemin_db=_chemin(
                env("CHEMIN_BASE") if mode_final == "reel" else None,
                "data/pokeveille.sqlite3" if mode_final == "reel" else "data/pokeveille_demo.sqlite3",
            ),
            seuils=Seuils.depuis_dict(conf.get("seuils", {})),
            sources={k: ConfigSource.depuis_dict(v) for k, v in conf.get("sources", {}).items()},
            amazon_credential_id=env("AMAZON_CREDENTIAL_ID") or None,
            amazon_credential_secret=env("AMAZON_CREDENTIAL_SECRET") or None,
            amazon_credential_version=env("AMAZON_CREDENTIAL_VERSION") or None,
            amazon_partner_tag=env("AMAZON_PARTNER_TAG") or None,
            amazon_marketplace=env("AMAZON_MARKETPLACE") or "www.amazon.fr",
            frequence_defaut_minutes=int(alertes.get("frequence_par_defaut_minutes", 60)),
            frequence_min_minutes=int(alertes.get("frequence_minimale_minutes", 15)),
            intervalle_tache_secondes=int(alertes.get("intervalle_tache_secondes", 60)),
            max_offres_par_produit=int(affichage.get("max_offres_par_produit", 8)),
            salons_veille=salons,
            intervalle_veille_minutes=max(10, int(veille.get("intervalle_minutes", 30))),
            rappel_veille_sortie=bool(veille.get("rappel_veille_de_sortie", True)),
            delai_entre_drops_minutes=int(veille.get("delai_entre_drops_minutes", 30)),
            chemin_catalogue=_chemin(env("CHEMIN_CATALOGUE"), "data/catalogue.csv"),
            chemin_offres_manuelles=_chemin(env("CHEMIN_OFFRES_MANUELLES"), "data/offres_manuelles.csv"),
        )
