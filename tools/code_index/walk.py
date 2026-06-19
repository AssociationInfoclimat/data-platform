"""Découverte des fichiers à indexer, selon le manifeste.

Pur stdlib : aucun import lourd, pour que les tests tournent en CI (pytest + pyyaml).
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# Extension → étiquette de langage (métadonnée de filtrage à la recherche).
LANG_BY_EXT = {
    ".php": "php", ".js": "js", ".ts": "ts", ".py": "python", ".ncl": "ncl",
    ".sh": "shell", ".sql": "sql", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".xml": "xml", ".jinja2": "jinja", ".j2": "jinja", ".conf": "conf", ".ini": "ini",
    ".toml": "toml", ".md": "markdown", ".map": "mapfile",
}


@dataclass(frozen=True)
class SourceFile:
    repo: str            # nom du repo (ex. site-infoclimat)
    path: str            # chemin relatif au repo, en POSIX (ex. forums/index.php)
    abspath: Path        # chemin absolu sur disque
    lang: str            # étiquette de langage

    @property
    def key(self) -> str:
        """Identifiant stable d'un fichier dans l'index (repo + chemin relatif)."""
        return f"{self.repo}/{self.path}"


def is_excluded(rel_posix: str, exclude_dirs: set[str], exclude_globs: list[str]) -> bool:
    parts = rel_posix.split("/")
    if exclude_dirs.intersection(parts[:-1]):
        return True
    base = parts[-1]
    return any(fnmatch.fnmatch(rel_posix, g) or fnmatch.fnmatch(base, g) for g in exclude_globs)


def _looks_binary(abspath: Path, sniff_bytes: int = 1024) -> bool:
    try:
        with abspath.open("rb") as fh:
            return b"\x00" in fh.read(sniff_bytes)
    except OSError:
        return True


def iter_files(manifest: dict, base_dir: Path, *, repos: list[str] | None = None,
               max_file_bytes: int = 2_000_000) -> Iterator[SourceFile]:
    """Itère les fichiers source des repos du manifeste (filtrables par `repos`).

    Applique, dans l'ordre : exclusion de dossier, exclusion par motif, filtre
    d'extension, taille max, détection de binaire.
    """
    include_ext = {e.lower() for e in manifest.get("include_ext", [])}
    exclude_dirs = set(manifest.get("exclude_dirs", []))
    exclude_globs = list(manifest.get("exclude_globs", []))
    # Exclusions PAR REPO (motifs relatifs au repo) : ex. retirer la gouvernance data-platform
    # (catalog/contracts/inventory/lineage/…) du corpus CODE — elle est déjà dans docs_chunks,
    # et sa prose enterrait le vrai code applicatif dans search_code.
    per_repo = manifest.get("exclude_per_repo", {}) or {}
    wanted = set(repos) if repos else None

    for repo in manifest.get("repos", []):
        if wanted is not None and repo not in wanted:
            continue
        root = (base_dir / repo).resolve()
        if not root.is_dir():
            continue
        repo_globs = exclude_globs + list(per_repo.get(repo, []))
        for abspath in sorted(root.rglob("*")):
            if not abspath.is_file():
                continue
            rel = abspath.relative_to(root).as_posix()
            if is_excluded(rel, exclude_dirs, repo_globs):
                continue
            if abspath.suffix.lower() not in include_ext:
                continue
            try:
                if abspath.stat().st_size > max_file_bytes:
                    continue
            except OSError:
                continue
            if _looks_binary(abspath):
                continue
            yield SourceFile(repo=repo, path=rel, abspath=abspath,
                             lang=LANG_BY_EXT.get(abspath.suffix.lower(), "text"))


def iter_docs(manifest: dict, base_dir: Path, *, max_file_bytes: int = 2_000_000) -> Iterator[SourceFile]:
    """Itère le corpus « docs » (section `docs` du manifeste) : globs explicites sous un repo
    (data-platform). Contrairement à `iter_files` (filtre d'extension), on suit des motifs
    précis (contrats, inventory, catalog, audits…)."""
    spec = manifest.get("docs") or {}
    repo = spec.get("repo", "data-platform")
    root = (base_dir / repo).resolve()
    if not root.is_dir():
        return
    seen: set[str] = set()
    for glob in spec.get("include_globs", []):
        for abspath in sorted(root.glob(glob)):
            if not abspath.is_file():
                continue
            rel = abspath.relative_to(root).as_posix()
            if rel in seen:
                continue
            try:
                if abspath.stat().st_size > max_file_bytes or _looks_binary(abspath):
                    continue
            except OSError:
                continue
            seen.add(rel)
            yield SourceFile(repo=repo, path=rel, abspath=abspath,
                             lang=LANG_BY_EXT.get(abspath.suffix.lower(), "text"))
