"""Stockage vectoriel LanceDB (fichier local).

`lancedb` est importé paresseusement (cf. embed.py). Une table par corpus dans la MÊME base :
`code_chunks` (code) et `docs_chunks` (gouvernance data-platform). Toutes les fonctions
acceptent `table=` (défaut `code_chunks`). Un vecteur par chunk + métadonnées de localisation ;
l'état d'indexation (sha par fichier) vit dans la table elle-même — pas de fichier d'état.
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


def open_table(db: Any, table: str = TABLE_NAME) -> Any | None:
    return db.open_table(table) if table in _table_names(db) else None


def indexed_shas(db: Any, table: str = TABLE_NAME) -> dict[str, str]:
    """{clé fichier → sha} déjà en base ({} si la table n'existe pas encore)."""
    tbl = open_table(db, table)
    if tbl is None:
        return {}
    data = tbl.to_arrow().select(["key", "sha"]).to_pydict()
    return dict(zip(data["key"], data["sha"]))


def indexed_vers(db: Any, table: str = TABLE_NAME) -> dict[str, str]:
    """{clé fichier → embed_ver}. {} si la table (ancienne) n'a pas la colonne, ce qui
    force la réindexation de tout (l'index pré-contexte doit être reconstruit)."""
    tbl = open_table(db, table)
    if tbl is None:
        return {}
    if "embed_ver" not in tbl.schema.names or "key" not in tbl.schema.names:
        return {}
    data = tbl.to_arrow().select(["key", "embed_ver"]).to_pydict()
    return dict(zip(data["key"], data["embed_ver"]))


def ensure_fts_index(db: Any, table: str = TABLE_NAME) -> None:
    """(Re)construit l'index full-text BM25 sur la colonne contextualisée (idempotent).

    NB : le builder FTS natif de LanceDB **se bloque (deadlock)** sur une table
    MULTI-FRAGMENT à l'échelle (~50k lignes) — l'indexation par lots en produit beaucoup.
    Pour le build complet, utiliser `rebuild_with_fts()` qui compacte d'abord. Cette
    fonction reste correcte sur une table déjà mono-fragment (petites tables, tests)."""
    tbl = open_table(db, table)
    if tbl is None or FTS_COLUMN not in tbl.schema.names:
        return
    tbl.create_fts_index(FTS_COLUMN, replace=True)


def rebuild_with_fts(db: Any, meta: dict | None = None, table: str = TABLE_NAME) -> None:
    """Compacte la table en UN SEUL fragment puis construit l'index FTS BM25.

    Le builder FTS natif de LanceDB 0.33 deadlock sur une table multi-fragment (vérifié :
    OK mono-fragment, blocage à ~11 fragments même avec 8 workers Tokio ; `optimize()` ne
    suffit pas). On réécrit donc la table via `to_arrow()` → `create_table` (un seul fichier,
    <1M lignes ⇒ 1 fragment), puis on indexe. `rename_table` n'existe pas en LanceDB OSS, donc
    drop + recreate ; sans risque ici car l'indexation écrit dans une base jetable, basculée
    en live par swap de répertoire au déploiement. Charge toute la table en RAM le temps de la
    réécriture (~quelques centaines de Mo pour ~50k chunks).

    Si `meta` (sidecar de `meta.build_sidecar`) est fourni, (ré)injecte les colonnes
    `source`/`last_commit`/`status` sur chaque ligne SANS ré-embedder (les vecteurs sont
    préservés) — backfill métadonnée bon marché."""
    tbl = open_table(db, table)
    if tbl is None or FTS_COLUMN not in tbl.schema.names:
        return
    data: Any = tbl.to_arrow()
    if meta is not None:
        data = _inject_meta_columns(data, meta)  # colonnes au niveau Arrow (vecteurs intacts)
    db.drop_table(table)
    new = db.create_table(table, data=data)          # réécriture en un seul fragment
    new.create_fts_index(FTS_COLUMN, replace=True)   # FTS sur mono-fragment → pas de deadlock


def _inject_meta_columns(data: Any, meta: dict) -> Any:
    """(Ré)injecte source/last_commit/status comme colonnes Arrow, sans matérialiser les
    vecteurs en objets Python (mémoire bornée sur petite VM)."""
    import pyarrow as pa

    from . import meta as _meta
    keys = data.column("key").to_pylist()
    repos = data.column("repo").to_pylist()
    paths = data.column("path").to_pylist()
    starts = data.column("start_line").to_pylist()
    ends = data.column("end_line").to_pylist()
    rsource = meta.get("repo_source") or {}
    lc = meta.get("last_commit") or {}
    st = meta.get("status") or {}
    cols = {
        "source": [rsource.get(r, "other") for r in repos],
        "last_commit": [lc.get(k, "") for k in keys],
        "status": [st.get(k, "") for k in keys],
        "source_url": [_meta.chunk_url(meta, repos[i], paths[i], starts[i], ends[i])
                       for i in range(len(keys))],
    }
    for name, vals in cols.items():
        arr = pa.array(vals, type=pa.string())
        if name in data.schema.names:
            data = data.set_column(data.schema.get_field_index(name), name, arr)
        else:
            data = data.append_column(name, arr)
    return data


def _esc(value: str) -> str:
    return value.replace("'", "''")


def delete_keys(db: Any, keys: list[str], table: str = TABLE_NAME) -> None:
    tbl = open_table(db, table)
    if tbl is None or not keys:
        return
    # Filtre IN borné pour éviter une expression géante.
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        in_list = ", ".join(f"'{_esc(k)}'" for k in chunk)
        tbl.delete(f"key IN ({in_list})")


def add_rows(db: Any, rows: list[dict], table: str = TABLE_NAME) -> None:
    if not rows:
        return
    tbl = open_table(db, table)
    if tbl is None:
        db.create_table(table, data=rows)
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
           reranker: Any = None, table: str = TABLE_NAME) -> list[dict]:
    """Recherche top-k. Mode hybride (vecteur + BM25 sur `contextualized`, fusionnés par
    `reranker`) si `hybrid` et `query_text` fournis et l'index FTS présent ; sinon vecteur seul."""
    tbl = open_table(db, table)
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
