"""Tests du store LanceDB (code_index.store). Sauté si lancedb non installé (CI)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("lancedb")

from code_index import store  # noqa: E402


def _row(key: str, idx: int, repo: str, vec: list[float], sha: str,
         text: str = "code", contextualized: str | None = None,
         ver: str = "ctx-v1") -> dict:
    return {"id": f"{key}#{idx}", "key": key, "repo": repo, "path": key.split("/", 1)[1],
            "lang": "php", "start_line": 1, "end_line": 10, "sha": sha, "text": text,
            "context": "ctx", "contextualized": contextualized or text,
            "embed_ver": ver, "vector": vec}


def test_add_search_indexed_shas_and_delete(tmp_path: Path) -> None:
    db = store.connect(tmp_path / "db")
    assert store.indexed_shas(db) == {}

    rows = [
        _row("site-infoclimat/a.php", 0, "site-infoclimat", [1.0, 0.0, 0.0], "sha-a"),
        _row("site-infoclimat/b.php", 0, "site-infoclimat", [0.0, 1.0, 0.0], "sha-b"),
        _row("infrapilot/c.yml", 0, "infrapilot", [0.0, 0.0, 1.0], "sha-c"),
    ]
    store.add_rows(db, rows)

    shas = store.indexed_shas(db)
    assert shas == {"site-infoclimat/a.php": "sha-a",
                    "site-infoclimat/b.php": "sha-b",
                    "infrapilot/c.yml": "sha-c"}

    # Plus proche de [0.9, 0.1, 0] = a.php.
    hits = store.search(db, [0.9, 0.1, 0.0], k=1)
    assert hits[0]["key"] == "site-infoclimat/a.php"

    # Filtre repo.
    hits = store.search(db, [0.0, 0.0, 1.0], k=3, where="repo = 'infrapilot'")
    assert {h["repo"] for h in hits} == {"infrapilot"}

    # Suppression par clé.
    store.delete_keys(db, ["site-infoclimat/a.php"])
    assert "site-infoclimat/a.php" not in store.indexed_shas(db)


def test_indexed_vers_roundtrip(tmp_path: Path) -> None:
    db = store.connect(tmp_path / "db")
    store.add_rows(db, [_row("r/a.php", 0, "r", [1.0, 0.0], "s1", ver="ctx-v1"),
                        _row("r/b.php", 0, "r", [0.0, 1.0], "s2", ver="ctx-v1")])
    assert store.indexed_vers(db) == {"r/a.php": "ctx-v1", "r/b.php": "ctx-v1"}


def test_hybrid_search_with_rrf(tmp_path: Path) -> None:
    rerankers = pytest.importorskip("lancedb.rerankers")
    db = store.connect(tmp_path / "db")
    rows = [
        _row("r/auth.php", 0, "r", [1.0, 0.0, 0.0], "s1",
             contextualized="module authentification anti-scraping verification du jeton"),
        _row("r/forum.php", 0, "r", [0.0, 1.0, 0.0], "s2",
             contextualized="routing des forums et affichage des messages"),
        _row("r/map.php", 0, "r", [0.0, 0.0, 1.0], "s3",
             contextualized="generation des cartes isobares et tuiles"),
    ]
    store.add_rows(db, rows)
    store.ensure_fts_index(db)

    # Vecteur neutre : c'est le terme lexical « anti-scraping » qui doit faire remonter auth.php.
    hits = store.search(db, [0.34, 0.33, 0.33], k=3, query_text="anti-scraping jeton",
                        hybrid=True, reranker=rerankers.RRFReranker())
    assert hits, "recherche hybride vide"
    assert hits[0]["key"] == "r/auth.php"
    # Le texte brut reste exposé (pas le texte contextualisé).
    assert hits[0]["text"] == "code"


def test_search_falls_back_to_vector_without_fts(tmp_path: Path) -> None:
    db = store.connect(tmp_path / "db")
    store.add_rows(db, [_row("r/a.php", 0, "r", [1.0, 0.0], "s1"),
                        _row("r/b.php", 0, "r", [0.0, 1.0], "s2")])
    # Pas d'index FTS construit : hybride demandé mais repli vecteur seul (pas d'erreur).
    hits = store.search(db, [0.9, 0.1], k=1, query_text="quoi que ce soit", hybrid=True)
    assert hits[0]["key"] == "r/a.php"
