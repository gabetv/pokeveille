"""Envoi des notifications dans un salon Discord par webhook (aucun bot connecté nécessaire).

Le webhook se crée dans Discord : Paramètres du serveur › Intégrations › Webhooks › Nouveau webhook.
Son URL est un SECRET (quiconque la connaît peut écrire dans le salon) : elle se met dans .env ou dans
les « Secrets » GitHub sous le nom DISCORD_WEBHOOK_URL, jamais dans le code.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from .affichage import LIMITE_DISCORD, decouper

log = logging.getLogger(__name__)
SANS_APERCU = 4  # drapeau Discord SUPPRESS_EMBEDS : pas d'aperçu des liens


class ErreurWebhook(Exception):
    pass


def _poster_httpx(url: str, corps: dict) -> tuple[int, dict]:
    import httpx

    rep = httpx.post(url, json=corps, timeout=20)
    try:
        donnees = rep.json() if rep.content else {}
    except ValueError:
        donnees = {}
    return rep.status_code, donnees


class Webhook:
    def __init__(self, url: str | None, poster: Callable[[str, dict], tuple[int, dict]] | None = None,
                 pause: Callable[[float], None] = time.sleep):
        self.url = url
        self.poster = poster or _poster_httpx
        self.pause = pause

    @property
    def configure(self) -> bool:
        return bool(self.url and self.url.startswith("https://discord.com/api/webhooks/"))

    def envoyer(self, texte: str) -> None:
        if not self.configure:
            raise ErreurWebhook("DISCORD_WEBHOOK_URL absent ou invalide")
        for morceau in decouper(texte, LIMITE_DISCORD):
            corps = {"content": morceau, "flags": SANS_APERCU, "allowed_mentions": {"parse": []},
                     "username": "PokéVeille"}
            for _ in range(4):
                statut, donnees = self.poster(self.url, corps)  # type: ignore[arg-type]
                if statut == 429:  # limite de débit Discord : on attend le délai demandé
                    self.pause(float(donnees.get("retry_after", 2)) + 0.5)
                    continue
                if statut >= 400:
                    raise ErreurWebhook(f"Discord a refusé le message (HTTP {statut})")
                break
            else:
                raise ErreurWebhook("limite de débit Discord : message non envoyé")
            self.pause(1.0)  # moins de 30 messages par minute

    def envoyer_tous(self, textes: list[str]) -> int:
        envoyes = 0
        for t in textes:
            try:
                self.envoyer(t)
                envoyes += 1
            except ErreurWebhook as exc:
                log.error("Webhook : %s", exc)
                break
        return envoyes
