"""Réécriture de la requête utilisateur avant recherche (rappel amélioré).

Un appel chat Mistral reformule une question en langage naturel en une requête orientée
recherche de code : expansion d'acronymes, ajout de synonymes et de noms de symboles/termes
techniques probables. Complète la recherche contextuelle (le contexte côté index ; la
réécriture côté requête). Tout échec retombe sur la requête d'origine — jamais bloquant.

Réutilisé par le CLI `search.py` et par le wrapper MCP d'ic-data-bot → source unique.
"""
from __future__ import annotations

import time
from typing import Any

from .embed import Throttle, _is_rate_limit

_SYS = (
    "Tu reformules une question d'un développeur en une requête de recherche dans une base "
    "de code (français/anglais, multi-repos). Développe les acronymes, ajoute synonymes et "
    "noms de symboles/fonctions/termes techniques plausibles. Garde-la courte (une ligne). "
    "Réponds UNIQUEMENT par la requête réécrite, sans préambule ni guillemets."
)


def rewrite_query(client: Any, question: str, *, model: str, throttle: Throttle,
                  max_retries: int, max_chars: int = 2000) -> str:
    """Requête réécrite ; retombe sur `question` si vide ou en cas d'échec."""
    q = (question or "").strip()
    if not q:
        return q
    messages = [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": q[:max_chars]},
    ]
    attempt = 0
    while True:
        throttle.wait()
        try:
            resp = client.chat.complete(model=model, messages=messages, temperature=0.0)
            out = (resp.choices[0].message.content or "").strip()
            return out or q
        except Exception as exc:  # noqa: BLE001 — la recherche ne doit pas casser
            attempt += 1
            if attempt > max_retries or not _is_rate_limit(exc):
                return q
            time.sleep(min(2 ** attempt, 30))
