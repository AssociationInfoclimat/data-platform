"""Métadonnées d'autorité et de récence par fichier (source, dernier commit, statut).

Objectif : au-delà de la pertinence sémantique, savoir si un chunk vient d'un repo
**moderne** (GitHub) ou **legacy** (GitLab), s'il a bougé récemment, et s'il est **actif /
douteux / mort** selon la gouvernance. Le rerank de `search.py` s'en sert pour ne pas laisser
du vieux code (pertinent en 2024 mais plus en 2026) saturer le top-k.

Trois signaux :
- ``source``      : github | gitlab | other — d'après le remote git du repo.
- ``last_commit`` : date (YYYY-MM-DD) du dernier commit touchant le fichier (récence).
- ``status``      : actif | douteux | mort — depuis ``data-platform/inventory/pipelines.yaml``
                    (champ status), mappé par ``repo/script`` → autorité côté gouvernance.

Le sidecar JSON est calculé EN LOCAL (le build sur la VM ne reçoit pas les ``.git``) puis
livré avec l'index ; consommé à l'indexation (`index.py`) et par l'apply métadonnée-seule
(`store.rebuild_with_fts`, sans ré-embedding). `git`/`yaml` ne sont touchés qu'ici.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _git(repo_dir: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo_dir), *args],
                           capture_output=True, text=True, timeout=120)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_source(repo_dir: Path) -> str:
    """github | gitlab | other, d'après le remote `origin`."""
    url = _git(repo_dir, "remote", "get-url", "origin").strip().lower()
    if "github.com" in url:
        return "github"
    if "gitlab" in url or "vcs.infoclimat" in url:
        return "gitlab"
    return "other"


def file_last_commits(repo_dir: Path) -> dict[str, str]:
    """{chemin relatif → 'YYYY-MM-DD' du dernier commit}, en une passe `git log`.

    `git log --name-only` liste les commits du plus récent au plus ancien ; la 1ʳᵉ
    occurrence d'un fichier est donc son dernier commit."""
    out: dict[str, str] = {}
    cur = ""
    for line in _git(repo_dir, "log", "--no-renames", "--name-only",
                     "--format=__C__%cs").splitlines():
        if line.startswith("__C__"):
            cur = line[5:].strip()
        elif line.strip() and cur:
            out.setdefault(line.strip(), cur)  # 1ʳᵉ vue = plus récente
    return out


def inventory_status(base_dir: Path) -> dict[str, str]:
    """{ 'repo/script' → status } depuis l'inventaire de la data-platform."""
    import yaml
    p = Path(base_dir) / "data-platform" / "inventory" / "pipelines.yaml"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    items = data.get("pipelines") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for it in items or []:
        repo, script = it.get("repo"), it.get("script")
        st = it.get("status") or it.get("statut")
        if repo and script and st:
            out[f"{repo}/{script}"] = st
    return out


def build_sidecar(base_dir: Any, repos: list[str]) -> dict:
    """Sidecar { repo_source, last_commit, status } pour les repos donnés."""
    base = Path(base_dir)
    last_commit: dict[str, str] = {}
    rsource: dict[str, str] = {}
    for repo in repos:
        rd = base / repo
        rsource[repo] = repo_source(rd) if (rd / ".git").is_dir() else "other"
        if (rd / ".git").is_dir():
            for rel, dt in file_last_commits(rd).items():
                last_commit[f"{repo}/{rel}"] = dt
    return {"repo_source": rsource, "last_commit": last_commit,
            "status": inventory_status(base)}


def row_meta(sidecar: dict, repo: str, key: str) -> dict[str, str]:
    """Métadonnées (source/last_commit/status) pour un fichier `key` = 'repo/chemin'."""
    return {
        "source": (sidecar.get("repo_source") or {}).get(repo, "other"),
        "last_commit": (sidecar.get("last_commit") or {}).get(key, ""),
        "status": (sidecar.get("status") or {}).get(key, ""),
    }


def main(argv: list[str]) -> int:
    import argparse

    from .config import load_config, load_manifest
    ap = argparse.ArgumentParser(description="Génère le sidecar de métadonnées (source/date/statut).")
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--base-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True, help="Fichier JSON de sortie.")
    args = ap.parse_args(argv)

    cfg = load_config()
    base = args.base_dir or cfg.base_dir
    manifest = load_manifest(args.manifest)
    sidecar = build_sidecar(base, manifest.get("repos", []))
    args.out.write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
    nb_dates = len(sidecar["last_commit"])
    nb_status = len(sidecar["status"])
    print(f"Sidecar écrit : {args.out} — {len(sidecar['repo_source'])} repos, "
          f"{nb_dates} dates fichier, {nb_status} fichiers avec statut gouvernance.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
