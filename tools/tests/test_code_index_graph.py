"""Tests du graphe d'appels (code_index.graph) : extraction, construction, code_impact."""
from __future__ import annotations

import pytest

from code_index import graph
from code_index.walk import SourceFile


def _sf(repo: str, path: str, lang: str) -> SourceFile:
    from pathlib import Path
    return SourceFile(repo=repo, path=path, abspath=Path("/dev/null"), lang=lang)


# ── Extraction (nécessite tree-sitter) ─────────────────────────────────────────

PY_SRC = (
    "import os\n\n"
    "def alpha(a):\n"
    "    return beta(a)\n\n"
    "def beta(a):\n"
    "    return os.path.join(a)\n\n"
    "class Gamma:\n"
    "    def m(self):\n"
    "        return self.helper() + alpha(1)\n"
    "    def helper(self):\n"
    "        return 0\n"
)


def test_extract_python_defs_and_calls() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    defs, calls = graph.extract_file("python", PY_SRC)
    qnames = {d["qname"] for d in defs}
    assert {"alpha", "beta", "Gamma", "Gamma.m", "Gamma.helper"} <= qnames
    # alpha appelle beta ; Gamma.m appelle helper (membre) et alpha
    pairs = {(c["caller"], c["callee"]) for c in calls}
    assert ("alpha", "beta") in pairs
    assert ("Gamma.m", "helper") in pairs        # self.helper() → leaf 'helper'
    assert ("Gamma.m", "alpha") in pairs
    assert ("beta", "join") in pairs             # os.path.join → leaf 'join'


def test_extract_php_member_and_free_calls() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    php = ("<?php\n"
           "function alpha($a) { return beta($a); }\n"
           "class Gamma {\n"
           "  public function m() { return $this->helper() + alpha(1); }\n"
           "  public function helper() { return 0; }\n"
           "}\n")
    defs, calls = graph.extract_file("php", php)
    qnames = {d["qname"] for d in defs}
    assert {"alpha", "Gamma", "Gamma.m", "Gamma.helper"} <= qnames
    pairs = {(c["caller"], c["callee"]) for c in calls}
    assert ("alpha", "beta") in pairs
    assert ("Gamma.m", "helper") in pairs        # $this->helper()
    assert ("Gamma.m", "alpha") in pairs


def test_extract_unsupported_lang_is_empty() -> None:
    # Langage non outillé → aucune extraction, jamais d'exception.
    assert graph.extract_file("ncl", "a = 1\n") == ([], [])
    assert graph.extract_file("python", "") == ([], [])


# ── Construction du graphe ──────────────────────────────────────────────────────

def test_build_graph_resolves_internal_calls() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = graph.build_graph([(_sf("r", "mod.py", "python"), PY_SRC)])
    assert g["version"] == graph.GRAPH_VERSION
    # beta est défini → il a un nœud, et alpha→beta est une arête
    beta_ids = g["by_name"]["beta"]
    assert len(beta_ids) == 1
    alpha_id = g["by_name"]["alpha"][0]
    assert beta_ids[0] in g["out"][alpha_id]
    # join (os.path.join) n'est PAS défini en interne → pas de nœud, pas d'arête
    assert "join" not in g["by_name"]


def test_build_graph_prunes_ambiguous_names() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    # 'run' défini dans 3 fichiers, appelé par caller ; fanout=2 → élagué (>2 homonymes)
    files = []
    for i in range(3):
        files.append((_sf("r", f"w{i}.py", "python"), f"def run():\n    return {i}\n"))
    files.append((_sf("r", "main.py", "python"), "def go():\n    return run()\n"))
    g = graph.build_graph(files, max_name_fanout=2)
    go_id = g["by_name"]["go"][0]
    assert go_id not in g["out"]            # 'run' a 3 défs > 2 → aucune arête créée
    g2 = graph.build_graph(files, max_name_fanout=5)
    assert len(g2["out"][g2["by_name"]["go"][0]]) == 3   # 5 ≥ 3 → reliées


def test_build_graph_prunes_ubiquitous_call_names() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    # 'push' défini une seule fois (méthode user) mais appelé partout (primitive .push()) :
    # au-delà de max_call_freq, aucune arête ne pointe vers lui (anti-collision builtin).
    files = [(_sf("r", "lib.py", "python"), "class S:\n    def push(self):\n        return 1\n")]
    callers = "\n".join(f"def c{i}():\n    x.push()\n" for i in range(5))
    files.append((_sf("r", "many.py", "python"), callers))
    g = graph.build_graph(files, max_call_freq=3)         # 5 appels > 3 → 'push' bloqué
    push_id = g["by_name"]["push"][0]
    loaded = {**g, "in": graph._reverse(g["out"])}
    assert push_id not in loaded["in"]                    # aucun caller relié
    g2 = graph.build_graph(files, max_call_freq=10)        # 5 ≤ 10 → reliés
    assert graph._reverse(g2["out"]).get(push_id)


def test_is_minified_detection() -> None:
    assert graph._is_minified("web/js/app.min.js", "x")
    assert graph._is_minified("vendor/lib/foo.js", "x")
    assert graph._is_minified("a.js", "var x=1;" + "a" * 3000)   # ligne géante
    assert not graph._is_minified("src/app.js", "const x = 1\nconst y = 2\n")


# ── code_impact (BFS) ───────────────────────────────────────────────────────────

def _chain_graph():
    """a → b → c (a appelle b, b appelle c), en python."""
    src = ("def c():\n    return 1\n\n"
           "def b():\n    return c()\n\n"
           "def a():\n    return b()\n")
    return graph.build_graph([(_sf("r", "chain.py", "python"), src)])


def test_code_impact_callers_blast_radius() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    # qui casse si on change c ? → b (prof 1) puis a (prof 2)
    res = graph.code_impact(g, "c", direction="callers", depth=2)
    names = {(n["qname"], n["depth"]) for n in res["impacted"]}
    assert ("b", 1) in names and ("a", 2) in names
    # profondeur 1 : seulement b
    res1 = graph.code_impact(g, "c", direction="callers", depth=1)
    assert {n["qname"] for n in res1["impacted"]} == {"b"}


def test_code_impact_callees_dependencies() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    # de quoi dépend a ? → b puis c
    res = graph.code_impact(g, "a", direction="callees", depth=2)
    assert {n["qname"] for n in res["impacted"]} == {"b", "c"}


def test_code_impact_unknown_symbol() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.code_impact(g, "inexistant", direction="callers")
    assert res["roots"] == [] and res["impacted"] == []


def test_load_graph_roundtrip_and_reverse(tmp_path) -> None:
    pytest.importorskip("tree_sitter_language_pack")
    import json
    g = _chain_graph()
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(g), encoding="utf-8")
    loaded = graph.load_graph(p)
    assert "in" in loaded                                   # index inverse calculé
    res = graph.code_impact(loaded, "c", direction="callers", depth=2)
    assert {n["qname"] for n in res["impacted"]} == {"a", "b"}


def test_load_graph_gzip(tmp_path) -> None:
    pytest.importorskip("tree_sitter_language_pack")
    import gzip
    import json
    g = _chain_graph()
    p = tmp_path / "graph.json.gz"
    p.write_bytes(gzip.compress(json.dumps(g).encode("utf-8")))
    loaded = graph.load_graph(p)
    assert loaded["nodes"] == g["nodes"]
