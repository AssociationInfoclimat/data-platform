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

# LanceDB sur peu de cœurs : le builder FTS natif deadlock (futex_wait, 0 % CPU) quand les
# réservations de threads IO ≥ nb de CPU — vérifié, et cf. lancedb/lancedb#2326. Sur une
# petite machine (≤4 cœurs) on force des pools IO/CPU distincts pour casser l'interblocage.
# `setdefault` ⇒ surchargeable ; DOIT être posé avant tout import de lancedb (fait ici car
# `config` est importé avant `store`, qui importe lancedb paresseusement).
if (os.cpu_count() or 1) <= 4:
    os.environ.setdefault("LANCE_IO_THREADS", "2")
    os.environ.setdefault("LANCE_CPU_THREADS", "4")

_PKG_DIR = Path(__file__).resolve().parent
# _PKG_DIR = .../infoclimat/data-platform/tools/code_index → parents[2] = .../infoclimat,
# dossier qui contient les clones siblings (site-infoclimat, infrapilot, …).
_WORKSPACE_ROOT = _PKG_DIR.parents[2]

DEFAULT_MANIFEST = _PKG_DIR / "manifest.yaml"
DEFAULT_DB_DIR = _PKG_DIR / ".lancedb"
TABLE_NAME = "code_chunks"
EMBED_MODEL = "codestral-embed-2505"
CONTEXT_MODEL = "mistral-small-latest"   # chat bon marché pour situer les chunks
FTS_COLUMN = "contextualized"            # colonne indexée en BM25 (contexte + code)

# Version de la stratégie d'indexation (contexte + texte embeddé). Stampée sur chaque
# ligne (`embed_ver`). La bumper invalide l'index : tout fichier dont la version diffère
# est ré-embeddé, même si son sha256 n'a pas changé (le diff par sha ne voit pas un
# changement de stratégie de contexte).
EMBED_VERSION = "ctx-v1"


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
    context_mode: str             # contexte préfixé à l'embedding : llm | struct | off
    context_model: str            # modèle chat Mistral pour le contexte LLM
    hybrid: bool                  # recherche hybride vecteur + BM25 (sinon vecteur seul)
    rerank: str                   # fusion/rerank : rrf | llm | none
    query_rewrite: bool           # réécrire la requête (chat) avant recherche
    max_context_file_chars: int   # taille max d'un fichier envoyé en un appel contexte
    concurrency: int              # appels de contexte LLM concurrents à l'indexation (I/O-bound)
    meta_rerank: bool             # rerank par autorité (statut) + récence après l'hybride
    meta_path: str | None         # sidecar JSON de métadonnées (source/date/statut) à l'indexation


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_choice(name: str, default: str, allowed: set[str]) -> str:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw if raw in allowed else default


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
        # ≤ 8192 : codestral-embed plafonne à 8192 tokens/entrée, et tokens ≤ caractères,
        # donc tronquer à 8000 caractères garantit de ne jamais dépasser la limite (les
        # chunks contextualisés normaux ~3,8k car. ne sont pas touchés).
        max_input_chars=_env_int("CODE_INDEX_MAX_INPUT_CHARS", 8_000),
        min_interval_s=_env_float("CODE_INDEX_MIN_INTERVAL_S", 0.5),
        max_retries=_env_int("CODE_INDEX_MAX_RETRIES", 5),
        context_mode=_env_choice("CODE_INDEX_CONTEXT", "llm", {"llm", "struct", "off"}),
        context_model=os.environ.get("CODE_INDEX_CONTEXT_MODEL", CONTEXT_MODEL),
        hybrid=_env_bool("CODE_INDEX_HYBRID", True),
        rerank=_env_choice("CODE_INDEX_RERANK", "rrf", {"rrf", "llm", "none"}),
        query_rewrite=_env_bool("CODE_INDEX_QUERY_REWRITE", True),
        max_context_file_chars=_env_int("CODE_INDEX_MAX_CONTEXT_FILE_CHARS", 40_000),
        concurrency=max(1, _env_int("CODE_INDEX_CONCURRENCY", 1)),
        meta_rerank=_env_bool("CODE_INDEX_META_RERANK", True),
        meta_path=os.environ.get("CODE_INDEX_META") or None,
    )


def load_manifest(path: Path | None = None) -> dict:
    p = path or DEFAULT_MANIFEST
    return yaml.safe_load(p.read_text(encoding="utf-8"))
