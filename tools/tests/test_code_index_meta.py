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


def test_web_base_github_and_gitlab() -> None:
    assert meta._web_base("https://github.com/AssociationInfoclimat/podaac-sst-mur.git",
                          "github") == "https://github.com/AssociationInfoclimat/podaac-sst-mur"
    assert meta._web_base("git@github.com:AssociationInfoclimat/data-platform.git",
                          "github") == "https://github.com/AssociationInfoclimat/data-platform"
    assert meta._web_base("ssh://git@vcs.infoclimat.net:59833/responsablestechnique/site-infoclimat.git",
                          "gitlab") == "https://vcs.infoclimat.net/responsablestechnique/site-infoclimat"
    assert meta._web_base("https://vcs.infoclimat.net/externes/appli-ios.git",
                          "gitlab") == "https://vcs.infoclimat.net/externes/appli-ios"
    assert meta._web_base("", "github") == ""
    assert meta._web_base("whatever", "other") == ""


def test_chunk_url_github_gitlab_and_missing() -> None:
    sidecar = {
        "repo_source": {"podaac-sst-mur": "github", "site-infoclimat": "gitlab", "x": "other"},
        "repo_ref": {"podaac-sst-mur": "abc123", "site-infoclimat": "def456"},
        "web_base": {"podaac-sst-mur": "https://github.com/AssociationInfoclimat/podaac-sst-mur",
                     "site-infoclimat": "https://vcs.infoclimat.net/responsablestechnique/site-infoclimat"},
    }
    assert meta.chunk_url(sidecar, "podaac-sst-mur", "src/podaac_sst_MUR.php", 218, 292) == \
        "https://github.com/AssociationInfoclimat/podaac-sst-mur/blob/abc123/src/podaac_sst_MUR.php#L218-L292"
    assert meta.chunk_url(sidecar, "site-infoclimat", "include/MeteoFrance/combined.php", 35, 36) == \
        "https://vcs.infoclimat.net/responsablestechnique/site-infoclimat/-/blob/def456/include/MeteoFrance/combined.php#L35-36"
    # repo sans ref/base → vide (pas d'URL fausse)
    assert meta.chunk_url(sidecar, "x", "a.py", 1, 2) == ""
    assert meta.chunk_url({}, "podaac-sst-mur", "a.py", 1, 2) == ""
