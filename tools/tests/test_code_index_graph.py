"""Tests du graphe d'appels v2 (code_index.graph) : extraction riche, cascade de
résolution à confiance, code_impact (tiers/sous-système)."""
from __future__ import annotations

from pathlib import Path

import pytest

from code_index import graph
from code_index.walk import SourceFile


def _sf(repo: str, path: str, lang: str) -> SourceFile:
    return SourceFile(repo=repo, path=path, abspath=Path("/dev/null"), lang=lang)


def _edges(g, src_id):
    """{tid: conf} des arêtes sortantes d'un nœud."""
    return {t: c for t, c in g["out"].get(src_id, [])}


# ── Extraction ──────────────────────────────────────────────────────────────────

PY_SRC = (
    "import os\n\n"
    "def alpha(a):\n    return beta(a)\n\n"
    "def beta(a):\n    return os.path.join(a)\n\n"
    "class Gamma:\n"
    "    def m(self):\n        return self.helper() + alpha(1)\n"
    "    def helper(self):\n        return 0\n"
)


def test_extract_python_defs_and_calls() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    info = graph.extract_file("python", PY_SRC, "mod.py")
    qnames = {d["qname"] for d in info["defs"]}
    assert {"alpha", "beta", "Gamma", "Gamma.m", "Gamma.helper"} <= qnames
    triples = {(c["caller"], c["callee"], c["rkind"]) for c in info["calls"]}
    assert ("alpha", "beta", "free") in triples
    assert ("Gamma.m", "helper", "this") in triples       # self.helper() → receveur this
    assert ("Gamma.m", "alpha", "free") in triples


def test_extract_php_receivers() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    php = ("<?php\nnamespace App;\nuse App\\Util\\Geo;\n"
           "class Svc extends Base {\n"
           "  function m() { $this->h(); self::s(); parent::b(); Geo::load(); new Geo(); }\n"
           "  function h() {}\n}\n")
    info = graph.extract_file("php", php, "Svc.php")
    assert info["ns"] == "App"
    assert info["imports"].get("Geo", {}).get("fqn") == "App\\Util\\Geo"
    svc = next(d for d in info["defs"] if d["qname"] == "Svc")
    assert "Base" in svc["bases"]
    kinds = {(c["callee"], c["rkind"], c["rclass"]) for c in info["calls"]}
    assert ("h", "this", "") in kinds
    assert ("s", "self", "") in kinds
    assert ("b", "parent", "") in kinds
    assert ("load", "static", "Geo") in kinds
    assert ("__construct", "new", "Geo") in kinds


def test_extract_unsupported_lang_is_empty() -> None:
    assert graph.extract_file("ncl", "a = 1\n") == {"ns": "", "imports": {}, "defs": [], "calls": []}
    assert graph.extract_file("python", "")["defs"] == []


# ── Cascade de résolution ─────────────────────────────────────────────────────────

def test_resolve_this_and_parent_via_hierarchy() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    php = ("<?php\nnamespace App;\n"
           "class Base { function shared() { return 1; } }\n"
           "class Svc extends Base {\n"
           "  function run() { return $this->shared() + $this->own(); }\n"
           "  function own() { return 2; }\n}\n")
    g = graph.build_graph([(_sf("r", "svc.php", "php"), php)])
    run_id = g["by_name"]["run"][0]
    e = _edges(g, run_id)
    shared_id = g["by_name"]["shared"][0]
    own_id = g["by_name"]["own"][0]
    # $this->shared() résolu dans la classe PARENT (hiérarchie) → confiance forte
    assert e.get(shared_id) == graph.C_HIER
    assert e.get(own_id) == graph.C_HIER


def test_resolve_static_and_new_via_use() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    files = [
        (_sf("r", "geo.php", "php"),
         "<?php\nnamespace App\\Util;\nclass Geo { function load() {} }\n"),
        (_sf("r", "svc.php", "php"),
         "<?php\nnamespace App;\nuse App\\Util\\Geo;\n"
         "class Svc { function run() { Geo::load(); new Geo(); } }\n"),
    ]
    g = graph.build_graph(files)
    run_id = g["by_name"]["run"][0]
    e = _edges(g, run_id)
    load_id = g["by_name"]["load"][0]
    geo_id = g["by_fqn"]["App\\Util\\Geo"][0]
    assert e.get(load_id) == graph.C_STATIC          # Geo::load() résolu via use → classe → méthode
    assert e.get(geo_id) == graph.C_STATIC           # new Geo() → constructeur/classe


def test_namespaced_free_function_not_collapsed_when_ambiguous() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    # deux 'dup' GLOBAUX (ns="") + un appelant → ambigu (pas de fausse précision FQN)
    files = [
        (_sf("r", "a.php", "php"), "<?php\nfunction dup() { return 1; }\n"),
        (_sf("r", "b.php", "php"), "<?php\nfunction dup() { return 2; }\n"),
        (_sf("r", "c.php", "php"), "<?php\nfunction caller() { return dup(); }\n"),
    ]
    g = graph.build_graph(files)
    e = _edges(g, g["by_name"]["caller"][0])
    assert len(e) == 2 and all(c == graph.C_AMBIG for c in e.values())   # incertain, non collapsé


def test_unique_free_function_resolved() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    files = [
        (_sf("r", "u.php", "php"), "<?php\nfunction only_one() { return 1; }\n"),
        (_sf("r", "c.php", "php"), "<?php\nfunction caller() { return only_one(); }\n"),
    ]
    g = graph.build_graph(files)
    e = _edges(g, g["by_name"]["caller"][0])
    assert e.get(g["by_name"]["only_one"][0]) == graph.C_SAMENS   # global unique → fqn unique


def test_build_graph_prunes_ubiquitous_call_names() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    files = [(_sf("r", "lib.py", "python"), "class S:\n    def push(self):\n        return 1\n")]
    files.append((_sf("r", "many.py", "python"),
                  "\n".join(f"def c{i}():\n    x.push()\n" for i in range(5))))
    g = graph.build_graph(files, max_call_freq=3)
    push_id = g["by_name"]["push"][0]
    assert push_id not in graph._reverse(g["out"])          # 'push' bloqué (5 appels > 3)


def test_pagerank_and_fanin_present() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    for n in g["nodes"].values():
        assert "centrality" in n and "fan_in" in n


def test_is_minified_detection() -> None:
    assert graph._is_minified("web/js/app.min.js", "x")
    assert graph._is_minified("vendor/lib/foo.js", "x")
    assert graph._is_minified("a.js", "var x=1;" + "a" * 3000)
    assert not graph._is_minified("src/app.js", "const x = 1\nconst y = 2\n")


# ── code_impact ───────────────────────────────────────────────────────────────────

def _chain_graph():
    src = ("def c():\n    return 1\n\n"
           "def b():\n    return c()\n\n"
           "def a():\n    return b()\n")
    return graph.build_graph([(_sf("r", "pkg/chain.py", "python"), src)])


def test_code_impact_callers_blast_radius() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.code_impact(g, "c", direction="callers", depth=2)
    names = {(n["qname"], n["depth"]) for n in res["impacted"]}
    assert ("b", 1) in names and ("a", 2) in names
    res1 = graph.code_impact(g, "c", direction="callers", depth=1)
    assert {n["qname"] for n in res1["impacted"]} == {"b"}


def test_code_impact_callees_dependencies() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.code_impact(g, "a", direction="callees", depth=2)
    assert {n["qname"] for n in res["impacted"]} == {"b", "c"}


def test_code_impact_tiers_and_subsystem() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.code_impact(g, "c", direction="callers", depth=2)
    # b et c sont résolus en nom unique (≥0.75) → tier certain/probable, jamais d'erreur
    assert set(res["tiers"]) == {"certain", "probable", "incertain"}
    assert all(n["tier"] in ("certain", "probable", "incertain") for n in res["impacted"])
    assert res["by_subsystem"]                         # regroupé par repo/dossier de tête
    assert all("/" in k for k in res["by_subsystem"])


def test_code_impact_ambiguous_is_incertain() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    files = [
        (_sf("r", "a.php", "php"), "<?php\nfunction dup() { return 1; }\n"),
        (_sf("r", "b.php", "php"), "<?php\nfunction dup() { return 2; }\n"),
        (_sf("r", "c.php", "php"), "<?php\nfunction caller() { return dup(); }\n"),
    ]
    g = graph.build_graph(files)
    res = graph.code_impact(g, "caller", direction="callees")
    assert all(n["tier"] == "incertain" for n in res["impacted"])   # arêtes 0.35


def test_code_impact_unknown_symbol() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.code_impact(g, "inexistant", direction="callers")
    assert res["roots"] == [] and res["impacted"] == []


# ── Mode fichier ──────────────────────────────────────────────────────────────────

def test_code_impact_file_mode() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    files = [
        (_sf("r", "lib/util.py", "python"), "def helper():\n    return 1\n\ndef other():\n    return 2\n"),
        (_sf("r", "app/main.py", "python"), "from x import y\ndef run():\n    return helper()\n"),
    ]
    g = graph.build_graph(files)
    # « qu'est-ce qui casse si je supprime lib/util.py » → run (appelle helper)
    res = graph.code_impact(g, "lib/util.py", direction="callers", depth=2)
    assert res["scope"] == "file"
    assert res["files"] == ["r/lib/util.py"]
    assert len(res["roots"]) == 2                       # helper + other = symboles du fichier
    assert "run" in {n["qname"] for n in res["impacted"]}


def test_code_impact_symbol_takes_precedence_over_path() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.code_impact(g, "c", direction="callers")   # 'c' est un symbole, pas un chemin
    assert res["scope"] == "symbol"


# ── code_hotspots ─────────────────────────────────────────────────────────────────

def test_code_hotspots_ranking_and_filter() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.code_hotspots(g, top=5, by="fan_in")
    qn = [h["qname"] for h in res["hotspots"]]
    assert "c" in qn and "<module>" not in qn           # module exclu
    # c (appelé par b) a un fan-in ≥ a (appelé par personne) → c avant a
    assert qn.index("c") < qn.index("a")
    # filtre repo inexistant → vide
    assert graph.code_hotspots(g, repo="absent")["hotspots"] == []


def test_load_graph_roundtrip_and_gzip(tmp_path) -> None:
    pytest.importorskip("tree_sitter_language_pack")
    import gzip
    import json
    g = _chain_graph()
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(g), encoding="utf-8")
    loaded = graph.load_graph(p)
    assert "in" in loaded
    res = graph.code_impact(loaded, "c", direction="callers", depth=2)
    assert {n["qname"] for n in res["impacted"]} == {"a", "b"}
    pgz = tmp_path / "graph.json.gz"
    pgz.write_bytes(gzip.compress(json.dumps(g).encode("utf-8")))
    assert graph.load_graph(pgz)["nodes"] == g["nodes"]


# ── shortest_path ───────────────────────────────────────────────────────────────

def test_shortest_path_src_to_dst() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()       # a → b → c (out)
    res = graph.shortest_path(g, "a", "c")
    assert res["found"] is True
    assert res["direction"] == "src->dst"
    assert [n["qname"] for n in res["path"]] == ["a", "b", "c"]
    # min_confidence = min des confiances des arêtes du chemin (b→c, a→b sont C_UNIQUE/SAMENS)
    assert res["min_confidence"] == pytest.approx(min(n["confidence"] for n in res["path"][1:]))
    assert res["src_roots"] and res["dst_roots"]


def test_shortest_path_falls_back_to_reverse_direction() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()       # a → b → c (out) : pas de chemin c→a, mais a→c existe
    res = graph.shortest_path(g, "c", "a")
    assert res["found"] is True
    assert res["direction"] == "dst->src"      # trouvé en sens inverse (a→…→c)
    assert [n["qname"] for n in res["path"]] == ["a", "b", "c"]


def test_shortest_path_same_symbol() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.shortest_path(g, "b", "b")
    assert res["found"] is True
    assert [n["qname"] for n in res["path"]] == ["b"]
    assert res["min_confidence"] == 1.0


def test_shortest_path_unresolved_src() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()
    res = graph.shortest_path(g, "inexistant", "c")
    assert res["found"] is False
    assert res["src_roots"] == [] and res["direction"] is None


def test_shortest_path_no_path_within_depth() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    # deux composantes disjointes : x→y et z (isolé) → aucun chemin
    files = [
        (_sf("r", "p.py", "python"),
         "def y():\n    return 1\n\ndef x():\n    return y()\n"),
        (_sf("r", "q.py", "python"), "def z():\n    return 0\n"),
    ]
    g = graph.build_graph(files)
    res = graph.shortest_path(g, "x", "z")
    assert res["found"] is False


def test_shortest_path_tiebreak_prefers_higher_min_confidence() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    # a atteint d par deux chemins de même longueur ; on construit le graphe à la main pour
    # contrôler les confiances. a→b (0.9)→d (0.9)  vs  a→c (0.4)→d (0.9).
    nodes = {}
    for q, ln in (("a", 1), ("b", 2), ("c", 3), ("d", 4)):
        nid = f"r/m.py:{ln}:{q}"
        nodes[nid] = {"name": q, "qname": q, "repo": "r", "path": "m.py", "lang": "python",
                      "kind": "function", "start_line": ln, "end_line": ln,
                      "fan_in": 0, "centrality": 0.0}
    out = {
        "r/m.py:1:a": [["r/m.py:2:b", 0.9], ["r/m.py:3:c", 0.4]],
        "r/m.py:2:b": [["r/m.py:4:d", 0.9]],
        "r/m.py:3:c": [["r/m.py:4:d", 0.9]],
    }
    g = {"version": "graph-v2", "nodes": nodes, "by_name": {q: [nid] for nid, q in
         ((nid, n["qname"]) for nid, n in nodes.items())}, "by_fqn": {}, "out": out}
    res = graph.shortest_path(g, "a", "d")
    assert res["found"] is True
    assert [n["qname"] for n in res["path"]] == ["a", "b", "d"]   # min-conf 0.9 préféré à 0.4
    assert res["min_confidence"] == pytest.approx(0.9)


# ── dead_symbols ────────────────────────────────────────────────────────────────

def test_dead_symbols_lists_zero_fanin_functions() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    g = _chain_graph()       # a → b → c : seul 'a' a fan_in 0 (et n'est ni classe ni module)
    res = graph.dead_symbols(g)
    qn = {s["qname"] for s in res["symbols"]}
    assert "a" in qn
    assert "b" not in qn and "c" not in qn        # b et c ont des appelants
    assert "<module>" not in qn
    assert res["count"] == len(res["symbols"])
    assert "caveat" in res and "point" in res["caveat"].lower()   # mentionne les points d'entrée


def test_dead_symbols_excludes_classes() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    files = [(_sf("r", "lib.php", "php"),
              "<?php\nclass Orphan { function unused() {} }\n")]
    g = graph.build_graph(files)
    res = graph.dead_symbols(g)
    kinds = {s["kind"] for s in res["symbols"]}
    assert "class" not in kinds                    # classes exclues même à fan_in 0
    qn = {s["qname"] for s in res["symbols"]}
    assert "Orphan" not in qn


def test_dead_symbols_repo_and_subsystem_filter() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    files = [
        (_sf("r1", "svc/a.py", "python"), "def lonely():\n    return 1\n"),
        (_sf("r2", "svc/b.py", "python"), "def other():\n    return 2\n"),
    ]
    g = graph.build_graph(files)
    res = graph.dead_symbols(g, repo="r1")
    assert {s["repo"] for s in res["symbols"]} == {"r1"}
    res2 = graph.dead_symbols(g, subsystem="r2/svc")
    assert {s["subsystem"] for s in res2["symbols"]} == {"r2/svc"}


def test_dead_symbols_top_truncation() -> None:
    pytest.importorskip("tree_sitter_language_pack")
    src = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(5))
    g = graph.build_graph([(_sf("r", "many.py", "python"), src)])
    res = graph.dead_symbols(g, top=2)
    assert res["count"] == 2
    assert res["truncated"] is True
