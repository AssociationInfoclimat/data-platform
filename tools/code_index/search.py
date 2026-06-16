"""Requête sémantique de l'index code : fonction importable + CLI.

`search_code()` est réutilisée par le wrapper MCP d'ic-data-bot (Partie B) ; garder sa
signature stable.

Usage CLI :
  python -m code_index.search "où est géré le routing des forums ?" [--k 6]
                              [--repo site-infoclimat ...] [--lang php] [--full]
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from . import embed, store
from .config import Config, load_config


@dataclass(frozen=True)
class Result:
    repo: str
    path: str
    start_line: int
    end_line: int
    lang: str
    score: float       # distance cosinus (plus petit = plus proche)
    text: str

    @property
    def location(self) -> str:
        return f"{self.repo}/{self.path}:{self.start_line}-{self.end_line}"


def _where(repos: list[str] | None, lang: str | None) -> str | None:
    clauses = []
    if repos:
        joined = ", ".join("'" + r.replace("'", "''") + "'" for r in repos)
        clauses.append(f"repo IN ({joined})")
    if lang:
        clauses.append("lang = '" + lang.replace("'", "''") + "'")
    return " AND ".join(clauses) if clauses else None


def search_code(question: str, k: int = 8, repos: list[str] | None = None,
                lang: str | None = None, config: Config | None = None) -> list[Result]:
    """Top-`k` chunks de code les plus proches de `question`, filtrables par repo/langage."""
    cfg = config or load_config()
    if not cfg.api_key:
        raise RuntimeError("MISTRAL_API_KEY manquante : impossible d'embedder la requête.")
    client = embed.make_client(cfg.api_key)
    throttle = embed.Throttle(cfg.min_interval_s)
    qvec = embed.embed_query(client, question, model=cfg.model, dim=cfg.dim,
                             max_input_chars=cfg.max_input_chars, throttle=throttle,
                             max_retries=cfg.max_retries)
    db = store.connect(cfg.db_dir)
    rows = store.search(db, qvec, k=k, where=_where(repos, lang))
    return [
        Result(repo=r["repo"], path=r["path"], start_line=r["start_line"],
               end_line=r["end_line"], lang=r["lang"],
               score=float(r.get("_distance", 0.0)), text=r["text"])
        for r in rows
    ]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Recherche sémantique dans le code Infoclimat.")
    ap.add_argument("question")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--repo", action="append", dest="repos", default=None)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--full", action="store_true", help="Afficher le chunk entier.")
    args = ap.parse_args(argv)

    results = search_code(args.question, k=args.k, repos=args.repos, lang=args.lang)
    if not results:
        print("Aucun résultat (index vide ?). Lancer d'abord : python -m code_index.index",
              file=sys.stderr)
        return 1
    for i, r in enumerate(results, 1):
        print(f"\n#{i}  {r.location}  ({r.lang}, distance {r.score:.3f})")
        snippet = r.text if args.full else "\n".join(r.text.splitlines()[:15])
        print(snippet.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
