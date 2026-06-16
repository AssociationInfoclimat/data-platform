"""Embeddings Mistral (codestral-embed) : client, batch, throttle, retry.

`mistralai` est importé paresseusement pour ne pas l'imposer aux tests/CI qui ne
touchent pas l'API. Le throttle (espacement minimal entre appels) reprend le motif
éprouvé d'ic-data-bot pour rester sous la limite de débit du tier.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class Throttle:
    """Garantit un intervalle minimal entre tous les appels (verrou partagé)."""

    def __init__(self, min_interval_s: float) -> None:
        self._min = min_interval_s
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self._min - (time.monotonic() - self._last)
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def make_client(api_key: str) -> Any:
    # Selon la version du SDK, le client est exporté au niveau racine (1.x) ou sous
    # mistralai.client (2.x). On gère les deux.
    try:
        from mistralai import Mistral
    except ImportError:
        from mistralai.client import Mistral
    return Mistral(api_key=api_key)


def _is_rate_limit(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def _create(client: Any, model: str, inputs: list[str], dim: int | None) -> Any:
    """Appel embeddings, en retombant sans `output_dimension` si le SDK l'ignore."""
    if dim is not None:
        try:
            return client.embeddings.create(model=model, inputs=inputs, output_dimension=dim)
        except TypeError:
            pass
    return client.embeddings.create(model=model, inputs=inputs)


def _embed_batch(client: Any, batch: list[str], *, model: str, dim: int | None,
                 throttle: Throttle, max_retries: int) -> list[list[float]]:
    attempt = 0
    while True:
        throttle.wait()
        try:
            resp = _create(client, model, batch, dim)
            return [list(item.embedding) for item in resp.data]
        except Exception as exc:  # noqa: BLE001 — on relaie après épuisement des essais
            attempt += 1
            if attempt > max_retries or not _is_rate_limit(exc):
                raise
            time.sleep(min(2 ** attempt, 30))


def _make_batches(texts: list[str], batch_size: int, max_batch_chars: int) -> list[list[str]]:
    """Lots bornés à la fois en nombre d'inputs ET en caractères cumulés (l'API
    embeddings plafonne le total de tokens par requête, pas seulement le nb d'inputs)."""
    batches: list[list[str]] = []
    cur: list[str] = []
    cur_chars = 0
    for t in texts:
        if cur and (len(cur) >= batch_size or cur_chars + len(t) > max_batch_chars):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(t)
        cur_chars += len(t)
    if cur:
        batches.append(cur)
    return batches


def embed_texts(client: Any, texts: list[str], *, model: str, dim: int | None,
                batch_size: int, max_batch_chars: int, max_input_chars: int,
                throttle: Throttle, max_retries: int,
                on_batch: Any = None) -> list[list[float]]:
    """Embedde `texts` par lots ; tronque chaque entrée à `max_input_chars` (garde-fou
    sous la limite de contexte du modèle). `on_batch(done, total)` : callback de progrès."""
    clipped = [t[:max_input_chars] for t in texts]
    total = len(clipped)
    out: list[list[float]] = []
    done = 0
    for batch in _make_batches(clipped, batch_size, max_batch_chars):
        out.extend(_embed_batch(client, batch, model=model, dim=dim,
                                throttle=throttle, max_retries=max_retries))
        done += len(batch)
        if on_batch:
            on_batch(done, total)
    return out


def embed_query(client: Any, text: str, *, model: str, dim: int | None,
                max_input_chars: int, throttle: Throttle, max_retries: int) -> list[float]:
    return _embed_batch(client, [text[:max_input_chars]], model=model, dim=dim,
                        throttle=throttle, max_retries=max_retries)[0]
