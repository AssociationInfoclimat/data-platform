"""Découpage d'un fichier en fenêtres pour l'embedding.

Fenêtres respectant les frontières de ligne : ~`max_chars` caractères avec un
recouvrement d'~`overlap_chars` (Mistral recommande 3000 / 1000 pour codestral-embed).
Découpe agnostique au langage (pas d'AST) — KISS ; l'AST par fonction est une
amélioration future. Pur stdlib (testable en CI).
"""
from __future__ import annotations

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
