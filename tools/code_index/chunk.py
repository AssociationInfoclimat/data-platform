"""Découpage d'un fichier en fenêtres pour l'embedding.

Fenêtres respectant les frontières de ligne : ~`max_chars` caractères avec un
recouvrement d'~`overlap_chars` (Mistral recommande 3000 / 1000 pour codestral-embed).
Découpe agnostique au langage (pas d'AST) — KISS ; l'AST par fonction est une
amélioration future. Pur stdlib (testable en CI).

`chunk_structured` (corpus docs) découpe au contraire **par entrée** : une entrée de
registre YAML (table/pipeline/…), un contrat ODCS, une section Markdown = un chunk —
plus naturel pour de la gouvernance que des fenêtres de caractères.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    start_line: int   # 1-based, inclus
    end_line: int     # 1-based, inclus
    text: str


def _segments(text: str, max_chars: int) -> list[tuple[int, str]]:
    """Lignes (avec n° 1-based) ; toute ligne plus longue que `max_chars` est
    re-coupée en morceaux ≤ `max_chars` (garantit qu'aucun chunk ne dépasse la limite
    de tokens de l'API — une ligne minifiée/dense ne peut pas exploser un chunk)."""
    segs: list[tuple[int, str]] = []
    for ln, line in enumerate(text.splitlines(keepends=True), 1):
        if len(line) <= max_chars:
            segs.append((ln, line))
        else:
            for start in range(0, len(line), max_chars):
                segs.append((ln, line[start:start + max_chars]))
    return segs


def chunk_text(text: str, max_chars: int = 3000, overlap_chars: int = 1000) -> list[Chunk]:
    """Découpe `text` en fenêtres de ≤ `max_chars` caractères alignées sur les lignes.

    Chaque fenêtre redémarre `overlap_chars` caractères avant la fin de la précédente.
    Progression garantie (au moins un segment par pas).
    """
    if not text:
        return []
    segs = _segments(text, max_chars)
    n = len(segs)
    chunks: list[Chunk] = []
    i = 0
    while i < n:
        size = 0
        j = i
        while j < n and (j == i or size + len(segs[j][1]) <= max_chars):
            size += len(segs[j][1])
            j += 1
        chunks.append(Chunk(start_line=segs[i][0], end_line=segs[j - 1][0],
                            text="".join(s[1] for s in segs[i:j])))
        if j >= n:
            break
        # Recule pour le recouvrement, sans jamais rester sur place.
        ov = 0
        k = j
        while k > i + 1 and ov + len(segs[k - 1][1]) <= overlap_chars:
            ov += len(segs[k - 1][1])
            k -= 1
        i = max(k, i + 1)
    return chunks


# ── Découpe « par entrée » pour le corpus docs (gouvernance) ──────────────────

_MD_HEADING = re.compile(r"^#{1,4}\s")
_YAML_ITEM = re.compile(r"^(\s*)-\s")


def _entry_label(item: dict) -> str:
    for k in ("id", "name", "table", "dataset", "pipeline"):
        v = item.get(k)
        if v:
            return str(v)
    return next((str(v) for v in item.values() if isinstance(v, (str, int))), "?")


def _md_sections(text: str, max_chars: int) -> list[Chunk]:
    """1 chunk par section Markdown (titre `#`..`####`). Repli char-window si trop long."""
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if _MD_HEADING.match(ln)]
    if not starts:
        return chunk_text(text, max_chars, 0)
    if starts[0] != 0:
        starts = [0] + starts          # préambule avant le 1er titre
    bounds = starts + [len(lines)]
    out: list[Chunk] = []
    for a, b in zip(bounds, bounds[1:]):
        body = "\n".join(lines[a:b]).strip("\n")
        if not body.strip():
            continue
        if len(body) > max_chars:
            for c in chunk_text(body, max_chars, 0):
                out.append(Chunk(a + c.start_line, a + c.end_line, c.text))
        else:
            out.append(Chunk(a + 1, b, body))
    return out


def _yaml_items(text: str, header_for, max_chars: int) -> list[Chunk] | None:
    """Si le YAML est un dict avec une LISTE d'entrées sous une clé (registre inventory),
    renvoie 1 chunk par entrée (en-tête + bloc brut, lignes réelles). Sinon None."""
    import yaml
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    list_key = next((k for k, v in data.items()
                     if isinstance(v, list) and v and all(isinstance(e, dict) for e in v)), None)
    if list_key is None:
        return None
    items = data[list_key]
    lines = text.split("\n")
    key_ln = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(list_key)}\s*:", ln)), None)
    if key_ln is None:
        return None
    # Indentation des items = celle du 1er `- ` après la clé.
    starts = []
    indent = None
    for i in range(key_ln + 1, len(lines)):
        m = _YAML_ITEM.match(lines[i])
        if m and indent is None:
            indent = len(m.group(1))
        if m and len(m.group(1)) == indent:
            starts.append(i)
    if not starts:
        return None
    bounds = starts + [len(lines)]
    out: list[Chunk] = []
    for idx, (a, b) in enumerate(zip(bounds, bounds[1:])):
        if idx >= len(items):
            break
        block = "\n".join(lines[a:b]).rstrip("\n")
        label = _entry_label(items[idx])
        body = f"{header_for(list_key, label)}\n{block}"
        if len(body) > max_chars:
            for c in chunk_text(body, max_chars, 0):
                out.append(Chunk(a + c.start_line, a + c.end_line, c.text))
        else:
            out.append(Chunk(a + 1, b, body))
    return out


def chunk_structured(rel_path: str, text: str, max_chars: int = 8000) -> list[Chunk]:
    """Découpe « par entrée » du corpus docs : registre YAML → 1 chunk/entrée ; Markdown →
    1 chunk/section ; sinon (contrat ODCS, doc unique) → fichier entier (repli char-window si
    > max_chars). Chaque chunk d'entrée porte un en-tête `# <fichier> | <clé>: <label>` qui
    sert de contexte (le contexte LLM par chunk est désactivé pour les docs)."""
    if not text.strip():
        return []
    if rel_path.endswith(".md"):
        return _md_sections(text, max_chars)
    # Per-entrée UNIQUEMENT pour les registres inventory (listes table/pipeline/source/…).
    # Les contrats ODCS sont des docs uniques qui CONTIENNENT des listes (servers/schema/…) :
    # à NE PAS découper par ces sous-listes → traités comme doc unique ci-dessous.
    if rel_path.startswith("inventory/") and rel_path.endswith((".yaml", ".yml")):
        def _hdr(key, label):
            return f"# {rel_path} | {key}: {label}"
        items = _yaml_items(text, _hdr, max_chars)
        if items is not None:
            return items
    # Doc unique (contrat ODCS, catalog, audits…) : 1 chunk, en-tête fichier, repli si trop gros.
    head = f"# {rel_path}\n"
    if len(head) + len(text) <= max_chars:
        return [Chunk(1, len(text.split("\n")), head + text.rstrip("\n"))]
    return chunk_text(text, max_chars, 0)
