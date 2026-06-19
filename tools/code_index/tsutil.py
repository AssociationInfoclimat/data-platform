"""Accès tree-sitter agnostique au binding (partagé par le chunking AST et le graphe).

Les bindings tree-sitter divergent : py-tree-sitter expose ``node.type`` /
``node.start_point`` / ``node.named_children`` / ``tree.root_node`` (propriété) ;
d'autres (ex. language-pack 1.9) exposent ``node.kind`` / ``node.start_position`` /
``node.named_child(i)`` / ``tree.root_node()`` (méthode), avec des points tantôt
tuples ``(row, col)`` tantôt objets ``Point(.row)``. On lisse les deux pour rester
portable, et on importe la lib PARESSEUSEMENT : sans elle (CI/tests stdlib), tout
appelant retombe sur son propre repli — rien ne casse.
"""
from __future__ import annotations


def get_parser(ts_lang: str):
    """Parser tree-sitter pour `ts_lang`, ou None si la lib/grammaire est absente."""
    try:
        from tree_sitter_language_pack import get_parser as _gp
        return _gp(ts_lang)
    except Exception:  # noqa: BLE001 — lib absente, grammaire inconnue, etc.
        return None


def v(obj, name):
    """Attribut `name`, appelé s'il s'agit d'une méthode (les bindings exposent tantôt
    des propriétés, tantôt des méthodes pour les mêmes infos)."""
    a = getattr(obj, name, None)
    return a() if callable(a) else a


def root(tree):
    return v(tree, "root_node")


def kind(node) -> str:
    return v(node, "type") or v(node, "kind")


def _row(pt) -> int:
    """Ligne 0-based d'un point tree-sitter : tuple (row, col) ou objet Point(.row)."""
    return pt.row if hasattr(pt, "row") else pt[0]


def start_row(node) -> int:
    return _row(v(node, "start_point") or v(node, "start_position"))


def end_row(node) -> int:
    return _row(v(node, "end_point") or v(node, "end_position"))


def named_children(node) -> list:
    kids = v(node, "named_children")
    if kids is not None:
        return list(kids)
    cnt = v(node, "named_child_count") or 0
    return [node.named_child(i) for i in range(cnt)]


def child_by_field(node, field: str):
    """Enfant nommé via son champ de grammaire (ex. `name`), ou None.

    py-tree-sitter : ``child_by_field_name(field)`` ; language-pack 1.9 idem. On lisse
    aussi l'éventuel accès par propriété (rare)."""
    fn = getattr(node, "child_by_field_name", None)
    if callable(fn):
        try:
            return fn(field)
        except Exception:  # noqa: BLE001
            return None
    return None


def node_text(node, src_bytes: bytes) -> str:
    """Texte source d'un nœud. Utilise ``node.text`` si présent, sinon découpe les octets
    via ``start_byte``/``end_byte`` (lissés) — décodage tolérant."""
    t = getattr(node, "text", None)
    if isinstance(t, (bytes, bytearray)):
        return bytes(t).decode("utf-8", errors="replace")
    if isinstance(t, str):
        return t
    a = v(node, "start_byte")
    b = v(node, "end_byte")
    if a is None or b is None:
        return ""
    return src_bytes[a:b].decode("utf-8", errors="replace")


def parse(parser, text: str):
    """parse(bytes) (py-tree-sitter) ou parse(str) (language-pack 1.9) — on tente les deux."""
    try:
        return parser.parse(text.encode("utf-8", errors="replace"))
    except TypeError:
        return parser.parse(text)
