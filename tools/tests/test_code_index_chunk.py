"""Tests du découpage en fenêtres (code_index.chunk)."""
from __future__ import annotations

import pytest

from code_index.chunk import chunk_structured, chunk_text


def test_empty_text_yields_nothing() -> None:
    assert chunk_text("") == []


# ── chunk_structured (corpus docs) ──

def test_structured_yaml_registry_one_chunk_per_entry() -> None:
    pytest.importorskip("yaml")
    text = ("version: 1\n"
            "tables:\n"
            "  - name: foudre\n    status: actif\n    note: impacts\n"
            "  - name: connectes\n    status: mort\n")
    chunks = chunk_structured("inventory/tables.yaml", text)
    assert len(chunks) == 2
    assert chunks[0].text.startswith("# inventory/tables.yaml | tables: foudre")
    assert "name: foudre" in chunks[0].text and "name: connectes" in chunks[1].text
    # lignes réelles : la 1re entrée commence ligne 3
    assert chunks[0].start_line == 3


def test_structured_contract_is_single_doc() -> None:
    pytest.importorskip("yaml")
    # Un contrat ODCS contient des listes (servers) mais NE doit PAS être éclaté par elles.
    text = ("apiVersion: v3.0.2\nkind: DataContract\n"
            "servers:\n  - server: a\n  - server: b\n")
    chunks = chunk_structured("contracts/x.odcs.yaml", text)
    assert len(chunks) == 1
    assert chunks[0].text.startswith("# contracts/x.odcs.yaml")
    assert "server: a" in chunks[0].text and "server: b" in chunks[0].text


def test_structured_markdown_by_section() -> None:
    text = "# Titre\nintro\n\n## A\nbla\n\n## B\nblo\n"
    chunks = chunk_structured("catalog/glossary.md", text)
    assert len(chunks) == 3  # préambule+titre / A / B
    assert any("## A" in c.text for c in chunks) and any("## B" in c.text for c in chunks)


def test_small_file_is_single_chunk() -> None:
    text = "line1\nline2\nline3\n"
    chunks = chunk_text(text, max_chars=3000, overlap_chars=1000)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 3
    assert chunks[0].text == text


def test_windows_have_overlap_and_cover_all_lines() -> None:
    lines = [f"line{i:03d}\n" for i in range(1, 101)]  # 100 lignes de 8 caractères
    text = "".join(lines)
    chunks = chunk_text(text, max_chars=80, overlap_chars=24)  # ~10 lignes, recouvre 3

    assert len(chunks) > 1
    # Couverture : la 1re commence à 1, la dernière finit à 100, sans trou.
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 100
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start_line <= prev.end_line + 1          # pas de trou
        assert nxt.start_line <= prev.end_line              # recouvrement effectif
        assert nxt.start_line > prev.start_line             # progression


def test_determinism() -> None:
    text = "".join(f"x{i}\n" for i in range(200))
    assert chunk_text(text, 100, 30) == chunk_text(text, 100, 30)


def test_oversized_line_is_split_under_max() -> None:
    text = "short\n" + "z" * 5000 + "\n"
    chunks = chunk_text(text, max_chars=1000, overlap_chars=200)
    # Aucune fenêtre ne dépasse max_chars (garantie anti-dépassement de tokens API).
    assert all(len(c.text) <= 1000 for c in chunks)
    # La ligne longue (n°2) est bien couverte par plusieurs morceaux.
    assert sum(1 for c in chunks if c.start_line == 2) >= 5
    assert all(c.end_line >= c.start_line for c in chunks)


def test_no_chunk_exceeds_max_chars() -> None:
    text = "".join(f"col{i},val{i};" for i in range(2000)) + "\n"   # une seule ligne dense
    chunks = chunk_text(text, max_chars=3000, overlap_chars=1000)
    assert chunks and all(len(c.text) <= 3000 for c in chunks)
