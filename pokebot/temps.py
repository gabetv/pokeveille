"""Gestion de l'heure de Paris (Europe/Paris).

Sous Windows, la base des fuseaux horaires n'est pas fournie par le système :
installez le paquet `tzdata` (dans requirements.txt). À défaut, une règle de secours
(heure d'été européenne) est utilisée pour que le mode démo fonctionne sans installation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo

    PARIS: tzinfo | None = ZoneInfo("Europe/Paris")
except Exception:  # base tz absente (Windows sans tzdata)
    PARIS = None


def _dernier_dimanche(annee: int, mois: int) -> datetime:
    if mois == 12:
        dernier = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier = datetime(annee, mois + 1, 1) - timedelta(days=1)
    return dernier - timedelta(days=(dernier.weekday() + 1) % 7)


def _decalage_paris(dt_utc: datetime) -> timedelta:
    """Heure d'été du dernier dimanche de mars au dernier dimanche d'octobre, 01:00 UTC."""
    debut = _dernier_dimanche(dt_utc.year, 3).replace(hour=1, tzinfo=timezone.utc)
    fin = _dernier_dimanche(dt_utc.year, 10).replace(hour=1, tzinfo=timezone.utc)
    return timedelta(hours=2) if debut <= dt_utc < fin else timedelta(hours=1)


def en_heure_paris(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if PARIS is not None:
        return dt.astimezone(PARIS)
    utc = dt.astimezone(timezone.utc)
    return utc.astimezone(timezone(_decalage_paris(utc), "Europe/Paris"))


def maintenant() -> datetime:
    return en_heure_paris(datetime.now(timezone.utc))


def depuis_texte(texte: str | None) -> datetime | None:
    """Lit une date ISO 8601. Une date sans fuseau est considérée comme une heure de Paris."""
    if not texte or not texte.strip():
        return None
    dt = datetime.fromisoformat(texte.strip())
    if dt.tzinfo is not None:
        return dt
    if PARIS is not None:
        return dt.replace(tzinfo=PARIS)
    approx = dt.replace(tzinfo=timezone.utc)
    return dt.replace(tzinfo=timezone(_decalage_paris(approx)))


def format_paris(dt: datetime | None) -> str:
    if dt is None:
        return "date inconnue"
    local = en_heure_paris(dt)
    return local.strftime("%d/%m/%Y à %H:%M") + " (heure de Paris)"
