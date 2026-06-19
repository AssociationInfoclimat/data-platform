"""Graphe d'appels du code (Phase 4) : « qu'est-ce qui casse si je change X ? »

Complète le `lineage` data curé (flux de tables/pipelines) par un graphe **de code**
extrait statiquement via tree-sitter (PHP/Python/TS/JS) : définitions (fonctions, classes,
méthodes) reliées par leurs sites d'appel. L'outil `code_impact` parcourt ce graphe :
- ``callers``  (défaut) : qui appelle X, transitivement = **rayon d'impact** d'un changement ;
- ``callees`` : ce dont X dépend (ses appels sortants).

Résolution **par nom** (pragmatique, multi-langage) : un appel à ``foo()`` pointe vers
toute définition nommée ``foo``. C'est une SUR-approximation ; pour rester utile on élague
les noms trop ambigus (``--max-fanout``, défaut 6) — un nom défini partout (``run``, ``get``)
ne produit pas d'arêtes. Limitation assumée et signalée dans la sortie.

Le graphe est un **artefact JSON** (comme l'index LanceDB) : construit une fois (pur
tree-sitter, AUCUN appel API), livré à côté de l'index, lu par le bot/MCP. Sans
``tree_sitter_language_pack`` (CI) l'extraction renvoie un graphe vide — rien ne casse.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import deque
from pathlib import Path
from typing import Iterable, Iterator

from . import tsutil, walk
from .meta import chunk_url

GRAPH_VERSION = "graph-v1"

# Étiquette de langage (walk.LANG_BY_EXT) → nom tree-sitter.
_TS_LANG = {"php": "php", "python": "python", "ts": "typescript", "js": "javascript"}

# Nœuds « définition » → genre lisible, par grammaire tree-sitter.
_DEF_TYPES = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "php": {"function_definition": "function", "method_declaration": "method",
            "class_declaration": "class", "interface_declaration": "interface",
            "trait_declaration": "trait", "enum_declaration": "enum"},
    "typescript": {"function_declaration": "function", "method_definition": "method",
                   "class_declaration": "class", "interface_declaration": "interface",
                   "enum_declaration": "enum", "abstract_class_declaration": "class"},
    "javascript": {"function_declaration": "function", "method_definition": "method",
                   "class_declaration": "class"},
}

# Nœuds « site d'appel », par grammaire.
_CALL_TYPES = {
    "python": {"call"},
    "php": {"function_call_expression", "member_call_expression", "scoped_call_expression"},
    "typescript": {"call_expression"},
    "javascript": {"call_expression"},
}

MODULE_QNAME = "<module>"   # portée fichier (appels hors de toute définition)


# ── Extraction par fichier ────────────────────────────────────────────────────

def _leaf_name(node, src: bytes) -> str:
    """Dernier segment d'un nom qualifié/membre : ``os.path.join`` → ``join``,
    ``Foo\\Bar`` → ``Bar``, ``$this->helper`` → ``helper``."""
    if node is None:
        return ""
    if tsutil.kind(node) in ("identifier", "name"):
        return tsutil.node_text(node, src).strip()
    kids = tsutil.named_children(node)
    if kids:
        return _leaf_name(kids[-1], src)
    return tsutil.node_text(node, src).strip()


def _callee_name(node, ts_lang: str, src: bytes) -> str:
    """Nom de la fonction/méthode appelée par un nœud d'appel (champ selon la grammaire)."""
    if ts_lang == "php" and tsutil.kind(node) in ("member_call_expression",
                                                  "scoped_call_expression"):
        return _leaf_name(tsutil.child_by_field(node, "name"), src)  # méthode : champ "name"
    return _leaf_name(tsutil.child_by_field(node, "function"), src)   # py/ts/js + php libre


def extract_file(lang: str, text: str) -> tuple[list[dict], list[dict]]:
    """(définitions, appels) d'un fichier. Définitions : {name, qname, kind, start_line,
    end_line}. Appels : {caller (qname englobant ou ""), callee (nom), line}. Vide si le
    langage n'est pas outillé ou si le parsing échoue (jamais d'exception)."""
    ts_lang = _TS_LANG.get(lang)
    parser = tsutil.get_parser(ts_lang) if ts_lang else None
    if parser is None or not text.strip():
        return [], []
    try:
        tree = tsutil.parse(parser, text)
        root = tsutil.root(tree)
    except Exception:  # noqa: BLE001
        return [], []
    src = text.encode("utf-8", errors="replace")
    def_types = _DEF_TYPES.get(ts_lang, {})
    call_types = _CALL_TYPES.get(ts_lang, set())
    defs: list[dict] = []
    calls: list[dict] = []
    stack: list[str] = []  # pile des noms englobants → qname (Classe.méthode)

    def visit(node) -> None:
        k = tsutil.kind(node)
        pushed = False
        if k in def_types:
            nm = tsutil.child_by_field(node, "name")
            name = tsutil.node_text(nm, src).strip() if nm is not None else ""
            if name:
                defs.append({"name": name, "qname": ".".join(stack + [name]),
                             "kind": def_types[k],
                             "start_line": tsutil.start_row(node) + 1,
                             "end_line": tsutil.end_row(node) + 1})
                stack.append(name)
                pushed = True
        elif k in call_types:
            cn = _callee_name(node, ts_lang, src)
            if cn:
                calls.append({"caller": ".".join(stack), "callee": cn,
                              "line": tsutil.start_row(node) + 1})
        for c in tsutil.named_children(node):
            visit(c)
        if pushed:
            stack.pop()

    visit(root)
    return defs, calls


# ── Construction du graphe ─────────────────────────────────────────────────────

def _node_id(repo: str, path: str, start_line: int, qname: str) -> str:
    return f"{repo}/{path}:{start_line}:{qname}"


def build_graph(files: Iterable[tuple[walk.SourceFile, str]], *,
                max_name_fanout: int = 6, max_call_freq: int = 200) -> dict:
    """Construit le graphe d'appels à partir d'un itérable (SourceFile, texte).

    Résolution par nom : une arête caller→callee est créée pour CHAQUE définition portant
    le nom appelé. Deux garde-fous data-driven contre les collisions avec des primitives
    (``.push()``, ``.map()``, ``substr()``…) qui parasitent une résolution par nom :
    - `max_name_fanout` : un nom défini plus de N fois est trop ambigu → non relié ;
    - `max_call_freq`   : un nom appelé depuis plus de N sites est quasi sûrement une
      primitive du langage/bibliothèque (ex. ``push`` ~2900×) → non relié.
    Les appels vers des noms inconnus (stdlib/externe) sont aussi ignorés (on ne graphe
    que les symboles internes)."""
    nodes: dict[str, dict] = {}
    by_name: dict[str, list[str]] = {}
    call_freq: dict[str, int] = {}
    # passe 1 : toutes les définitions deviennent des nœuds (by_name complet AVANT les arêtes)
    pending: list[tuple[walk.SourceFile, list[dict], dict[str, str]]] = []
    for sf, text in files:
        defs, calls = extract_file(sf.lang, text)
        qmap: dict[str, str] = {}
        for d in defs:
            nid = _node_id(sf.repo, sf.path, d["start_line"], d["qname"])
            nodes[nid] = {"name": d["name"], "qname": d["qname"], "repo": sf.repo,
                          "path": sf.path, "lang": sf.lang, "kind": d["kind"],
                          "start_line": d["start_line"], "end_line": d["end_line"]}
            by_name.setdefault(d["name"], []).append(nid)
            qmap[d["qname"]] = nid
        for c in calls:
            call_freq[c["callee"]] = call_freq.get(c["callee"], 0) + 1
        if calls:
            pending.append((sf, calls, qmap))

    # noms à ne PAS relier : trop de définitions (ambigu) ou trop d'appels (primitive)
    blocked = {nm for nm, ids in by_name.items() if len(ids) > max_name_fanout}
    blocked |= {nm for nm, f in call_freq.items() if f > max_call_freq}

    # passe 2 : arêtes caller→callee, résolues par nom
    out: dict[str, set[str]] = {}
    for sf, calls, qmap in pending:
        module_id: str | None = None
        for c in calls:
            if c["callee"] in blocked:
                continue
            targets = by_name.get(c["callee"])
            if not targets:
                continue  # nom inconnu (externe) → pas d'arête
            caller = c["caller"]
            if caller and caller in qmap:
                src_id = qmap[caller]
            elif caller and any(caller.startswith(q + ".") or q == caller for q in qmap):
                # appel dans une portée englobante connue (méthode imbriquée non capturée)
                src_id = next(qmap[q] for q in qmap
                              if caller == q or caller.startswith(q + "."))
            else:
                # appel au niveau module : nœud de portée fichier, créé à la demande
                if module_id is None:
                    module_id = _node_id(sf.repo, sf.path, 1, MODULE_QNAME)
                    nodes.setdefault(module_id, {
                        "name": MODULE_QNAME, "qname": MODULE_QNAME, "repo": sf.repo,
                        "path": sf.path, "lang": sf.lang, "kind": "module",
                        "start_line": 1, "end_line": 1})
                src_id = module_id
            for tid in targets:
                if tid != src_id:  # on garde la récursion directe ? non : self-edge inutile ici
                    out.setdefault(src_id, set()).add(tid)

    return {
        "version": GRAPH_VERSION,
        "nodes": nodes,
        "by_name": by_name,
        "out": {k: sorted(v) for k, v in out.items()},
    }


def _is_minified(path: str, text: str) -> bool:
    """Fichier minifié/bundlé (junk pour un graphe : identifiants mutilés, tout sur une
    ligne) : nom révélateur, ou une ligne anormalement longue (source jamais > ~2 000 car.)."""
    low = path.lower()
    if any(m in low for m in (".min.", "-min.", ".bundle.")):
        return True
    if {"vendor", "dist", "node_modules"} & set(low.split("/")):
        return True
    return any(len(ln) > 2000 for ln in text.split("\n", 50)[:50])


def _iter_supported(manifest: dict, base_dir: Path, repos: list[str] | None,
                    max_file_bytes: int) -> Iterator[tuple[walk.SourceFile, str]]:
    """Fichiers des langages outillés (PHP/Py/TS/JS), texte décodé, hors minifiés/bundles."""
    for sf in walk.iter_files(manifest, base_dir, repos=repos, max_file_bytes=max_file_bytes):
        if sf.lang not in _TS_LANG:
            continue
        try:
            text = sf.abspath.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if text.strip() and not _is_minified(sf.path, text):
            yield sf, text


# ── Requête : code_impact ──────────────────────────────────────────────────────

def load_graph(path: str | Path) -> dict:
    """Charge un graphe (`.json` ou `.json.gz`) et calcule l'index inverse `in`
    (callers) à partir de `out`."""
    p = Path(path)
    raw = (gzip.decompress(p.read_bytes()).decode("utf-8") if p.suffix == ".gz"
           else p.read_text(encoding="utf-8"))
    g = json.loads(raw)
    rev: dict[str, list[str]] = {}
    for src_id, tgts in g.get("out", {}).items():
        for t in tgts:
            rev.setdefault(t, []).append(src_id)
    g["in"] = {k: sorted(v) for k, v in rev.items()}
    return g


def resolve_symbol(graph: dict, symbol: str) -> list[str]:
    """Identifiants de nœuds correspondant à `symbol` : nom exact, ou suffixe de qname
    (``Classe.methode`` / ``methode``), ou ``chemin:ligne``. Insensible à la casse en repli."""
    s = symbol.strip()
    if not s:
        return []
    nodes = graph.get("nodes", {})
    # 1) nom exact (le plus courant)
    hits = list(graph.get("by_name", {}).get(s, []))
    if hits:
        return hits
    # 2) chemin:ligne
    if ":" in s:
        head = s.rsplit(":", 1)
        if head[1].isdigit():
            ln = int(head[1])
            hits = [nid for nid, n in nodes.items()
                    if n["path"].endswith(head[0]) and n["start_line"] == ln]
            if hits:
                return hits
    # 3) qname exact ou suffixe (Classe.methode), insensible à la casse
    sl = s.lower()
    return [nid for nid, n in nodes.items()
            if n["qname"].lower() == sl or n["qname"].lower().endswith("." + sl)]


def code_impact(graph: dict, symbol: str, *, direction: str = "callers", depth: int = 2,
                max_nodes: int = 40, sidecar: dict | None = None) -> dict:
    """Parcours BFS borné du graphe depuis `symbol`.

    direction = ``callers`` (qui appelle X, transitif = rayon d'impact) ou ``callees``
    (ce dont X dépend). Renvoie {roots, impacted, truncated, ambiguous} ; chaque nœud est
    enrichi de son URL source (permalien) si un `sidecar` méta est fourni."""
    if "in" not in graph:  # graphe chargé sans load_graph (ex. fraîchement construit)
        graph = {**graph, "in": _reverse(graph.get("out", {}))}
    edges = graph["in"] if direction == "callers" else graph.get("out", {})
    roots = resolve_symbol(graph, symbol)
    nodes = graph.get("nodes", {})

    # Un conteneur (classe/interface/trait/enum) « tire » ses membres comme graines : changer
    # la classe, c'est changer ses méthodes ⇒ impact = celui de la classe OU d'un membre.
    seeds = set(roots)
    for r in roots:
        n = nodes.get(r)
        if n and n["kind"] in ("class", "interface", "trait", "enum"):
            pref = n["qname"] + "."
            seeds.update(nid for nid, nn in nodes.items()
                         if nn["repo"] == n["repo"] and nn["path"] == n["path"]
                         and nn["qname"].startswith(pref))

    seen: dict[str, int] = {s: 0 for s in seeds}   # graines en prof 0 → exclues des résultats
    order: list[tuple[str, int]] = []
    frontier = list(seeds)
    d = 0
    while frontier and d < depth:
        d += 1
        nxt: list[str] = []
        for nid in frontier:
            for m in edges.get(nid, []):
                if m not in seen:
                    seen[m] = d
                    nxt.append(m)
                    order.append((m, d))
        frontier = nxt

    truncated = len(order) > max_nodes
    impacted = [_describe(nodes[i], dep, sidecar) for i, dep in order[:max_nodes] if i in nodes]
    return {
        "symbol": symbol,
        "direction": direction,
        "depth": depth,
        "roots": [_describe(nodes[r], 0, sidecar) for r in roots if r in nodes],
        "ambiguous": len(roots) > 1,
        "impacted": impacted,
        "truncated": truncated,
    }


def _reverse(out: dict) -> dict:
    rev: dict[str, list[str]] = {}
    for s, tgts in out.items():
        for t in tgts:
            rev.setdefault(t, []).append(s)
    return rev


def _describe(node: dict, depth: int, sidecar: dict | None) -> dict:
    url = (chunk_url(sidecar, node["repo"], node["path"],
                     node["start_line"], node["end_line"]) if sidecar else "")
    return {"qname": node["qname"], "kind": node["kind"], "repo": node["repo"],
            "path": node["path"], "lang": node["lang"], "start_line": node["start_line"],
            "end_line": node["end_line"], "depth": depth, "source_url": url}


# ── CLI ─────────────────────────────────────────────────────────────────────────

def _cmd_build(args: argparse.Namespace) -> int:
    from .config import load_config, load_manifest
    cfg = load_config()
    base = args.base_dir or cfg.base_dir
    manifest = load_manifest(args.manifest)
    g = build_graph(_iter_supported(manifest, base, args.repos, cfg.max_file_bytes),
                    max_name_fanout=args.max_fanout)
    n_edges = sum(len(v) for v in g["out"].values())
    out_path = Path(args.out)
    data = json.dumps(g, ensure_ascii=False)
    if out_path.suffix == ".gz":
        out_path.write_bytes(gzip.compress(data.encode("utf-8")))
    else:
        out_path.write_text(data, encoding="utf-8")
    print(f"Graphe écrit : {out_path} — {len(g['nodes'])} nœuds, {n_edges} arêtes, "
          f"{len(g['by_name'])} noms (fanout max {args.max_fanout}).")
    return 0


def _cmd_impact(args: argparse.Namespace) -> int:
    graph = load_graph(args.graph)
    sidecar = json.loads(Path(args.meta).read_text(encoding="utf-8")) if args.meta else None
    res = code_impact(graph, args.symbol, direction=args.direction, depth=args.depth,
                      sidecar=sidecar)
    if not res["roots"]:
        print(f"Symbole introuvable dans le graphe : {args.symbol}", file=sys.stderr)
        return 1
    verb = "appelé par" if args.direction == "callers" else "dépend de"
    print(f"# {args.symbol} — {verb} (profondeur {args.depth})")
    if res["ambiguous"]:
        print(f"  ⚠ {len(res['roots'])} définitions portent ce nom (résolution par nom).")
    for r in res["roots"]:
        print(f"  ⌖ {r['qname']} ({r['kind']}) {r['repo']}/{r['path']}:{r['start_line']}")
    for n in res["impacted"]:
        url = f"  {n['source_url']}" if n["source_url"] else ""
        print(f"  {'·' * n['depth']} {n['qname']} ({n['kind']}) "
              f"{n['repo']}/{n['path']}:{n['start_line']}{url}")
    if res["truncated"]:
        print("  … (résultats tronqués)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Graphe d'appels du code Infoclimat (tree-sitter).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Construire l'artefact graphe (JSON).")
    b.add_argument("--out", required=True, help="Fichier de sortie (.json ou .json.gz).")
    b.add_argument("--base-dir", type=Path, default=None)
    b.add_argument("--manifest", type=Path, default=None)
    b.add_argument("--repo", action="append", dest="repos", default=None)
    b.add_argument("--max-fanout", type=int, default=6,
                   help="Au-delà de N définitions homonymes, le nom n'est pas relié (anti-bruit).")
    b.set_defaults(func=_cmd_build)

    q = sub.add_parser("impact", help="Rayon d'impact / dépendances d'un symbole.")
    q.add_argument("symbol")
    q.add_argument("--graph", required=True, help="Artefact graphe (.json/.json.gz).")
    q.add_argument("--direction", choices=["callers", "callees"], default="callers")
    q.add_argument("--depth", type=int, default=2)
    q.add_argument("--meta", default=None, help="Sidecar méta (pour les URLs source).")
    q.set_defaults(func=_cmd_impact)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
