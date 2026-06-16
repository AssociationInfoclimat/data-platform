"""Configuration de l'index code : chemins, modèle, chunking, throttle.

Tout est surchargeable par variable d'environnement pour rester sans secret en clair
(la clé API Mistral n'est jamais écrite sur disque). Les défauts sont calculés à partir
de l'emplacement du paquet, de sorte que les CLI fonctionnent depuis `tools/`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

_PKG_DIR = Path(__file__).resolve().parent
# _PKG_DIR = .../infoclimat/data-platform/tools/code_index → parents[2] = .../infoclimat,
# dossier qui contient les clones siblings (site-infoclimat, infrapilot, …).
_WORKSPACE_ROOT = _PKG_DIR.parents[2]

DEFAULT_MANIFEST = _PKG_DIR / "manifest.yaml"
DEFAULT_DB_DIR = _PKG_DIR / ".lancedb"
TABLE_NAME = "code_chunks"
EMBED_MODEL = "codestral-embed-2505"


@dataclass(frozen=True)
class Config:
    base_dir: Path                # racine où chercher les repos
    db_dir: Path                  # répertoire LanceDB (artefact local, gitignoré)
    model: str                    # modèle d'embedding Mistral
    dim: int | None               # dimension de sortie (None = native du modèle)
    api_key: str | None           # MISTRAL_API_KEY (requis pour indexer/requêter)
    batch_size: int               # plafond d'inputs par appel embeddings
    max_batch_chars: int          # plafond de caractères cumulés par appel (limite tokens API)
    chunk_chars: int              # taille de fenêtre (caractères)
    overlap_chars: int            # recouvrement entre fenêtres (caractères)
    max_file_bytes: int           # fichiers plus gros = ignorés (générés/dumps)
    max_input_chars: int          # garde-fou par chunk avant envoi à l'API
    min_interval_s: float         # espacement minimal entre appels API (throttle)
    max_retries: int              # tentatives sur 429 / erreur transitoire


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def load_config() -> Config:
    base = os.environ.get("CODE_INDEX_BASE_DIR")
    db = os.environ.get("CODE_INDEX_DIR")
    dim_raw = os.environ.get("CODE_INDEX_DIM")
    return Config(
        base_dir=Path(base).expanduser() if base else _WORKSPACE_ROOT,
        db_dir=Path(db).expanduser() if db else DEFAULT_DB_DIR,
        model=os.environ.get("CODE_INDEX_MODEL", EMBED_MODEL),
        dim=int(dim_raw) if dim_raw else None,
        api_key=os.environ.get("MISTRAL_API_KEY"),
        batch_size=_env_int("CODE_INDEX_BATCH_SIZE", 64),
        max_batch_chars=_env_int("CODE_INDEX_MAX_BATCH_CHARS", 50_000),
        chunk_chars=_env_int("CODE_INDEX_CHUNK_CHARS", 3000),
        overlap_chars=_env_int("CODE_INDEX_OVERLAP_CHARS", 1000),
        max_file_bytes=_env_int("CODE_INDEX_MAX_FILE_BYTES", 2_000_000),
        max_input_chars=_env_int("CODE_INDEX_MAX_INPUT_CHARS", 30_000),
        min_interval_s=_env_float("CODE_INDEX_MIN_INTERVAL_S", 0.5),
        max_retries=_env_int("CODE_INDEX_MAX_RETRIES", 5),
    )


def load_manifest(path: Path | None = None) -> dict:
    p = path or DEFAULT_MANIFEST
    return yaml.safe_load(p.read_text(encoding="utf-8"))
