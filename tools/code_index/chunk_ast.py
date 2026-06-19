"""Découpe du code aux frontières sémantiques (fonction/classe) via tree-sitter.

Remplace les fenêtres de caractères (`chunk.chunk_text`) pour les langages outillés
(PHP/Python/TS/JS) : un chunk = une définition top-level (fonction, classe, interface…),
commentaires/décorateurs attenants inclus. Le code « entre » les définitions (imports,
procédural) est regroupé en chunks « glue ». Repli char-window pour : langage non outillé,
échec de parsing, ou nœud plus gros que `max_chars`. Interface `Chunk` identique → le reste
du pipeline (URL/lignes, embed, store) est inchangé.

`tree_sitter_language_pack` est importé PARESSEUSEMENT : sans lui (CI/tests stdlib), tout
retombe sur le char-window — rien ne casse.
"""
from __future__ import annotations

from . import tsutil
from .chunk import Chunk, chunk_text

# Étiquette de langage (walk.LANG_BY_EXT) → nom tree-sitter.
_TS_LANG = {"php": "php", "python": "python", "ts": "typescript", "js": "javascript"}

# Types de nœuds « définition top-level » à isoler, par langage.
_DEF_TYPES = {
    "python": {"function_definition", "class_definition", "decorated_definition"},
    "php": {"function_definition", "class_declaration", "interface_declaration",
            "trait_declaration", "enum_declaration"},
    "typescript": {"function_declaration", "class_declaration", "interface_declaration",
                   "enum_declaration", "abstract_class_declaration", "method_definition",
                   "lexical_declaration", "export_statement"},
    "javascript": {"function_declaration", "class_declaration", "method_definition",
                   "lexical_declaration", "export_statement"},
}

_COMMENT_PREFIXES = ("#", "//", "/*", "*", "*/")

# Accès tree-sitter agnostique au binding : factorisé dans `tsutil` (partagé avec `graph`).
_get_parser = tsutil.get_parser
_root = tsutil.root
_kind = tsutil.kind
_start_row = tsutil.start_row
_end_row = tsutil.end_row
_named_children = tsutil.named_children
_parse = tsutil.parse


def _emit_window(lines: list[str], a: int, b: int, max_chars: int, out: list[Chunk]) -> None:
    """Émet les lignes [a, b) (0-based) en 1+ chunks, char-window si trop gros. Ignore le vide."""
    body = "\n".join(lines[a:b]).strip("\n")
    if not body.strip():
        return
    if len(body) <= max_chars:
        out.append(Chunk(a + 1, b, body))
        return
    for c in chunk_text(body, max_chars, 0):   # offset local → lignes absolues
        out.append(Chunk(a + c.start_line, a + c.end_line, c.text))


def _absorb_comments(lines: list[str], def_start: int, floor: int) -> int:
    """Recule depuis `def_start` pour inclure les lignes de commentaire/blanc attenantes
    (sans descendre sous `floor` = fin du chunk précédent)."""
    s = def_start
    while s > floor:
        stripped = lines[s - 1].strip()
        if stripped == "" or stripped.startswith(_COMMENT_PREFIXES):
            s -= 1
        else:
            break
    return s


def chunk_code(text: str, lang: str, max_chars: int = 3000) -> list[Chunk]:
    """Découpe `text` (langage `lang`, étiquette walk) par définitions top-level via
    tree-sitter ; repli char-window si langage non outillé / parsing impossible."""
    if not text.strip():
        return []
    ts_lang = _TS_LANG.get(lang)
    parser = _get_parser(ts_lang) if ts_lang else None
    fallback_overlap = max(0, max_chars // 3)
    if parser is None:
        return chunk_text(text, max_chars, fallback_overlap)
    try:
        tree = _parse(parser, text)
        root = _root(tree)
    except Exception:  # noqa: BLE001
        return chunk_text(text, max_chars, fallback_overlap)

    def_types = _DEF_TYPES.get(ts_lang, set())
    lines = text.split("\n")
    # Définitions top-level (enfants directs de la racine), triées par ligne.
    defs = sorted(
        ((_start_row(n), _end_row(n)) for n in _named_children(root)
         if _kind(n) in def_types),
        key=lambda p: p[0])
    if not defs:
        return chunk_text(text, max_chars, fallback_overlap)         # procédural : fenêtres

    out: list[Chunk] = []
    cursor = 0  # 1re ligne non encore émise (0-based)
    for start_row, end_row in defs:
        if start_row < cursor:        # nœud chevauchant déjà émis (sécurité)
            continue
        cstart = _absorb_comments(lines, start_row, cursor)
        if cstart > cursor:           # « glue » avant la définition (imports, procédural)
            _emit_window(lines, cursor, cstart, max_chars, out)
        _emit_window(lines, cstart, end_row + 1, max_chars, out)  # la définition (split si géante)
        cursor = end_row + 1
    if cursor < len(lines):           # queue de fichier
        _emit_window(lines, cursor, len(lines), max_chars, out)
    return out
