"""Tests du store LanceDB (code_index.store). Sauté si lancedb non installé (CI)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("lancedb")

from code_index import store  # noqa: E402


def _row(key: str, idx: int, repo: str, vec: list[float], sha: str) -> dict:
    return {"id": f"{key}#{idx}", "key": key, "repo": repo, "path": key.split("/", 1)[1],
            "lang": "php", "start_line": 1, "end_line": 10, "sha": sha, "text": "code",
            "vector": vec}


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
