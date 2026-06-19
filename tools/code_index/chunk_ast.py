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


def _get_parser(ts_lang: str):
    """Parser tree-sitter ou None si la lib/grammaire est absente (→ repli char-window)."""
    try:
        from tree_sitter_language_pack import get_parser
        return get_parser(ts_lang)
    except Exception:  # noqa: BLE001 — lib absente, grammaire inconnue, etc.
        return None


# ── Accès NŒUD/ARBRE agnostique au binding ───────────────────────────────────
# Les bindings tree-sitter divergent : py-tree-sitter expose node.type /
# node.start_point / node.named_children / tree.root_node (propriété) ; d'autres
# (ex. language-pack 1.9) exposent node.kind / node.start_position / node.named_child(i)
# / tree.root_node() (méthode). On lisse les deux pour rester portable.

def _v(obj, name):
    """Attribut `name`, appelé s'il s'agit d'une méthode (les bindings exposent tantôt des
    propriétés, tantôt des méthodes pour les mêmes infos)."""
    a = getattr(obj, name, None)
    return a() if callable(a) else a


def _root(tree):
    return _v(tree, "root_node")


def _kind(node) -> str:
    return _v(node, "type") or _v(node, "kind")


def _row(pt) -> int:
    """Ligne 0-based d'un point tree-sitter : tuple (row, col) ou objet Point(.row)."""
    return pt.row if hasattr(pt, "row") else pt[0]


def _start_row(node) -> int:
    return _row(_v(node, "start_point") or _v(node, "start_position"))


def _end_row(node) -> int:
    return _row(_v(node, "end_point") or _v(node, "end_position"))


def _named_children(node) -> list:
    kids = _v(node, "named_children")
    if kids is not None:
        return list(kids)
    cnt = _v(node, "named_child_count") or 0
    return [node.named_child(i) for i in range(cnt)]


def _parse(parser, text: str):
    """parse(bytes) (py-tree-sitter) ou parse(str) (language-pack 1.9) — on tente les deux."""
    try:
        return parser.parse(text.encode("utf-8", errors="replace"))
    except TypeError:
        return parser.parse(text)


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
