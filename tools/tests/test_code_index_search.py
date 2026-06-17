"""Tests de la couche requête (code_index.search) : clause WHERE + mapping, sans réseau."""
from __future__ import annotations

from pathlib import Path

import pytest

import datetime

from code_index import search as search_mod
from code_index.config import Config
from code_index.search import Result, _meta_rerank, _where, search_code


def _r(repo: str, status: str = "", last_commit: str = "") -> Result:
    return Result(repo=repo, path="f.py", start_line=1, end_line=2, lang="py",
                  score=0.0, text="x", status=status, last_commit=last_commit)


_TODAY = datetime.date(2026, 6, 17)


def test_meta_rerank_sinks_dead_code() -> None:
    # 'mort' en tête de pertinence doit couler ; le suivant remonte.
    res = [_r("a", status="mort"), _r("b", status="actif", last_commit="2026-05-01")]
    out = _meta_rerank(res, k=2, today=_TODAY)
    assert [x.repo for x in out] == ["b", "a"]


def test_meta_rerank_keeps_relevance_dominant() -> None:
    # Un actif récent en position 3 ne dépasse pas un résultat pertinent neutre en position 0
    # (nudge borné : -2 max), mais passe devant un douteux ancien.
    res = [_r("top"), _r("old", status="douteux", last_commit="2021-01-01"),
           _r("fresh", status="actif", last_commit="2026-06-01")]
    out = _meta_rerank(res, k=3, today=_TODAY)
    assert out[0].repo == "top"            # pertinence #0 garde la tête
    assert out.index(_pick(out, "fresh")) < out.index(_pick(out, "old"))


def _pick(results, repo):
    return next(r for r in results if r.repo == repo)


def test_where_clause_building() -> None:
    assert _where(None, None) is None
    assert _where(["a", "b"], None) == "repo IN ('a', 'b')"
    assert _where(None, "php") == "lang = 'php'"
    assert _where(["a"], "php") == "repo IN ('a') AND lang = 'php'"


def test_where_escapes_quotes() -> None:
    assert _where(["o'brien"], None) == "repo IN ('o''brien')"


def _cfg() -> Config:
    # Pipeline simple (vecteur seul, sans réécriture/rerank) pour tester le mapping isolément ;
    # les modes contextuel/hybride ont leurs propres tests.
    return Config(base_dir=Path("."), db_dir=Path("."), model="m", dim=None, api_key="k",
                  batch_size=8, max_batch_chars=50_000, chunk_chars=3000, overlap_chars=1000,
                  max_file_bytes=1, max_input_chars=100, min_interval_s=0.0, max_retries=1,
                  context_mode="off", context_model="m", hybrid=False, rerank="none",
                  query_rewrite=False, max_context_file_chars=40_000, concurrency=1,
                  meta_rerank=False, meta_path=None)


def test_search_code_maps_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_mod.embed, "make_client", lambda key: object())
    monkeypatch.setattr(search_mod.embed, "embed_query", lambda *a, **k: [0.1, 0.2])
    monkeypatch.setattr(search_mod.store, "connect", lambda d: object())
    captured = {}

    def _fake_search(db, qvec, *, k, where, **kw):  # noqa: ANN001
        captured["k"] = k
        captured["where"] = where
        return [{"repo": "site-infoclimat", "path": "forums/index.php", "start_line": 1,
                 "end_line": 20, "lang": "php", "text": "<?php …", "_distance": 0.12}]

    monkeypatch.setattr(search_mod.store, "search", _fake_search)

    results = search_code("routing forums", k=3, repos=["site-infoclimat"], lang="php",
                          config=_cfg())
    assert captured["k"] == 3
    assert captured["where"] == "repo IN ('site-infoclimat') AND lang = 'php'"
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, Result)
    assert r.location == "site-infoclimat/forums/index.php:1-20"
    assert r.score == pytest.approx(0.12)


def test_search_code_requires_api_key() -> None:
    cfg = _cfg().__class__(**{**_cfg().__dict__, "api_key": None})
    with pytest.raises(RuntimeError):
        search_code("x", config=cfg)


def test_search_code_rewrites_and_passes_hybrid(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg().__class__(**{**_cfg().__dict__, "query_rewrite": True, "hybrid": True,
                              "rerank": "rrf"})
    monkeypatch.setattr(search_mod.embed, "make_client", lambda key: object())
    monkeypatch.setattr(search_mod, "_reranker", lambda c: "RRF")
    monkeypatch.setattr(search_mod.rewrite, "rewrite_query",
                        lambda client, q, **kw: "requête réécrite")
    embedded = {}
    monkeypatch.setattr(search_mod.embed, "embed_query",
                        lambda client, text, **kw: embedded.setdefault("text", text) or [0.1])
    monkeypatch.setattr(search_mod.store, "connect", lambda d: object())
    captured = {}

    def _fake_search(db, qvec, *, k, where, query_text=None, hybrid=False, reranker=None):
        captured.update(query_text=query_text, hybrid=hybrid, reranker=reranker)
        return [{"repo": "r", "path": "a.php", "start_line": 1, "end_line": 2, "lang": "php",
                 "text": "code", "_relevance_score": 0.9}]

    monkeypatch.setattr(search_mod.store, "search", _fake_search)
    results = search_code("question", k=2, config=cfg)
    # La requête réécrite est celle qu'on embedde ET qu'on passe au FTS.
    assert embedded["text"] == "requête réécrite"
    assert captured["query_text"] == "requête réécrite"
    assert captured["hybrid"] is True
    assert captured["reranker"] == "RRF"
    assert results[0].score == pytest.approx(0.9)  # score de pertinence hybride
