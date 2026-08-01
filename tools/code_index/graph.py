"""Graphe d'appels du code (Phase 4, v2) : « qu'est-ce qui casse si je change X ? »

Complète le `lineage` data curé par un graphe **de code** extrait statiquement via
tree-sitter (PHP/Python/TS/JS). `code_impact` le parcourt : ``callers`` (qui appelle X,
transitivement = rayon d'impact), ``callees`` (ce dont X dépend).

v2 — résolution **par cascade à score de confiance** (état de l'art accessible sans
compilateur : scope/stack graphs, SCIP, cascade « Codebase-Memory ») plutôt que la simple
correspondance de nom :

  1. ``$this->m()`` / ``self::m()`` / ``parent::m()`` → résolu dans la classe englobante
     et sa **hiérarchie** (extends/implements/use trait) — conf 0.95 ;
  2. ``Class::m()`` / ``new Class()`` → classe résolue via ``use``/namespace (PHP) ou
     import (TS/PY) puis méthode/constructeur dans la classe+hiérarchie — conf 0.9 ;
  3. fonction libre ``foo()`` : import-exact (``use`` PHP, import relatif TS/PY → fichier)
     0.95, même-namespace/même-fichier 0.9, nom unique projet 0.75, sinon ambigu 0.35 ;
  4. ``$obj->m()`` (receveur de type inconnu) → name-based.

Chaque arête porte sa **confiance**. Les arêtes fortes (≥0.7) ne sont JAMAIS élaguées ; le
fallback name-based bas-confiance reste élagué par fanout/fréquence d'appel (anti-collision
avec les primitives ``.push()``). La sortie bucketise en **Certain/Probable/Incertain**
(certitude d'un chemin = min des confiances) — ambiguïté affichée honnêtement. Au build on
calcule aussi **fan-in** et **centralité PageRank** par nœud (classement du rayon d'impact,
façon repo-map Aider).

Pur AST, **aucun appel API** → artefact reconstructible partout. Sans
``tree_sitter_language_pack`` (CI) l'extraction renvoie un graphe vide — rien ne casse.
"""
from __future__ import annotations

import argparse
import gzip
import json
import posixpath
import sys
from pathlib import Path
from typing import Iterable, Iterator

from . import tsutil, walk
from .meta import chunk_url

GRAPH_VERSION = "graph-v2"

_TS_LANG = {"php": "php", "python": "python", "ts": "typescript", "js": "javascript"}

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
_CLASS_KINDS = {"class", "interface", "trait", "enum"}

_CALL_TYPES = {
    "python": {"call"},
    "php": {"function_call_expression", "member_call_expression",
            "scoped_call_expression", "object_creation_expression"},
    "typescript": {"call_expression", "new_expression"},
    "javascript": {"call_expression", "new_expression"},
}

MODULE_QNAME = "<module>"

# Confiance par stratégie de résolution.
C_HIER = 0.95       # this/self/parent résolu dans la hiérarchie de classe
C_STATIC = 0.90     # Class::m / new Class résolu
C_IMPORT = 0.95     # fonction importée (use / import relatif) → fichier exact
C_SAMENS = 0.90     # même namespace / même fichier
C_UNIQUE = 0.75     # nom unique dans tout le projet
C_MEMBER1 = 0.60    # $obj->m receveur inconnu, mais nom unique
C_AMBIG = 0.35      # plusieurs définitions homonymes (name-based)
STRONG = 0.70       # au-dessus : jamais élagué
TIER_CERTAIN, TIER_PROBABLE = 0.80, 0.50


# ── Helpers d'extraction ────────────────────────────────────────────────────────

def _name_of(node, src: bytes) -> str:
    nm = tsutil.child_by_field(node, "name")
    return tsutil.node_text(nm, src).strip() if nm is not None else ""


def _leaf_name(node, src: bytes) -> str:
    """Dernier segment d'un nom qualifié/membre (os.path.join→join, Foo\\Bar→Bar)."""
    if node is None:
        return ""
    if tsutil.kind(node) in ("identifier", "name", "property_identifier", "type_identifier"):
        return tsutil.node_text(node, src).strip()
    kids = tsutil.named_children(node)
    return _leaf_name(kids[-1], src) if kids else tsutil.node_text(node, src).strip()


def _receiver(node, ts_lang: str, src: bytes) -> tuple[str, str, str]:
    """(callee_name, receiver_kind, receiver_class). kind ∈ free|this|self|parent|static|new|member."""
    k = tsutil.kind(node)
    if ts_lang == "php":
        if k == "object_creation_expression":              # new Class()
            cls = next((c for c in tsutil.named_children(node)
                        if tsutil.kind(c) in ("name", "qualified_name")), None)
            return ("__construct", "new", _leaf_name(cls, src))
        if k == "scoped_call_expression":                  # self::/parent::/Class::
            scope = tsutil.child_by_field(node, "scope")
            meth = _leaf_name(tsutil.child_by_field(node, "name"), src)
            st = tsutil.node_text(scope, src).strip() if scope is not None else ""
            if st in ("self", "static"):
                return (meth, "self", "")
            if st == "parent":
                return (meth, "parent", "")
            return (meth, "static", _leaf_name(scope, src))
        if k == "member_call_expression":                  # $x->m()
            obj = tsutil.child_by_field(node, "object")
            meth = _leaf_name(tsutil.child_by_field(node, "name"), src)
            if obj is not None and tsutil.node_text(obj, src).strip() == "$this":
                return (meth, "this", "")
            return (meth, "member", "")
        return (_leaf_name(tsutil.child_by_field(node, "function"), src), "free", "")
    # python / ts / js
    if k == "new_expression":
        return ("__construct", "new",
                _leaf_name(tsutil.child_by_field(node, "constructor"), src))
    fn = tsutil.child_by_field(node, "function")
    if fn is not None and tsutil.kind(fn) in ("attribute", "member_expression"):
        kids = tsutil.named_children(fn)
        base = tsutil.node_text(kids[0], src).strip() if kids else ""
        meth = _leaf_name(fn, src)
        return (meth, "this", "") if base in ("self", "this") else (meth, "member", "")
    return (_leaf_name(fn, src), "free", "")


def _bases(node, ts_lang: str, src: bytes) -> list[str]:
    """Noms (bruts) des classes/interfaces/traits parents d'une déclaration de classe."""
    out: list[str] = []
    if ts_lang == "python":
        al = next((c for c in tsutil.named_children(node)
                   if tsutil.kind(c) == "argument_list"), None)
        if al is not None:
            out += [tsutil.node_text(c, src).strip().split(".")[-1]
                    for c in tsutil.named_children(al) if tsutil.kind(c) == "identifier"]
        return out
    for c in tsutil.named_children(node):
        ck = tsutil.kind(c)
        if ck in ("base_clause", "class_interface_clause", "class_heritage"):
            for d in tsutil.named_children(c):
                dk = tsutil.kind(d)
                if dk in ("name", "identifier", "type_identifier", "qualified_name"):
                    out.append(_leaf_name(d, src))
                elif dk in ("extends_clause", "implements_clause"):
                    out += [_leaf_name(e, src) for e in tsutil.named_children(d)]
        elif ck == "use_declaration":   # php : use TraitX; dans le corps de classe
            out += [_leaf_name(d, src) for d in tsutil.named_children(c)
                    if tsutil.kind(d) in ("name", "qualified_name")]
    return out


def _php_namespace(root, src: bytes) -> str:
    for c in tsutil.named_children(root):
        if tsutil.kind(c) == "namespace_definition":
            nm = tsutil.child_by_field(c, "name")
            return tsutil.node_text(nm, src).strip().strip("\\") if nm is not None else ""
    return ""


def _imports(root, ts_lang: str, src: bytes, file_dir: str) -> dict[str, dict]:
    """alias → {fqn} (PHP use) ou {name, rel} (import relatif PY/TS)."""
    imp: dict[str, dict] = {}
    if ts_lang == "php":
        def walk_use(n):
            if tsutil.kind(n) == "namespace_use_clause":
                txt = tsutil.node_text(n, src).strip()
                fqn, alias = txt, None
                if " as " in txt:
                    fqn, alias = [p.strip() for p in txt.split(" as ", 1)]
                fqn = fqn.strip("\\")
                imp[alias or fqn.split("\\")[-1]] = {"fqn": fqn}
            for c in tsutil.named_children(n):
                walk_use(c)
        walk_use(root)
        return imp

    for c in tsutil.named_children(root):
        ck = tsutil.kind(c)
        if ts_lang == "python" and ck == "import_from_statement":
            mod = next((tsutil.node_text(d, src).strip() for d in tsutil.named_children(c)
                        if tsutil.kind(d) == "dotted_name"), "")
            rel = _py_rel(mod, file_dir)
            if rel is None:
                continue
            for d in tsutil.named_children(c):
                if tsutil.kind(d) == "aliased_import":
                    nm, al = _name_of(d, src), _leaf_name(tsutil.named_children(d)[-1], src)
                    if nm:
                        imp[al] = {"name": nm, "rel": rel}
                elif tsutil.kind(d) == "dotted_name" and tsutil.node_text(d, src).strip() != mod:
                    nm = tsutil.node_text(d, src).strip().split(".")[-1]
                    imp[nm] = {"name": nm, "rel": rel}
        elif ts_lang in ("typescript", "javascript") and ck == "import_statement":
            srcstr = next((tsutil.node_text(s, src).strip().strip("'\"")
                           for s in tsutil.named_children(c) if tsutil.kind(s) == "string"), "")
            rel = _ts_rel(srcstr, file_dir)
            if rel is None:
                continue
            clause = next((s for s in tsutil.named_children(c)
                           if tsutil.kind(s) == "import_clause"), None)
            if clause is None:
                continue
            for d in tsutil.named_children(clause):
                if tsutil.kind(d) == "identifier":               # import Default from …
                    imp[tsutil.node_text(d, src).strip()] = {"name": "default", "rel": rel}
                elif tsutil.kind(d) == "named_imports":          # { A, B as C }
                    for spec in tsutil.named_children(d):
                        if tsutil.kind(spec) == "import_specifier":
                            orig = _name_of(spec, src)
                            al = tsutil.child_by_field(spec, "alias")
                            alias = tsutil.node_text(al, src).strip() if al is not None else orig
                            if orig:
                                imp[alias] = {"name": orig, "rel": rel}
    return imp


def _py_rel(mod: str, file_dir: str) -> str | None:
    if not mod.startswith("."):
        return None
    up = len(mod) - len(mod.lstrip("."))
    rest = mod[up:].replace(".", "/")
    base = file_dir
    for _ in range(up - 1):
        base = posixpath.dirname(base)
    return posixpath.normpath(posixpath.join(base, rest)) if rest else base


def _ts_rel(srcstr: str, file_dir: str) -> str | None:
    return posixpath.normpath(posixpath.join(file_dir, srcstr)) if srcstr.startswith(".") else None


# ── Extraction par fichier ──────────────────────────────────────────────────────

def extract_file(lang: str, text: str, path: str = "") -> dict:
    """Infos structurelles d'un fichier : ns, imports, defs (avec hiérarchie), calls (avec
    receveur). Vide si langage non outillé / parsing impossible (jamais d'exception)."""
    empty = {"ns": "", "imports": {}, "defs": [], "calls": []}
    ts_lang = _TS_LANG.get(lang)
    parser = tsutil.get_parser(ts_lang) if ts_lang else None
    if parser is None or not text.strip():
        return empty
    try:
        tree = tsutil.parse(parser, text)
        root = tsutil.root(tree)
    except Exception:  # noqa: BLE001
        return empty
    src = text.encode("utf-8", errors="replace")
    def_types = _DEF_TYPES.get(ts_lang, {})
    call_types = _CALL_TYPES.get(ts_lang, set())
    ns = _php_namespace(root, src) if ts_lang == "php" else ""
    imports = _imports(root, ts_lang, src, posixpath.dirname(path))

    defs: list[dict] = []
    calls: list[dict] = []
    stack: list[str] = []
    class_stack: list[str] = []

    def visit(node) -> None:
        k = tsutil.kind(node)
        pushed = is_class = False
        if k in def_types:
            name = _name_of(node, src)
            if name:
                kind = def_types[k]
                d = {"name": name, "qname": ".".join(stack + [name]), "kind": kind,
                     "start_line": tsutil.start_row(node) + 1,
                     "end_line": tsutil.end_row(node) + 1}
                if kind in _CLASS_KINDS:
                    d["bases"] = _bases(node, ts_lang, src)
                    is_class = True
                defs.append(d)
                stack.append(name)
                pushed = True
                if is_class:
                    class_stack.append(d["qname"])
        elif k in call_types:
            callee, rkind, rclass = _receiver(node, ts_lang, src)
            if callee:
                calls.append({"callee": callee, "rkind": rkind, "rclass": rclass,
                              "caller": ".".join(stack),
                              "class": class_stack[-1] if class_stack else "",
                              "line": tsutil.start_row(node) + 1})
        for c in tsutil.named_children(node):
            visit(c)
        if pushed:
            stack.pop()
            if is_class:
                class_stack.pop()

    visit(root)
    return {"ns": ns, "imports": imports, "defs": defs, "calls": calls}


# ── Construction du graphe ───────────────────────────────────────────────────────

def _node_id(repo: str, path: str, start_line: int, qname: str) -> str:
    return f"{repo}/{path}:{start_line}:{qname}"


def _fqn(ns: str, qname: str) -> str:
    return f"{ns}\\{qname}" if ns else qname


def build_graph(files: Iterable[tuple[walk.SourceFile, str]], *,
                max_name_fanout: int = 6, max_call_freq: int = 200) -> dict:
    """Graphe d'appels à résolution par cascade. Voir le docstring du module."""
    nodes: dict[str, dict] = {}
    by_name: dict[str, list[str]] = {}
    by_fqn: dict[str, str] = {}
    classes: dict[str, dict] = {}
    file_defs: dict[tuple, dict] = {}
    pending: list[tuple] = []
    call_freq: dict[str, int] = {}

    for sf, text in files:
        info = extract_file(sf.lang, text, sf.path)
        ns = info["ns"]
        qmap: dict[str, str] = {}
        local: dict[str, list[str]] = {}
        class_fqn_by_q: dict[str, str] = {}
        for d in info["defs"]:
            nid = _node_id(sf.repo, sf.path, d["start_line"], d["qname"])
            nodes[nid] = {"name": d["name"], "qname": d["qname"], "repo": sf.repo,
                          "path": sf.path, "lang": sf.lang, "kind": d["kind"],
                          "start_line": d["start_line"], "end_line": d["end_line"]}
            by_name.setdefault(d["name"], []).append(nid)
            local.setdefault(d["name"], []).append(nid)
            qmap[d["qname"]] = nid
            by_fqn.setdefault(_fqn(ns, d["qname"]), []).append(nid)
            if d["kind"] in _CLASS_KINDS:
                cfqn = _fqn(ns, d["qname"])
                classes[cfqn] = {"id": nid, "bases": d.get("bases", []), "methods": {},
                                 "ns": ns, "imports": info["imports"], "lang": sf.lang}
                class_fqn_by_q[d["qname"]] = cfqn
        for d in info["defs"]:
            if d["kind"] in ("method", "function") and "." in d["qname"]:
                cfqn = class_fqn_by_q.get(d["qname"].rsplit(".", 1)[0])
                if cfqn:
                    classes[cfqn]["methods"][d["name"]] = qmap[d["qname"]]
        file_defs[(sf.repo, sf.path)] = local
        for c in info["calls"]:
            call_freq[c["callee"]] = call_freq.get(c["callee"], 0) + 1
        if info["calls"]:
            pending.append((sf, ns, info["imports"], info["calls"], qmap, class_fqn_by_q))

    blocked = {nm for nm, ids in by_name.items() if len(ids) > max_name_fanout}
    blocked |= {nm for nm, f in call_freq.items() if f > max_call_freq}

    def resolve_class(name: str, ns: str, imports: dict, lang: str) -> str | None:
        """FQN d'une classe `name` visible depuis (`ns`, `imports`), MÊME LANGAGE que l'appel
        (le registre est multi-langage : un `new Date()` JS ne doit pas viser une classe PHP)."""
        if not name:
            return None
        def ok(cfqn):
            return cfqn in classes and classes[cfqn]["lang"] == lang
        spec = imports.get(name)
        if spec and "fqn" in spec and ok(spec["fqn"]):
            return spec["fqn"]
        if ok(_fqn(ns, name)):
            return _fqn(ns, name)
        if ok(name):
            return name
        cand = [c for c in classes if classes[c]["lang"] == lang
                and c.rsplit("\\", 1)[-1].rsplit(".", 1)[-1] == name]
        return cand[0] if len(cand) == 1 else None

    def method_in_hierarchy(cfqn: str | None, meth: str, seen=None) -> str | None:
        seen = seen or set()
        if not cfqn or cfqn in seen or cfqn not in classes:
            return None
        seen.add(cfqn)
        cl = classes[cfqn]
        if meth in cl["methods"]:
            return cl["methods"][meth]
        for b in cl["bases"]:
            bf = resolve_class(b, cl.get("ns", ""), cl.get("imports", {}), cl["lang"])
            r = method_in_hierarchy(bf, meth, seen) if bf else None
            if r:
                return r
        return None

    out: dict[str, dict[str, float]] = {}

    def add_edge(src_id: str, tid: str | None, conf: float) -> bool:
        if tid and tid != src_id:
            d = out.setdefault(src_id, {})
            d[tid] = max(d.get(tid, 0.0), conf)
            return True
        return False

    def _same_lang(ids, lang):
        return [i for i in ids if nodes[i]["lang"] == lang]

    for sf, ns, imports, calls, qmap, class_fqn_by_q in pending:
        module_id: str | None = None
        clang = sf.lang
        for c in calls:
            callee, rkind, rclass = c["callee"], c["rkind"], c["rclass"]
            caller_q = c["caller"]
            if caller_q and caller_q in qmap:
                src_id = qmap[caller_q]
            elif caller_q and any(caller_q == q or caller_q.startswith(q + ".") for q in qmap):
                src_id = next(qmap[q] for q in qmap
                              if caller_q == q or caller_q.startswith(q + "."))
            else:
                if module_id is None:
                    module_id = _node_id(sf.repo, sf.path, 1, MODULE_QNAME)
                    nodes.setdefault(module_id, {
                        "name": MODULE_QNAME, "qname": MODULE_QNAME, "repo": sf.repo,
                        "path": sf.path, "lang": sf.lang, "kind": "module",
                        "start_line": 1, "end_line": 1})
                src_id = module_id

            cur_class = class_fqn_by_q.get(c["class"], "")
            if rkind in ("this", "self"):
                if add_edge(src_id, method_in_hierarchy(cur_class, callee), C_HIER):
                    continue
            elif rkind == "parent":
                done = False
                for b in classes.get(cur_class, {}).get("bases", []):
                    bf = resolve_class(b, ns, imports, clang)
                    if bf and add_edge(src_id, method_in_hierarchy(bf, callee), C_HIER):
                        done = True
                        break
                if done:
                    continue
            elif rkind in ("static", "new"):
                cf = resolve_class(rclass, ns, imports, clang)
                if cf:
                    tid = (method_in_hierarchy(cf, "__construct") or classes[cf]["id"]
                           if rkind == "new" else method_in_hierarchy(cf, callee))
                    if add_edge(src_id, tid, C_STATIC):
                        continue

            # fonction libre / membre inconnu → import / namespace / fichier / nom
            if rkind == "free" and callee in imports:
                spec = imports[callee]
                fq = _same_lang(by_fqn.get(spec.get("fqn", ""), []), clang)
                if len(fq) == 1:
                    add_edge(src_id, fq[0], C_IMPORT)
                    continue
                if spec.get("rel"):
                    tgt = _lookup_rel(file_defs, sf.repo, spec["rel"], spec.get("name", callee))
                    if tgt and add_edge(src_id, tgt, C_IMPORT):
                        continue
            # même fichier (locality forte) : on résout même un nom ubiquitaire local
            same = file_defs.get((sf.repo, sf.path), {}).get(callee)
            if same and len(same) == 1:
                add_edge(src_id, same[0], C_SAMENS)
                continue
            # nom ubiquitaire (primitive du langage) ou trop défini → on s'arrête AVANT la
            # résolution globale par nom (sinon une fonction interne homonyme d'un builtin,
            # ex. `range`, absorberait tous les appels du builtin via le FQN unique).
            if callee in blocked:
                continue
            ns_ids = _same_lang(by_fqn.get(_fqn(ns, callee), []), clang) if rkind == "free" else []
            if len(ns_ids) == 1:
                add_edge(src_id, ns_ids[0], C_SAMENS)
                continue
            cand = _same_lang(by_name.get(callee, []), clang)
            if not cand:
                continue
            if len(cand) == 1:
                add_edge(src_id, cand[0], C_UNIQUE if rkind == "free" else C_MEMBER1)
            else:
                for tid2 in cand:
                    add_edge(src_id, tid2, C_AMBIG)

    out_lists = {s: list(d.items()) for s, d in out.items()}
    fan_in: dict[str, int] = {}
    for d in out.values():
        for t in d:
            fan_in[t] = fan_in.get(t, 0) + 1
    centrality = _pagerank(nodes, out_lists)
    for nid, node in nodes.items():
        node["fan_in"] = fan_in.get(nid, 0)
        node["centrality"] = round(centrality.get(nid, 0.0), 7)

    return {
        "version": GRAPH_VERSION,
        "nodes": nodes,
        "by_name": by_name,
        "by_fqn": by_fqn,
        "out": {s: [[t, round(c, 2)] for t, c in d.items()] for s, d in out.items()},
    }


def _lookup_rel(file_defs: dict, repo: str, rel: str, name: str) -> str | None:
    rel = rel.lstrip("/")
    for ext in (".py", ".ts", ".tsx", ".js", ".jsx", "/__init__.py", "/index.ts", "/index.js"):
        cand = file_defs.get((repo, rel + ext))
        if cand and name in cand and len(cand[name]) == 1:
            return cand[name][0]
    return None


def _pagerank(nodes: dict, out_lists: dict, d: float = 0.85, iters: int = 20) -> dict:
    """PageRank pondéré par la confiance des arêtes (importance structurelle d'un symbole)."""
    n = len(nodes)
    if not n:
        return {}
    pr = {k: 1.0 / n for k in nodes}
    wsum = {s: (sum(c for _, c in lst) or 1.0) for s, lst in out_lists.items()}
    base = (1.0 - d) / n
    dangling_keys = [k for k in nodes if k not in out_lists]
    for _ in range(iters):
        nxt = {k: base for k in nodes}
        dshare = d * sum(pr[k] for k in dangling_keys) / n
        for s, lst in out_lists.items():
            ps = pr[s] * d / wsum[s]
            for t, c in lst:
                if t in nxt:
                    nxt[t] += ps * c
        for k in nodes:
            nxt[k] += dshare
        pr = nxt
    return pr


def _iter_supported(manifest: dict, base_dir: Path, repos: list[str] | None,
                    max_file_bytes: int) -> Iterator[tuple[walk.SourceFile, str]]:
    """Fichiers PHP/Py/TS/JS, texte décodé, hors minifiés/bundles."""
    for sf in walk.iter_files(manifest, base_dir, repos=repos, max_file_bytes=max_file_bytes):
        if sf.lang not in _TS_LANG:
            continue
        try:
            text = sf.abspath.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if text.strip() and not _is_minified(sf.path, text):
            yield sf, text


def _is_minified(path: str, text: str) -> bool:
    low = path.lower()
    if any(m in low for m in (".min.", "-min.", ".bundle.")):
        return True
    if {"vendor", "dist", "node_modules"} & set(low.split("/")):
        return True
    return any(len(ln) > 2000 for ln in text.split("\n", 50)[:50])


# ── Requête : code_impact ──────────────────────────────────────────────────────

def load_graph(path: str | Path) -> dict:
    """Charge un graphe (.json/.json.gz) et calcule l'index inverse `in` (avec confiance)."""
    p = Path(path)
    raw = (gzip.decompress(p.read_bytes()).decode("utf-8") if p.suffix == ".gz"
           else p.read_text(encoding="utf-8"))
    g = json.loads(raw)
    g["in"] = _reverse(g.get("out", {}))
    return g


def _reverse(out: dict) -> dict:
    rev: dict[str, list] = {}
    for s, lst in out.items():
        for t, c in lst:
            rev.setdefault(t, []).append([s, c])
    return rev


def resolve_symbol(graph: dict, symbol: str) -> list[str]:
    """Nœuds correspondant à `symbol` : nom exact, FQN, suffixe de qname, ou chemin:ligne."""
    s = symbol.strip()
    if not s:
        return []
    nodes = graph.get("nodes", {})
    hits = list(graph.get("by_name", {}).get(s, []))
    if hits:
        return hits
    if s in graph.get("by_fqn", {}):
        return list(graph["by_fqn"][s])
    if ":" in s:
        head = s.rsplit(":", 1)
        if head[1].isdigit():
            ln = int(head[1])
            hits = [nid for nid, n in nodes.items()
                    if n["path"].endswith(head[0]) and n["start_line"] == ln]
            if hits:
                return hits
    sl = s.lower()
    return [nid for nid, n in nodes.items()
            if n["qname"].lower() == sl or n["qname"].lower().endswith("." + sl)]


_CODE_EXT = (".php", ".py", ".ts", ".tsx", ".js", ".jsx")


def _looks_like_path(s: str) -> bool:
    return "/" in s or s.endswith(_CODE_EXT)


def resolve_file(graph: dict, path: str) -> list[str]:
    """Nœuds (hors module) définis dans le(s) fichier(s) dont le chemin se termine par `path`."""
    pat = path.strip().lstrip("/")
    return [nid for nid, n in graph.get("nodes", {}).items()
            if n["kind"] != "module" and n["path"].endswith(pat)]


def _subsystem(node: dict) -> str:
    seg = node["path"].split("/", 1)[0]
    return f"{node['repo']}/{seg}" if seg else node["repo"]


def _tier(conf: float) -> str:
    return ("certain" if conf >= TIER_CERTAIN
            else "probable" if conf >= TIER_PROBABLE else "incertain")


def _describe(node: dict, depth: int, conf: float, sidecar: dict | None) -> dict:
    url = (chunk_url(sidecar, node["repo"], node["path"],
                     node["start_line"], node["end_line"]) if sidecar else "")
    return {"qname": node["qname"], "kind": node["kind"], "repo": node["repo"],
            "path": node["path"], "lang": node["lang"], "start_line": node["start_line"],
            "end_line": node["end_line"], "depth": depth, "source_url": url,
            "confidence": round(conf, 2), "tier": _tier(conf), "subsystem": _subsystem(node),
            "centrality": node.get("centrality", 0.0), "fan_in": node.get("fan_in", 0)}


def code_impact(graph: dict, symbol: str, *, direction: str = "callers", depth: int = 2,
                max_nodes: int = 40, min_confidence: float = 0.0,
                sidecar: dict | None = None) -> dict:
    """BFS borné depuis `symbol`. direction=callers (impact) | callees (deps).

    Certitude d'un nœud = **min des confiances** sur le meilleur chemin l'atteignant ;
    résultats triés (certitude, centralité), groupés par sous-système."""
    if "in" not in graph:
        graph = {**graph, "in": _reverse(graph.get("out", {}))}
    edges = graph["in"] if direction == "callers" else graph.get("out", {})
    nodes = graph.get("nodes", {})
    roots = resolve_symbol(graph, symbol)
    # Mode FICHIER : un chemin → tous les symboles du fichier comme graines (« qu'est-ce qui
    # casse si je supprime ce fichier »). Tenté seulement si le symbole ressemble à un chemin
    # et qu'aucun symbole exact ne correspond.
    scope = "symbol"
    if not roots and _looks_like_path(symbol):
        roots = resolve_file(graph, symbol)
        scope = "file"

    seeds = set(roots)
    for r in roots:
        n = nodes.get(r)
        if n and n["kind"] in _CLASS_KINDS:
            pref = n["qname"] + "."
            seeds.update(nid for nid, nn in nodes.items()
                         if nn["repo"] == n["repo"] and nn["path"] == n["path"]
                         and nn["qname"].startswith(pref))

    best: dict[str, tuple[int, float]] = {s: (0, 1.0) for s in seeds}
    order: list[str] = []
    frontier = list(seeds)
    d = 0
    while frontier and d < depth:
        d += 1
        nxt: list[str] = []
        for nid in frontier:
            pconf = best[nid][1]
            for tgt, c in edges.get(nid, []):
                if c < min_confidence:
                    continue
                path_conf = min(pconf, c)
                if tgt not in best:
                    best[tgt] = (d, path_conf)
                    nxt.append(tgt)
                    order.append(tgt)
                elif path_conf > best[tgt][1]:
                    best[tgt] = (best[tgt][0], path_conf)
        frontier = nxt

    impacted = [_describe(nodes[i], best[i][0], best[i][1], sidecar)
                for i in order if i in nodes]
    impacted.sort(key=lambda x: ({"certain": 0, "probable": 1, "incertain": 2}[x["tier"]],
                                 -x["centrality"]))
    truncated = len(impacted) > max_nodes
    impacted = impacted[:max_nodes]
    by_sub: dict[str, int] = {}
    tiers = {"certain": 0, "probable": 0, "incertain": 0}
    for x in impacted:
        by_sub[x["subsystem"]] = by_sub.get(x["subsystem"], 0) + 1
        tiers[x["tier"]] += 1
    files = sorted({f"{nodes[r]['repo']}/{nodes[r]['path']}" for r in roots if r in nodes})
    return {
        "symbol": symbol, "direction": direction, "depth": depth, "scope": scope,
        "roots": [_describe(nodes[r], 0, 1.0, sidecar) for r in roots if r in nodes],
        "files": files if scope == "file" else [],
        "ambiguous": (len(files) > 1) if scope == "file" else (len(roots) > 1),
        "impacted": impacted, "truncated": truncated,
        "by_subsystem": dict(sorted(by_sub.items(), key=lambda kv: -kv[1])),
        "tiers": tiers,
    }


def code_hotspots(graph: dict, *, top: int = 20, repo: str | None = None,
                  subsystem: str | None = None, lang: str | None = None,
                  by: str = "centrality", sidecar: dict | None = None) -> dict:
    """Symboles les plus structurellement importants (« hubs ») : top-N par centralité
    PageRank (défaut) ou fan-in (nb d'appelants), filtrables par repo/sous-système/langage.
    Les nœuds module sont exclus."""
    metric = "fan_in" if by == "fan_in" else "centrality"
    items = [n for n in graph.get("nodes", {}).values() if n["kind"] != "module"]
    if repo:
        items = [n for n in items if n["repo"] == repo]
    if lang:
        items = [n for n in items if n["lang"] == lang]
    if subsystem:
        items = [n for n in items if _subsystem(n) == subsystem]
    items.sort(key=lambda n: (n.get(metric, 0), n.get("fan_in", 0)), reverse=True)
    hot = []
    for n in items[:max(1, top)]:
        d = _describe(n, 0, 1.0, sidecar)
        d["metric"] = n.get(metric, 0)
        hot.append(d)
    return {"by": metric, "repo": repo, "subsystem": subsystem, "lang": lang, "hotspots": hot}


# ── Requête : shortest_path ─────────────────────────────────────────────────────

_DEAD_EXCLUDE_KINDS = _CLASS_KINDS | {"module"}


def _bfs_path(out: dict, srcs: set[str], dsts: set[str], max_depth: int
              ) -> tuple[list[str], float] | None:
    """Plus court chemin (en nb d'arêtes) d'une graine `srcs` vers une graine `dsts` dans
    `out`. Départage : à longueur égale, on garde le chemin dont la confiance MINIMALE le long
    du chemin est la plus haute. Renvoie (liste de nids, min_confidence) ou None.

    BFS par couches : on explore couche par couche (toutes à la même distance) ; dès qu'une
    couche contient une cible on s'arrête (longueur minimale garantie). Pour chaque nœud on
    mémorise le meilleur (min-conf) prédécesseur à cette distance."""
    if srcs & dsts:                       # src == dst (ou recouvrement) : chemin trivial
        nid = next(iter(srcs & dsts))
        return [nid], 1.0
    # best[nid] = (min_conf du meilleur chemin jusqu'ici, prédécesseur) à la distance courante.
    best: dict[str, tuple[float, str | None]] = {s: (1.0, None) for s in srcs}
    frontier = set(srcs)
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        nxt: dict[str, tuple[float, str | None]] = {}
        for nid in frontier:
            pconf = best[nid][0]
            for tgt, c in out.get(nid, []):
                if tgt in best:           # déjà atteint plus tôt (distance ≤) → ne pas régresser
                    continue
                path_conf = min(pconf, c)
                if tgt not in nxt or path_conf > nxt[tgt][0]:
                    nxt[tgt] = (path_conf, nid)
        if not nxt:
            break
        # cibles atteintes à cette couche : on prend celle de meilleure confiance minimale.
        reached = [t for t in nxt if t in dsts]
        if reached:
            best.update(nxt)
            tgt = max(reached, key=lambda t: nxt[t][0])
            path = [tgt]
            while best[path[-1]][1] is not None:
                path.append(best[path[-1]][1])
            path.reverse()
            return path, best[tgt][0]
        best.update(nxt)
        frontier = set(nxt)
    return None


def shortest_path(graph: dict, src: str, dst: str, *, max_depth: int = 8,
                  sidecar: dict | None = None) -> dict:
    """Plus court chemin d'appel entre deux symboles dans le graphe de code.

    BFS sur `graph["out"]` depuis n'importe quelle racine de `src` vers n'importe quelle racine
    de `dst`. Départage à longueur égale : confiance MINIMALE la plus haute (chemin le plus
    sûr). Si aucun chemin src→dst sous `max_depth`, on tente dst→src et on le signale via
    `direction`. Chaque nœud du chemin porte la confiance de son arête entrante."""
    nodes = graph.get("nodes", {})
    out = graph.get("out", {})
    src_roots = resolve_symbol(graph, src)
    dst_roots = resolve_symbol(graph, dst)
    base = {"found": False, "path": [], "min_confidence": 0.0,
            "src_roots": src_roots, "dst_roots": dst_roots, "direction": None}
    if not src_roots or not dst_roots:
        return base

    def _render(path: list[str], min_conf: float, direction: str) -> dict:
        # confiance de l'arête ENTRANTE de chaque nœud (1.0 pour la racine) ; en sens inverse
        # le chemin reste exprimé src→…→dst pour la lisibilité, mais les arêtes sont celles
        # parcourues (dst→src dans `out`).
        confs = [1.0]
        for i in range(1, len(path)):
            edge = dict(out.get(path[i - 1], []))
            confs.append(edge.get(path[i], 0.0))
        rendered = [_describe(nodes[n], i, confs[i], sidecar)
                    for i, n in enumerate(path) if n in nodes]
        return {"found": True, "path": rendered, "min_confidence": round(min_conf, 2),
                "src_roots": src_roots, "dst_roots": dst_roots, "direction": direction}

    fwd = _bfs_path(out, set(src_roots), set(dst_roots), max_depth)
    if fwd is not None:
        return _render(fwd[0], fwd[1], "src->dst")
    rev = _bfs_path(out, set(dst_roots), set(src_roots), max_depth)
    if rev is not None:
        return _render(rev[0], rev[1], "dst->src")
    return base


# ── Requête : dead_symbols ──────────────────────────────────────────────────────

_DEAD_CAVEAT = ("attention : les points d'entrée (routes, mains de cron, hooks, callbacks de "
                "framework) ont légitimement 0 appelant intra-projet sous résolution statique "
                "et ne doivent pas être supprimés à l'aveugle.")


def dead_symbols(graph: dict, *, repo: str | None = None, subsystem: str | None = None,
                 top: int = 30, sidecar: dict | None = None) -> dict:
    """Symboles à fan-in nul (« code potentiellement mort ») : fonctions/méthodes jamais
    appelées dans le graphe. Exclut classes/interfaces/traits/enums et nœuds module (un type
    sans appelant n'est pas du code mort au même titre qu'une fonction). Filtrable par
    repo/sous-système. Tri repo→path→ligne, plafonné à `top`. Voir `caveat` : les points
    d'entrée ont légitimement 0 appelant."""
    items = [n for n in graph.get("nodes", {}).values()
             if n.get("fan_in", 0) == 0
             and n["kind"] not in _DEAD_EXCLUDE_KINDS
             and n["qname"] != MODULE_QNAME]
    if repo:
        items = [n for n in items if n["repo"] == repo]
    if subsystem:
        items = [n for n in items if _subsystem(n) == subsystem]
    items.sort(key=lambda n: (n["repo"], n["path"], n["start_line"]))
    truncated = len(items) > top
    symbols = [_describe(n, 0, 1.0, sidecar) for n in items[:max(0, top)]]
    return {"count": len(symbols), "truncated": truncated, "symbols": symbols,
            "caveat": _DEAD_CAVEAT}


# ── CLI ─────────────────────────────────────────────────────────────────────────

def _cmd_build(args: argparse.Namespace) -> int:
    from .config import load_config, load_manifest
    cfg = load_config()
    base = args.base_dir or cfg.base_dir
    manifest = load_manifest(args.manifest)
    g = build_graph(_iter_supported(manifest, base, args.repos, cfg.max_file_bytes),
                    max_name_fanout=args.max_fanout)
    n_edges = sum(len(v) for v in g["out"].values())
    strong = sum(1 for v in g["out"].values() for _, c in v if c >= STRONG)
    out_path = Path(args.out)
    data = json.dumps(g, ensure_ascii=False)
    if out_path.suffix == ".gz":
        out_path.write_bytes(gzip.compress(data.encode("utf-8")))
    else:
        out_path.write_text(data, encoding="utf-8")
    print(f"Graphe v2 écrit : {out_path} — {len(g['nodes'])} nœuds, {n_edges} arêtes "
          f"({strong} fortes ≥{STRONG}), {len(g['by_fqn'])} FQN.")
    return 0


def _cmd_impact(args: argparse.Namespace) -> int:
    graph = load_graph(args.graph)
    sidecar = json.loads(Path(args.meta).read_text(encoding="utf-8")) if args.meta else None
    res = code_impact(graph, args.symbol, direction=args.direction, depth=args.depth,
                      sidecar=sidecar)
    if not res["roots"]:
        print(f"Symbole/fichier introuvable : {args.symbol}", file=sys.stderr)
        return 1
    verb = "appelé par" if args.direction == "callers" else "dépend de"
    t = res["tiers"]
    scope = " [fichier]" if res.get("scope") == "file" else ""
    print(f"# {args.symbol}{scope} — {verb} (prof {args.depth}) — "
          f"{t['certain']} certains / {t['probable']} probables / {t['incertain']} incertains")
    if res.get("scope") == "file":
        print(f"  fichier(s) : {', '.join(res['files'])} ({len(res['roots'])} symboles)")
    elif res["ambiguous"]:
        print(f"  ⚠ {len(res['roots'])} définitions portent ce nom.")
    if res["by_subsystem"]:
        print("  sous-systèmes : " + ", ".join(f"{k} ({v})" for k, v in res["by_subsystem"].items()))
    for n in res["impacted"]:
        url = f"  {n['source_url']}" if n["source_url"] else ""
        print(f"  [{n['tier']}] {n['qname']} ({n['kind']}) "
              f"{n['repo']}/{n['path']}:{n['start_line']}{url}")
    if res["truncated"]:
        print("  … (tronqué)")
    return 0


def _cmd_path(args: argparse.Namespace) -> int:
    graph = load_graph(args.graph)
    sidecar = json.loads(Path(args.meta).read_text(encoding="utf-8")) if args.meta else None
    res = shortest_path(graph, args.src, args.dst, max_depth=args.max_depth, sidecar=sidecar)
    if not res["src_roots"] or not res["dst_roots"]:
        miss = args.src if not res["src_roots"] else args.dst
        print(f"Symbole introuvable : {miss}", file=sys.stderr)
        return 1
    if not res["found"]:
        print(f"# Aucun chemin d'appel entre {args.src} et {args.dst} (prof ≤ {args.max_depth}).")
        return 1
    arrow = "→" if res["direction"] == "src->dst" else "← (sens inverse)"
    print(f"# {args.src} {arrow} {args.dst} — {len(res['path'])} nœuds, "
          f"confiance min {res['min_confidence']}")
    for n in res["path"]:
        url = f"  {n['source_url']}" if n["source_url"] else ""
        print(f"  [{n['tier']}] {n['qname']} ({n['kind']}) "
              f"{n['repo']}/{n['path']}:{n['start_line']}{url}")
    return 0


def _cmd_dead(args: argparse.Namespace) -> int:
    graph = load_graph(args.graph)
    sidecar = json.loads(Path(args.meta).read_text(encoding="utf-8")) if args.meta else None
    res = dead_symbols(graph, repo=args.repo, subsystem=args.subsystem, top=args.top,
                       sidecar=sidecar)
    print(f"# Symboles à fan-in nul (code potentiellement mort) — {res['count']} affichés"
          + (f", repo={args.repo}" if args.repo else "")
          + (f", {args.subsystem}" if args.subsystem else "")
          + (" — tronqué" if res["truncated"] else ""))
    print(f"  ⚠ {res['caveat']}")
    for n in res["symbols"]:
        url = f"  {n['source_url']}" if n["source_url"] else ""
        print(f"  {n['qname']} ({n['kind']}) {n['repo']}/{n['path']}:{n['start_line']}{url}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Graphe d'appels du code Infoclimat (tree-sitter).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Construire l'artefact graphe (JSON).")
    b.add_argument("--out", required=True)
    b.add_argument("--base-dir", type=Path, default=None)
    b.add_argument("--manifest", type=Path, default=None)
    b.add_argument("--repo", action="append", dest="repos", default=None)
    b.add_argument("--max-fanout", type=int, default=6)
    b.set_defaults(func=_cmd_build)
    q = sub.add_parser("impact", help="Rayon d'impact / dépendances d'un symbole ou fichier.")
    q.add_argument("symbol", help="Nom de symbole (Classe.methode) OU chemin de fichier.")
    q.add_argument("--graph", required=True)
    q.add_argument("--direction", choices=["callers", "callees"], default="callers")
    q.add_argument("--depth", type=int, default=2)
    q.add_argument("--meta", default=None)
    q.set_defaults(func=_cmd_impact)

    h = sub.add_parser("hotspots", help="Symboles les plus centraux (hubs) du code.")
    h.add_argument("--graph", required=True)
    h.add_argument("--top", type=int, default=20)
    h.add_argument("--repo", default=None)
    h.add_argument("--subsystem", default=None)
    h.add_argument("--lang", default=None)
    h.add_argument("--by", choices=["centrality", "fan_in"], default="centrality")
    h.add_argument("--meta", default=None)
    h.set_defaults(func=_cmd_hotspots)

    p = sub.add_parser("path", help="Plus court chemin d'appel entre deux symboles.")
    p.add_argument("src", help="Symbole de départ (Classe.methode).")
    p.add_argument("dst", help="Symbole d'arrivée (Classe.methode).")
    p.add_argument("--graph", required=True)
    p.add_argument("--max-depth", type=int, default=8)
    p.add_argument("--meta", default=None)
    p.set_defaults(func=_cmd_path)

    d = sub.add_parser("dead", help="Symboles à fan-in nul (code potentiellement mort).")
    d.add_argument("--graph", required=True)
    d.add_argument("--top", type=int, default=30)
    d.add_argument("--repo", default=None)
    d.add_argument("--subsystem", default=None)
    d.add_argument("--meta", default=None)
    d.set_defaults(func=_cmd_dead)

    args = ap.parse_args(argv)
    return args.func(args)


def _cmd_hotspots(args: argparse.Namespace) -> int:
    graph = load_graph(args.graph)
    sidecar = json.loads(Path(args.meta).read_text(encoding="utf-8")) if args.meta else None
    res = code_hotspots(graph, top=args.top, repo=args.repo, subsystem=args.subsystem,
                        lang=args.lang, by=args.by, sidecar=sidecar)
    print(f"# Hubs du code (par {res['by']}"
          + (f", repo={args.repo}" if args.repo else "")
          + (f", {args.subsystem}" if args.subsystem else "") + ")")
    for n in res["hotspots"]:
        url = f"  {n['source_url']}" if n["source_url"] else ""
        m = n["metric"]
        mstr = f"{m:.5f}" if isinstance(m, float) else str(m)
        print(f"  {mstr:>9}  {n['qname']} ({n['kind']}) "
              f"{n['repo']}/{n['path']}:{n['start_line']}{url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
