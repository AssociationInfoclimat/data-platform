"""Requête sémantique de l'index code : fonction importable + CLI.

`search_code()` est réutilisée par le wrapper MCP d'ic-data-bot (Partie B) ; garder sa
signature stable.

Usage CLI :
  python -m code_index.search "où est géré le routing des forums ?" [--k 6]
                              [--repo site-infoclimat ...] [--lang php] [--full]
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from dataclasses import dataclass

from . import embed, rewrite, store
from .config import Config, load_config


@dataclass(frozen=True)
class Result:
    repo: str
    path: str
    start_line: int
    end_line: int
    lang: str
    score: float       # vecteur seul : distance cosinus (petit = proche) ; hybride : score
                       # de pertinence RRF (grand = pertinent). Affichage seulement.
    text: str
    source: str = ""        # github | gitlab | other (repo d'origine)
    last_commit: str = ""   # YYYY-MM-DD du dernier commit du fichier (récence)
    status: str = ""        # actif | douteux | mort (autorité, gouvernance)

    @property
    def location(self) -> str:
        return f"{self.repo}/{self.path}:{self.start_line}-{self.end_line}"

    @property
    def flag(self) -> str:
        """Étiquette courte d'autorité/récence pour l'affichage (vide si rien à signaler)."""
        tags = []
        if self.status:
            tags.append(self.status)
        yrs = _age_years(self.last_commit, datetime.date.today())
        if yrs is not None and yrs > 2:
            tags.append(f"~{int(yrs)}a")
        return " ".join(tags)


def _reranker(cfg: Config):
    """RRFReranker LanceDB pour fusionner vecteur + BM25 (None si hybride désactivé/absent)."""
    if not cfg.hybrid:
        return None
    try:
        from lancedb.rerankers import RRFReranker
        return RRFReranker()
    except Exception:  # noqa: BLE001 — repli silencieux sur fusion par défaut
        return None


def _to_result(r: dict) -> Result:
    score = float(r.get("_relevance_score", r.get("_distance", 0.0)))
    return Result(repo=r["repo"], path=r["path"], start_line=r["start_line"],
                  end_line=r["end_line"], lang=r["lang"], score=score, text=r["text"],
                  source=r.get("source") or "", last_commit=r.get("last_commit") or "",
                  status=r.get("status") or "")


def _age_years(last_commit: str, today: datetime.date) -> float | None:
    if not last_commit:
        return None
    try:
        d = datetime.date.fromisoformat(last_commit[:10])
    except ValueError:
        return None
    return (today - d).days / 365.25


def _meta_penalty(r: Result, today: datetime.date) -> float:
    """Pénalité (nudge borné) selon autorité et récence ; négatif = remonte. La pertinence
    reste dominante (cf. `_meta_rerank`) — l'autorité/récence ne fait que départager."""
    st = (r.status or "").lower()
    pen = 0.0
    if st == "mort":
        pen += 100.0        # code mort : coule en bas du top-k
    elif st == "douteux":
        pen += 2.0
    elif st == "actif":
        pen -= 1.0
    yrs = _age_years(r.last_commit, today)
    if yrs is not None:
        if yrs < 1:
            pen -= 1.0
        elif yrs > 3:
            pen += 2.0
        elif yrs > 2:
            pen += 1.0
    return pen


def _meta_rerank(results: list[Result], k: int, today: datetime.date | None = None) -> list[Result]:
    """Réordonne par (rang de pertinence + pénalité autorité/récence). Tri stable : un
    `mort` coule, un `actif`/récent remonte de quelques places, mais la pertinence prime."""
    today = today or datetime.date.today()
    ordered = sorted(enumerate(results), key=lambda p: p[0] + _meta_penalty(p[1], today))
    return [r for _, r in ordered][:k]


def _llm_rerank(client, query: str, results: list[Result], k: int, cfg: Config,
                throttle: embed.Throttle) -> list[Result]:
    """Dernière passe : un chat Mistral réordonne les candidats (Mistral n'a pas d'endpoint
    rerank dédié). Tout échec garde l'ordre RRF d'origine."""
    cand = "\n".join(
        f"[{i}] {r.location} ({r.lang}): " + " ".join(r.text.split())[:200]
        for i, r in enumerate(results))
    messages = [
        {"role": "system", "content":
            "Tu classes des extraits de code par pertinence pour une requête. Réponds en "
            'JSON : {"order": [<indices du plus au moins pertinent>]}.'},
        {"role": "user", "content": f"Requête : {query}\n\nCandidats :\n{cand}"},
    ]
    attempt = 0
    while True:
        throttle.wait()
        try:
            resp = client.chat.complete(model=cfg.context_model, messages=messages,
                                        response_format={"type": "json_object"},
                                        temperature=0.0)
            order = json.loads(resp.choices[0].message.content or "{}").get("order", [])
            seen, ranked = set(), []
            for i in order:
                if isinstance(i, int) and 0 <= i < len(results) and i not in seen:
                    ranked.append(results[i])
                    seen.add(i)
            ranked.extend(r for i, r in enumerate(results) if i not in seen)
            return ranked[:k]
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if attempt > cfg.max_retries or not embed._is_rate_limit(exc):
                return results[:k]
            time.sleep(min(2 ** attempt, 30))


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
    """Top-`k` chunks les plus pertinents pour `question`, filtrables par repo/langage.

    Pipeline (selon la config) : réécriture de la requête (chat) → embedding → recherche
    hybride vecteur + BM25 fusionnée par RRF → rerank LLM optionnel. Le `text` renvoyé
    reste le chunk **brut**. Signature stable (réutilisée par le wrapper MCP d'ic-data-bot)."""
    cfg = config or load_config()
    if not cfg.api_key:
        raise RuntimeError("MISTRAL_API_KEY manquante : impossible d'embedder la requête.")
    client = embed.make_client(cfg.api_key)
    throttle = embed.Throttle(cfg.min_interval_s)
    query = question
    if cfg.query_rewrite:
        query = rewrite.rewrite_query(client, question, model=cfg.context_model,
                                      throttle=throttle, max_retries=cfg.max_retries)
    qvec = embed.embed_query(client, query, model=cfg.model, dim=cfg.dim,
                             max_input_chars=cfg.max_input_chars, throttle=throttle,
                             max_retries=cfg.max_retries)
    db = store.connect(cfg.db_dir)
    # Sur-échantillonne quand un rerank va réordonner (LLM ou autorité/récence).
    over = k * 3 if (cfg.rerank == "llm" or cfg.meta_rerank) else k
    rows = store.search(db, qvec, k=over, where=_where(repos, lang),
                        query_text=query if cfg.hybrid else None,
                        hybrid=cfg.hybrid, reranker=_reranker(cfg))
    results = [_to_result(r) for r in rows]
    if cfg.rerank == "llm" and len(results) > 1:
        results = _llm_rerank(client, query, results, over, cfg, throttle)
    if cfg.meta_rerank:
        results = _meta_rerank(results, k)   # autorité (statut) + récence après la pertinence
    return results[:k]


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
        flag = f" [{r.flag}]" if r.flag else ""
        print(f"\n#{i}  {r.location}  ({r.lang}, score {r.score:.3f}){flag}")
        snippet = r.text if args.full else "\n".join(r.text.splitlines()[:15])
        print(snippet.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
