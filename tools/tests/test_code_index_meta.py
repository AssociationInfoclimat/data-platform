"""Tests des métadonnées d'autorité/récence (code_index.meta)."""
from __future__ import annotations

from pathlib import Path

import pytest

from code_index import meta

pytest.importorskip("yaml")


def _write_inventory(base: Path) -> None:
    inv = base / "data-platform" / "inventory"
    inv.mkdir(parents=True)
    (inv / "pipelines.yaml").write_text(
        "pipelines:\n"
        "  - id: p1\n    repo: site-infoclimat\n    script: cron/radarmf.php\n    status: mort\n"
        "  - id: p2\n    repo: calc-indicateur-realtime\n    script: src/main.php\n    status: actif\n"
        "  - id: p3\n    repo: x\n    script: y.py\n    statut: douteux\n",  # champ 'statut' aussi
        encoding="utf-8")


def test_inventory_status_maps_repo_script(tmp_path: Path) -> None:
    _write_inventory(tmp_path)
    st = meta.inventory_status(tmp_path)
    assert st["site-infoclimat/cron/radarmf.php"] == "mort"
    assert st["calc-indicateur-realtime/src/main.php"] == "actif"
    assert st["x/y.py"] == "douteux"          # alias 'statut' accepté


def test_inventory_status_absent(tmp_path: Path) -> None:
    assert meta.inventory_status(tmp_path) == {}


def test_row_meta_lookup() -> None:
    sidecar = {
        "repo_source": {"podaac-sst-mur": "github", "site-infoclimat": "gitlab"},
        "last_commit": {"podaac-sst-mur/src/x.php": "2025-11-26"},
        "status": {"site-infoclimat/cron/radarmf.php": "mort"},
    }
    assert meta.row_meta(sidecar, "podaac-sst-mur", "podaac-sst-mur/src/x.php") == {
        "source": "github", "last_commit": "2025-11-26", "status": ""}
    assert meta.row_meta(sidecar, "site-infoclimat", "site-infoclimat/cron/radarmf.php") == {
        "source": "gitlab", "last_commit": "", "status": "mort"}
    # repo inconnu → source 'other', champs vides
    assert meta.row_meta(sidecar, "inconnu", "inconnu/a.py") == {
        "source": "other", "last_commit": "", "status": ""}


def test_build_sidecar_without_git(tmp_path: Path) -> None:
    # Repos sans .git → source 'other', pas de dates ; statut depuis l'inventaire.
    _write_inventory(tmp_path)
    (tmp_path / "site-infoclimat").mkdir()
    sc = meta.build_sidecar(tmp_path, ["site-infoclimat"])
    assert sc["repo_source"]["site-infoclimat"] == "other"
    assert sc["last_commit"] == {}
    assert sc["status"]["site-infoclimat/cron/radarmf.php"] == "mort"


def test_repo_source_classification() -> None:
    # Pas de remote (dossier sans .git) → other ; la logique de classement est testée
    # indirectement, l'essentiel est de ne jamais lever.
    assert meta.repo_source(Path("/nonexistent-xyz")) == "other"
