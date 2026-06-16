"""Contexte préfixé aux chunks avant embedding (« Contextual Retrieval »).

Deux stratégies (cf. `Config.context_mode`) :

- ``llm`` : un appel chat Mistral **par fichier** renvoie, en JSON, une phrase situant
  chaque chunk dans son fichier. Anthropic met le document en cache et fait un appel par
  chunk ; Mistral n'a pas de cache manuel, donc on groupe par fichier pour ne pas re-payer
  le fichier ~N fois. Tout trou (chunk non couvert) ou tout échec retombe sur le contexte
  structurel — jamais de chunk sans préfixe.
- ``struct`` : contexte déterministe, pur stdlib (repo, chemin, langage, symbole englobant,
  position). Gratuit, testable en CI.
- ``off`` : aucun préfixe (comportement historique).

`mistralai` n'est pas importé ici : on reçoit un client déjà construit (cf. `embed.make_client`,
dont l'objet expose `.embeddings` et `.chat`).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .chunk import Chunk
from .embed import Throttle, _is_rate_limit


# --- contexte structurel (déterministe, pur stdlib) -------------------------------

# Repère une ligne de déclaration, multi-langage (PHP/JS/TS/Python/Go/Rust/shell…).
_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+|default\s+|public\s+|private\s+|protected\s+|static\s+|final\s+"
    r"|abstract\s+|async\s+)*"
    r"(?:def|class|function|func|fn|sub|interface|trait|struct|enum|module|namespace)\b.*"
)


def _enclosing_symbol(file_text: str, start_line: int) -> str | None:
    """Déclaration (def/class/function…) la plus proche en remontant depuis `start_line`."""
    lines = file_text.splitlines()
    for i in range(min(start_line, len(lines)) - 1, -1, -1):
        if _SYMBOL_RE.match(lines[i]):
            return lines[i].strip().rstrip("{(:").strip()
    return None


def structural_context(repo: str, path: str, lang: str, file_text: str, chunk: Chunk,
                       total_lines: int | None = None) -> str:
    """Descripteur compact d'un chunk, sans appel réseau."""
    n = total_lines if total_lines is not None else len(file_text.splitlines())
    parts = [f"repo {repo}", f"fichier {path} ({lang})"]
    sym = _enclosing_symbol(file_text, chunk.start_line)
    if sym:
        parts.append(f"dans {sym}")
    parts.append(f"lignes {chunk.start_line}-{chunk.end_line}/{n}")
    return "[" + " | ".join(parts) + "]"


# --- contexte LLM (par fichier, JSON) ---------------------------------------------

_SYS = (
    "Tu situes de courts extraits de code dans leur fichier pour améliorer une recherche "
    "sémantique. Pour chaque extrait (identifié par son indice et ses lignes), écris UNE "
    "phrase concise décrivant son rôle dans le fichier (quelle fonction/responsabilité, à "
    "quoi il sert). Pas de code, pas de paraphrase ligne à ligne. Réponds en JSON strict : "
    '{"contexts": [{"i": <indice entier>, "context": <phrase>}, ...]} couvrant TOUS les indices.'
)


def _numbered(file_text: str, max_chars: int) -> str:
    out: list[str] = []
    size = 0
    for n, line in enumerate(file_text.splitlines(), 1):
        piece = f"{n}: {line}"
        out.append(piece)
        size += len(piece) + 1
        if size > max_chars:
            out.append(f"... [fichier tronqué après {n} lignes]")
            break
    return "\n".join(out)


def _user_prompt(repo: str, path: str, lang: str, file_text: str, chunks: list[Chunk],
                 max_file_chars: int) -> str:
    # On donne le fichier numéroté UNE fois, puis on liste les chunks par lignes (pas de
    # recopie de leur texte : ils sont déjà dans le fichier ci-dessus → tokens divisés).
    listing = "\n".join(f"[{i}] lignes {ch.start_line}-{ch.end_line}"
                        for i, ch in enumerate(chunks))
    return (f"Fichier : {repo}/{path} ({lang})\n\n=== CONTENU (numéroté) ===\n"
            f"{_numbered(file_text, max_file_chars)}\n\n=== EXTRAITS À SITUER ===\n{listing}")


def _chat_json(client: Any, model: str, messages: list[dict], throttle: Throttle,
               max_retries: int) -> str:
    attempt = 0
    while True:
        throttle.wait()
        try:
            resp = client.chat.complete(model=model, messages=messages,
                                        response_format={"type": "json_object"},
                                        temperature=0.0)
            return resp.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 — relayé après épuisement des essais
            attempt += 1
            if attempt > max_retries or not _is_rate_limit(exc):
                raise
            time.sleep(min(2 ** attempt, 30))


def _parse_contexts(raw: str) -> dict[int, str]:
    data = json.loads(raw)
    items = data.get("contexts") if isinstance(data, dict) else None
    out: dict[int, str] = {}
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and it.get("context"):
                try:
                    out[int(it["i"])] = str(it["context"]).strip()
                except (TypeError, ValueError, KeyError):
                    pass
    return out


def build_file_contexts(client: Any, repo: str, path: str, lang: str, file_text: str,
                        chunks: list[Chunk], *, model: str, throttle: Throttle,
                        max_retries: int, max_file_chars: int) -> list[str]:
    """Contexte LLM par chunk (1 appel/fichier). Trous et échecs → contexte structurel."""
    if not chunks:
        return []
    total = len(file_text.splitlines())
    fallback = [structural_context(repo, path, lang, file_text, ch, total) for ch in chunks]
    messages = [
        {"role": "system", "content": _SYS},
        {"role": "user",
         "content": _user_prompt(repo, path, lang, file_text, chunks, max_file_chars)},
    ]
    try:
        by_i = _parse_contexts(_chat_json(client, model, messages, throttle, max_retries))
    except Exception:  # noqa: BLE001 — l'index ne doit jamais casser sur le contexte
        return fallback
    return [by_i.get(i) or fallback[i] for i in range(len(chunks))]


# --- dispatch + application -------------------------------------------------------

def contexts_for_file(client: Any, repo: str, path: str, lang: str, file_text: str,
                      chunks: list[Chunk], *, mode: str, model: str, throttle: Throttle,
                      max_retries: int, max_file_chars: int) -> list[str]:
    """Liste de contextes (parallèle à `chunks`) selon la stratégie `mode`."""
    if not chunks or mode == "off":
        return ["" for _ in chunks]
    if mode == "struct":
        total = len(file_text.splitlines())
        return [structural_context(repo, path, lang, file_text, ch, total) for ch in chunks]
    return build_file_contexts(client, repo, path, lang, file_text, chunks, model=model,
                               throttle=throttle, max_retries=max_retries,
                               max_file_chars=max_file_chars)


def apply_context(context: str, text: str) -> str:
    """Texte effectivement embeddé/indexé en FTS : contexte préfixé au chunk brut."""
    context = (context or "").strip()
    return f"{context}\n\n{text}" if context else text
