"""Stockage vectoriel LanceDB (fichier local).

`lancedb` est importé paresseusement (cf. embed.py). Table `code_chunks` : un vecteur
par chunk, plus les métadonnées de localisation. L'état d'indexation (sha par fichier)
vit dans la table elle-même — pas de fichier d'état séparé.
"""
from __future__ import annotations

from typing import Any

from .config import FTS_COLUMN, TABLE_NAME


def connect(db_dir: Any) -> Any:
    import lancedb
    db_dir = str(db_dir)
    return lancedb.connect(db_dir)


def _table_names(db: Any) -> list[str]:
    # list_tables() (lancedb récent) renvoie un objet paginé .tables ; table_names()
    # (déprécié) renvoie une liste. On supporte les deux.
    lister = getattr(db, "list_tables", None) or db.table_names
    res = lister()
    return list(getattr(res, "tables", res))


def open_table(db: Any) -> Any | None:
    return db.open_table(TABLE_NAME) if TABLE_NAME in _table_names(db) else None


def indexed_shas(db: Any) -> dict[str, str]:
    """{clé fichier → sha} déjà en base ({} si la table n'existe pas encore)."""
    tbl = open_table(db)
    if tbl is None:
        return {}
    data = tbl.to_arrow().select(["key", "sha"]).to_pydict()
    return dict(zip(data["key"], data["sha"]))


def indexed_vers(db: Any) -> dict[str, str]:
    """{clé fichier → embed_ver}. {} si la table (ancienne) n'a pas la colonne, ce qui
    force la réindexation de tout (l'index pré-contexte doit être reconstruit)."""
    tbl = open_table(db)
    if tbl is None:
        return {}
    if "embed_ver" not in tbl.schema.names or "key" not in tbl.schema.names:
        return {}
    data = tbl.to_arrow().select(["key", "embed_ver"]).to_pydict()
    return dict(zip(data["key"], data["embed_ver"]))


def ensure_fts_index(db: Any) -> None:
    """(Re)construit l'index full-text BM25 sur la colonne contextualisée (idempotent)."""
    tbl = open_table(db)
    if tbl is None or FTS_COLUMN not in tbl.schema.names:
        return
    tbl.create_fts_index(FTS_COLUMN, replace=True)


def _esc(value: str) -> str:
    return value.replace("'", "''")


def delete_keys(db: Any, keys: list[str]) -> None:
    tbl = open_table(db)
    if tbl is None or not keys:
        return
    # Filtre IN borné pour éviter une expression géante.
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        in_list = ", ".join(f"'{_esc(k)}'" for k in chunk)
        tbl.delete(f"key IN ({in_list})")


def add_rows(db: Any, rows: list[dict]) -> None:
    if not rows:
        return
    tbl = open_table(db)
    if tbl is None:
        db.create_table(TABLE_NAME, data=rows)
    else:
        tbl.add(rows)


def _has_fts(tbl: Any) -> bool:
    """Vrai si un index FTS existe sur la colonne contextualisée (sinon hybride impossible)."""
    if FTS_COLUMN not in getattr(tbl, "schema").names:
        return False
    try:
        return any(getattr(ix, "name", "") and FTS_COLUMN in str(getattr(ix, "columns", ""))
                   for ix in tbl.list_indices())
    except Exception:  # noqa: BLE001 — API d'introspection variable selon version
        return True  # colonne présente : on tente l'hybride, repli géré par l'appelant


def search(db: Any, query_vector: list[float], *, k: int, where: str | None = None,
           metric: str = "cosine", query_text: str | None = None, hybrid: bool = False,
           reranker: Any = None) -> list[dict]:
    """Recherche top-k. Mode hybride (vecteur + BM25 sur `contextualized`, fusionnés par
    `reranker`) si `hybrid` et `query_text` fournis et l'index FTS présent ; sinon vecteur seul."""
    tbl = open_table(db)
    if tbl is None:
        return []
    if hybrid and query_text and _has_fts(tbl):
        q = (tbl.search(query_type="hybrid", vector_column_name="vector",
                        fts_columns=FTS_COLUMN)
             .vector(query_vector).text(query_text))
        if reranker is not None:
            q = q.rerank(reranker)
        q = q.limit(k)
        if where:
            q = q.where(where)
        return q.to_list()
    q = tbl.search(query_vector).metric(metric).limit(k)
    if where:
        q = q.where(where)
    return q.to_list()
