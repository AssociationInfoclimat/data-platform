"""CLI de construction/mise à jour de l'index code (incrémental par sha256).

Usage :
  python -m code_index.index [--manifest F] [--base-dir D] [--repo R ...]
                             [--dry-run] [--limit N]

Ne ré-embedde que les fichiers dont le contenu a changé ; retire de l'index ceux
disparus du disque (dans le périmètre des repos parcourus). `--dry-run` estime volume
et coût sans appeler l'API.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from . import context, embed, store, walk
from .chunk import chunk_text
from .config import EMBED_VERSION, Config, load_config, load_manifest

PRICE_PER_MTOK = 0.15  # codestral-embed-2505, $ / million de tokens


@dataclass
class FileBlob:
    src: walk.SourceFile
    sha: str
    text: str


def _read(src: walk.SourceFile) -> FileBlob | None:
    try:
        data = src.abspath.read_bytes()
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        return None  # fichier vide/blanc : 0 chunk, inutile de l'indexer ou de le suivre
    sha = hashlib.sha256(data).hexdigest()
    return FileBlob(src=src, sha=sha, text=text)


def _build_rows(blob: FileBlob, cfg: Config, client: object | None,
                throttle: embed.Throttle) -> tuple[list[dict], list[str]]:
    """Lignes (sans vecteur) + textes contextualisés à embedder, pour un fichier.

    `text` reste le chunk **brut** (affichage, n° de ligne exacts) ; `contextualized`
    (= contexte préfixé) est ce qui est embeddé et indexé en BM25. Sans `client`
    (dry-run), le mode `llm` retombe sur le contexte structurel pour estimer sans API.
    """
    chunks = chunk_text(blob.text, cfg.chunk_chars, cfg.overlap_chars)
    mode = cfg.context_mode
    if client is None and mode == "llm":
        mode = "struct"  # proxy déterministe pour le dry-run (pas d'appel API)
    ctxs = context.contexts_for_file(
        client, blob.src.repo, blob.src.path, blob.src.lang, blob.text, chunks,
        mode=mode, model=cfg.context_model, throttle=throttle,
        max_retries=cfg.max_retries, max_file_chars=cfg.max_context_file_chars)
    rows: list[dict] = []
    texts: list[str] = []
    for idx, (ch, ctx) in enumerate(zip(chunks, ctxs)):
        ctext = context.apply_context(ctx, ch.text)
        rows.append({
            "id": f"{blob.src.key}#{idx}",
            "key": blob.src.key,
            "repo": blob.src.repo,
            "path": blob.src.path,
            "lang": blob.src.lang,
            "start_line": ch.start_line,
            "end_line": ch.end_line,
            "sha": blob.sha,
            "text": ch.text,
            "context": ctx,
            "contextualized": ctext,
            "embed_ver": EMBED_VERSION,
        })
        texts.append(ctext)
    return rows, texts


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Indexe le code Infoclimat (embeddings Mistral).")
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--base-dir", type=Path, default=None)
    ap.add_argument("--repo", action="append", dest="repos", default=None,
                    help="Limiter à ce(s) repo(s) (répétable).")
    ap.add_argument("--dry-run", action="store_true", help="Estimer sans appeler l'API.")
    ap.add_argument("--limit", type=int, default=None, help="Plafonner le nb de fichiers (debug).")
    args = ap.parse_args(argv)

    cfg = load_config()
    base_dir = args.base_dir or cfg.base_dir
    manifest = load_manifest(args.manifest)

    files = list(walk.iter_files(manifest, base_dir, repos=args.repos,
                                 max_file_bytes=cfg.max_file_bytes))
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"Aucun fichier trouvé sous {base_dir} (repos={args.repos or 'tous'}).",
              file=sys.stderr)
        return 1

    blobs = [b for b in (_read(f) for f in files) if b is not None]
    walked_keys = {b.src.key for b in blobs}
    walked_repos = {b.src.repo for b in blobs}

    if args.dry_run:
        rows_all: list[dict] = []
        dry_throttle = embed.Throttle(0.0)
        for b in blobs:
            rows, _ = _build_rows(b, cfg, None, dry_throttle)
            rows_all.extend(rows)
        chars = sum(len(r["contextualized"]) for r in rows_all)
        toks = chars / 4
        ctx_note = ""
        if cfg.context_mode == "llm":
            ctx_note = (f" + ~{len(blobs)} appels contexte LLM ({cfg.context_model}, "
                        f"1/fichier) ; chunks estimés au contexte structurel")
        print(f"[dry-run] {len(blobs)} fichiers, {len(rows_all)} chunks, "
              f"~{toks/1e6:.2f} M tokens d'embedding estimés, coût ~"
              f"${toks/1e6*PRICE_PER_MTOK:.2f}{ctx_note} "
              f"(plein index, sans tenir compte de l'existant).")
        return 0

    db = store.connect(cfg.db_dir)
    indexed = store.indexed_shas(db)
    vers = store.indexed_vers(db)

    def _needs_reindex(b: FileBlob) -> bool:
        # Contenu modifié OU stratégie d'indexation (contexte/embedding) périmée.
        return indexed.get(b.src.key) != b.sha or vers.get(b.src.key) != EMBED_VERSION

    to_index = [b for b in blobs if _needs_reindex(b)]
    gone = [k for k in indexed
            if k.split("/", 1)[0] in walked_repos and k not in walked_keys]
    refresh = [b.src.key for b in to_index if b.src.key in indexed]

    if not to_index and not gone:
        print(f"Index à jour : {len(blobs)} fichiers, rien à (ré)indexer.")
        return 0

    store.delete_keys(db, sorted(set(refresh) | set(gone)))

    total_rows = 0
    if to_index:
        if not cfg.api_key:
            print("MISTRAL_API_KEY manquante : impossible d'embedder.", file=sys.stderr)
            return 2
        client = embed.make_client(cfg.api_key)
        throttle = embed.Throttle(cfg.min_interval_s)
        # Même client pour le contexte (chat) et l'embedding ; None si pas de contexte LLM.
        ctx_client = client if cfg.context_mode == "llm" else None

        def _rows_for(batch_files: list[FileBlob]) -> tuple[list[dict], list[str]]:
            """(lignes, textes contextualisés) pour un lot de fichiers. La génération de
            contexte est I/O-bound (un appel réseau/fichier) : on la parallélise. Le Throttle
            partagé (à verrou) borne le débit global. `concurrency=1` ⇒ séquentiel."""
            if cfg.concurrency > 1 and ctx_client is not None and len(batch_files) > 1:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=cfg.concurrency) as ex:
                    parts = list(ex.map(
                        lambda b: _build_rows(b, cfg, ctx_client, throttle), batch_files))
            else:
                parts = [_build_rows(b, cfg, ctx_client, throttle) for b in batch_files]
            rows: list[dict] = []
            texts: list[str] = []
            for r, t in parts:
                rows.extend(r)
                texts.extend(t)
            return rows, texts

        # Traitement par LOTS DE FICHIERS, persistés au fur et à mesure : l'index étant
        # incrémental par sha, un échec (API, etc.) ne perd que le lot courant et un simple
        # relancement REPREND là où ça s'est arrêté (les fichiers déjà écrits sont sautés).
        # Borne aussi la mémoire (on ne garde pas 50k vecteurs en RAM).
        BATCH_FILES = 200
        for fstart in range(0, len(to_index), BATCH_FILES):
            fbatch = to_index[fstart:fstart + BATCH_FILES]
            rows_b, texts_b = _rows_for(fbatch)
            if rows_b:
                vectors = embed.embed_texts(
                    client, texts_b, model=cfg.model, dim=cfg.dim, batch_size=cfg.batch_size,
                    max_batch_chars=cfg.max_batch_chars, max_input_chars=cfg.max_input_chars,
                    throttle=throttle, max_retries=cfg.max_retries)
                for row, vec in zip(rows_b, vectors):
                    row["vector"] = vec
                for s in range(0, len(rows_b), 1000):
                    store.add_rows(db, rows_b[s:s + 1000])
                total_rows += len(rows_b)
            print(f"  {min(fstart + BATCH_FILES, len(to_index))}/{len(to_index)} fichiers "
                  f"indexés, {total_rows} chunks écrits…", flush=True, file=sys.stderr)
        if cfg.hybrid:
            # Compacte en mono-fragment PUIS construit le BM25 : le builder FTS natif de
            # LanceDB deadlock sur une table multi-fragment (cf. store.rebuild_with_fts).
            print("  compaction + index FTS BM25…", flush=True, file=sys.stderr)
            store.rebuild_with_fts(db)

    print(f"Indexé : {len(to_index)} fichiers (ré)indexés, {total_rows} chunks, "
          f"{len(gone)} fichiers retirés.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
