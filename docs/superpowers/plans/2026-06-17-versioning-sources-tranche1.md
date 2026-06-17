# Versioning des sources externes — Tranche 1 (fondation A + tool-vue) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer le catalogue Météo-France du bot (dict codé en dur) en une **vue** qui lit des contrats ODCS versionnés de data-platform, et rendre répondable « qu'a changé sur cette source et quand » via un historique de changelog.

**Architecture:** Chaque source MF devient un contrat ODCS (`tags: [source, meteofrance, api]`) portant le schéma brut (champs + unités), les quirks en `customProperties.externalSource`, et un `customProperties.changelog`. Le module `meteofrance_catalog.py` du bot perd son dict `CATALOG` et charge à la place ces contrats depuis la racine du snapshot data-platform (`ToolBox.root/contracts/`). Les fonctions de rendu existantes (`render_contract`, `render_schema`, `interpret`, `render_probe`) sont conservées en opérant sur des « entrées » normalisées produites par un adaptateur ODCS→entrée ; on ajoute `render_changes`.

**Tech Stack:** Python 3.x, PyYAML (déjà dépendance), pytest. Deux repos : `ic-data-bot` (le tool) et `data-platform` (les contrats).

**Périmètre :** Tranche 1 uniquement. Pas de détection Kestra (C1) ni de test CI sur sample figé (C3) — ce sont les tranches 2 et 3, plans séparés. Ici : modèle de données versionné + vue + answerability de l'historique (historique saisi à la main au départ).

**Précision vs ADR-0002 :** la tranche 1 migre **les 11 entrées** actuelles du dict (DPObs, DPPaquetObs, DPRadar, DPPaquetRadar, AROME-WCS, AROME-Paquets, AROME-OM, ARPEGE-Paquets, AROMEPI, PIAF, climato-data-gouv), pas seulement 2-3 : laisser des entrées dans le dict ferait régresser la couverture du bot. `AUTH` et `ERROR_TAXONOMY` (savoir transverse, pas par-source) restent des constantes du module — ils ne relèvent pas du versioning de schéma.

---

## Structure de fichiers

**ic-data-bot :**
- Modifier (réécriture) : `src/ic_data_bot/meteofrance_catalog.py` — devient une vue : constantes transverses + loader ODCS + adaptateur + rendus (dont `render_changes`). Le dict `CATALOG` et `_BY_ID` disparaissent.
- Modifier : `src/ic_data_bot/tools.py` — `ToolBox.meteofrance_catalog()` passe `self.root` aux fonctions ; entrée `SCHEMAS` (ajout `topic="changes"` + paramètre `since`) ; `_dispatch` propage `since`.
- Modifier (réécriture) : `tests/test_meteofrance_catalog.py` — sème des contrats synthétiques dans `tmp_path/contracts/` (le bot ne dépend pas du clone data-platform pour ses tests unitaires) ; ajoute les tests de `topic="changes"`.

**data-platform :**
- Créer : `contracts/source-meteofrance-dpobs.odcs.yaml` (contrat de référence, riche, avec changelog).
- Créer : `contracts/source-meteofrance-climato-data-gouv.odcs.yaml` (variante open-data, `auth: none`, unités conventionnelles).
- Créer (×9) : `contracts/source-meteofrance-<id>.odcs.yaml` pour les 9 sources restantes (transcription mécanique du dict via la table de correspondance de la Task 4).

---

## Task 1 : Réécrire `meteofrance_catalog.py` en vue sur contrats ODCS

**Files:**
- Modify (réécriture complète) : `src/ic_data_bot/meteofrance_catalog.py`
- Test : `tests/test_meteofrance_catalog.py` (réécrit en Task 1 même, pour rester vert)

- [ ] **Step 1 : Récupérer le dict actuel pour référence de transcription (Tasks 4) avant de le supprimer**

Run :
```bash
cd ~/PycharmProjects/infoclimat/ic-data-bot
git show HEAD:src/ic_data_bot/meteofrance_catalog.py > /tmp/catalog_dict_reference.py
```
Le fichier `/tmp/catalog_dict_reference.py` contient les 11 entrées `CATALOG` — source de vérité pour écrire les contrats (Tasks 3-4).

- [ ] **Step 2 : Écrire les tests qui échouent (vue sur contrats semés)**

Remplacer **tout** le contenu de `tests/test_meteofrance_catalog.py` par :

```python
import textwrap
import pytest

from ic_data_bot.tools import ToolBox, ToolError
from ic_data_bot import meteofrance_catalog as cat


def _write(root, fname, body):
    d = root / "contracts"
    d.mkdir(exist_ok=True)
    (d / fname).write_text(textwrap.dedent(body), encoding="utf-8")


def _seed(root):
    """Sème des contrats ODCS de source réalistes mais minimaux dans root/contracts/."""
    _write(root, "source-meteofrance-dpobs.odcs.yaml", """
        apiVersion: v3.0.2
        kind: DataContract
        id: urn:infoclimat:contract:source-meteofrance-dpobs
        name: Source Météo-France — Observations stations (DPObs)
        version: 2.0.0
        status: active
        domain: observations
        tags: [source, meteofrance, api]
        schema:
          - name: station-observation
            physicalType: object
            properties:
              - name: geo_id_insee
                physicalType: TEXT
                unit: ddnnnpp
                description: ID point
              - name: ff
                physicalType: REAL
                unit: m/s
                description: vent moyen à 10 m
              - name: t
                physicalType: REAL
                unit: K (Kelvin)
                description: température sous abri (SI brut)
        customProperties:
          - property: externalSource
            value:
              apiId: DPObs
              host: public-api.meteofrance.fr
              context: /public/DPObs/v1
              urlTemplate: /public/DPObs/v1/station/horaire?id_station={id}&format=json
              auth: token
              probeUrl: https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations
              verified: "verifie en live"
              unitsNote: "Unites SI BRUTES dans la reponse API : temperature en KELVIN, pression en PASCAL."
              quirks:
                - Stations RADOME, 24 dernieres heures.
          - property: changelog
            value:
              - version: "2.0.0"
                date: "2026-05-12"
                type: rename
                severity: breaking
                fields: [ff, fxi10]
                note: "Passage v2 vent : ff renomme, rafale fxi10 -> fxi."
              - version: "1.0.0"
                date: "2026-06-17"
                type: initial
                severity: non-breaking
                fields: []
                note: "Transcription du dict (etat v1)."
    """)
    _write(root, "source-meteofrance-climato.odcs.yaml", """
        apiVersion: v3.0.2
        kind: DataContract
        id: urn:infoclimat:contract:source-meteofrance-climato-data-gouv
        name: Source Météo-France — Climatologie data.gouv
        version: 1.0.0
        status: active
        domain: climato
        tags: [source, meteofrance]
        schema:
          - name: poste-horaire
            physicalType: object
            properties:
              - name: T
                physicalType: REAL
                unit: "°C"
                description: température (unité conventionnelle)
        customProperties:
          - property: externalSource
            value:
              apiId: climato-data-gouv
              host: object.files.data.gouv.fr
              context: /meteofrance/data/synchro_ftp/BASE
              urlTemplate: https://object.files.data.gouv.fr/.../{FREQ}.csv.gz
              auth: none
              probeUrl: https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/BASE/HOR/H_descriptif_champs.csv
              verified: open data
              unitsNote: "Unites CONVENTIONNELLES (°C, 1/10)."
              quirks: [Sans auth - Licence Ouverte Etalab 2.0.]
          - property: changelog
            value: []
    """)
    _write(root, "source-meteofrance-piaf.odcs.yaml", """
        apiVersion: v3.0.2
        kind: DataContract
        id: urn:infoclimat:contract:source-meteofrance-piaf
        name: Source Météo-France — PIAF (nowcast precip, commercial)
        version: 1.0.0
        status: active
        domain: modeles
        tags: [source, meteofrance, api]
        schema:
          - name: piaf
            physicalType: object
            properties:
              - name: TOTAL_PRECIPITATION_RATE
                physicalType: GRIB
                unit: kg/m²/s
                description: intensité précip fusionnée
        customProperties:
          - property: externalSource
            value:
              apiId: PIAF
              host: api.meteofrance.fr
              context: /pro/piaf/1.0/wcs
              urlTemplate: /pro/piaf/1.0/wcs/.../GetCoverage
              auth: token
              probeUrl: https://api.meteofrance.fr/pro/piaf/1.0/wcs/x/GetCapabilities
              verified: verifie en live
              quirks: [HOST COMMERCIAL api.meteofrance.fr.]
          - property: changelog
            value: []
    """)
    # Contrat non-source (table persistée) : la vue doit l'IGNORER.
    _write(root, "climato-mf-timescale.odcs.yaml", """
        apiVersion: v3.0.2
        kind: DataContract
        id: urn:infoclimat:contract:climato-mf-timescale
        name: Climato MF persistée
        version: 0.1.0
        status: active
        tags: [timescaledb]
        customProperties: []
    """)


def _box(root, meteofrance=None):
    _seed(root)
    return ToolBox(root, meteofrance=meteofrance)


class _StubMF:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def probe(self, url, *, auth=True, range_probe=True):
        self.calls.append((url, auth))
        return self.result


# ── Vue d'ensemble & contrat ────────────────────────────────────────────────

def test_overview_lists_only_source_contracts(tmp_path):
    out = _box(tmp_path).meteofrance_catalog()
    assert "DPObs" in out
    assert "PIAF" in out
    assert "900908" in out                 # taxonomie d'erreurs (constante)
    assert "persistée" not in out          # le contrat table est ignoré


def test_contract_returns_host_and_context(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="DPObs", topic="contract")
    assert "public-api.meteofrance.fr" in out
    assert "/public/DPObs/v1" in out


def test_piaf_uses_commercial_host(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="piaf")
    assert "api.meteofrance.fr" in out


def test_fuzzy_match_by_context(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="climato")
    assert "data.gouv" in out


def test_unknown_api_is_helpful(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="inexistant")
    assert "inconnue" in out.lower()
    assert "DPObs" in out


# ── Schéma de données ───────────────────────────────────────────────────────

def test_schema_dpobs_has_fields_and_units(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="DPObs", topic="schema")
    assert "geo_id_insee" in out
    assert "Kelvin" in out
    assert "SI BRUTES" in out


# ── Historique (NOUVEAU) ────────────────────────────────────────────────────

def test_changes_lists_versions_breaking(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="DPObs", topic="changes")
    assert "2.0.0" in out
    assert "breaking" in out.lower()
    assert "ff" in out                     # champ impacté listé


def test_changes_empty_is_explicit(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="PIAF", topic="changes")
    assert "aucun changement" in out.lower()


def test_changes_since_filters(tmp_path):
    out = _box(tmp_path).meteofrance_catalog(api="DPObs", topic="changes", since="2026-01-01")
    assert "2.0.0" in out
    out2 = _box(tmp_path).meteofrance_catalog(api="DPObs", topic="changes", since="2026-06-01")
    assert "2.0.0" not in out2             # changement du 2026-05-12 filtré


# ── Probe ───────────────────────────────────────────────────────────────────

def test_probe_without_client_raises(tmp_path):
    with pytest.raises(ToolError):
        _box(tmp_path).meteofrance_catalog(api="DPObs", probe=True)


def test_probe_served(tmp_path):
    stub = _StubMF({"status": 200, "content_type": "application/json", "snippet": "[]"})
    out = _box(tmp_path, meteofrance=stub).meteofrance_catalog(api="DPObs", probe=True)
    assert "servi" in out
    assert stub.calls and stub.calls[0][1] is True


def test_probe_open_data_no_auth(tmp_path):
    stub = _StubMF({"status": 200, "content_type": "text/csv", "snippet": "x"})
    _box(tmp_path, meteofrance=stub).meteofrance_catalog(api="climato-data-gouv", probe=True)
    assert stub.calls and stub.calls[0][1] is False


# ── Interprétation (constante, inchangée) ───────────────────────────────────

def test_interpret_taxonomy():
    assert "servi" in cat.interpret(206, "")
    assert "NoSuchCoverage" in cat.interpret(404, "NoSuchCoverage")
    assert "EXISTE" in cat.interpret(400, "")


def test_dispatch_meteofrance_catalog(tmp_path):
    _seed(tmp_path)
    out = ToolBox(tmp_path).dispatch("meteofrance_catalog", {"api": "DPObs", "topic": "schema"})
    assert "geo_id_insee" in out
```

- [ ] **Step 3 : Lancer les tests pour confirmer l'échec**

Run : `cd ~/PycharmProjects/infoclimat/ic-data-bot && .venv/bin/python -m pytest tests/test_meteofrance_catalog.py -q`
Expected : FAIL (signatures `overview(root)`, `find(root, ...)`, `topic="changes"`, `since` inconnues).

- [ ] **Step 4 : Réécrire `meteofrance_catalog.py`**

Remplacer **tout** le contenu de `src/ic_data_bot/meteofrance_catalog.py` par :

```python
"""Vue Météo-France : rend les contrats ODCS de source (tags [source, meteofrance])
versionnés dans data-platform/contracts/. Plus de catalogue codé en dur — le contrat
fait foi, son customProperties.changelog porte l'historique des changements.

Chargé depuis ToolBox.root (racine du snapshot data-platform). AUTH et ERROR_TAXONOMY
restent des constantes transverses (savoir plateforme, hors versioning de schéma).
"""

from __future__ import annotations

from pathlib import Path

import yaml

AUTH = (
    "Auth OAuth2 unique : POST https://portail-api.meteofrance.fr/token, header "
    "`Authorization: Basic ${METEOFRANCE_APPLICATION_ID}`, body `grant_type=client_credentials` "
    "→ bearer token (TTL ~1 h). Souscriptions PAR APPLICATION. Gateways : "
    "`public-api.meteofrance.fr` (open data) et `api.meteofrance.fr` (commercial, ex. PIAF)."
)

ERROR_TAXONOMY = {
    "200/206": "servi — l'application est abonnée et l'endpoint répond (206 = Range bytes=0-0).",
    "401": "token expiré/invalide → refresh.",
    "403 900908": "l'application porteuse de la clé n'est PAS abonnée à cette API.",
    "404 No matching resource": "mauvais path/context/suffixe produit.",
    "404 NoSuchCoverage": "path OK mais coverageId faux / sur-annoncé / non servi.",
    "400/422": "route connue mais paramètres requis manquants (l'endpoint EXISTE).",
    "405": "méthode non supportée (utiliser GET + Range bytes=0-0).",
}


# ── Chargement des contrats de source ─────────────────────────────────────────

def _custom(doc: dict, key: str):
    for cp in doc.get("customProperties") or []:
        if cp.get("property") == key:
            return cp.get("value")
    return None


def _is_source(doc: dict) -> bool:
    tags = doc.get("tags") or []
    return "source" in tags and "meteofrance" in tags


def _to_entry(doc: dict) -> dict:
    es = _custom(doc, "externalSource") or {}
    schema = doc.get("schema") or []
    props = (schema[0].get("properties") if schema else None) or []
    fields = [
        {
            "name": p.get("name", ""),
            "type": p.get("physicalType") or p.get("logicalType") or "",
            "unit": p.get("unit", ""),
            "desc": p.get("description", ""),
        }
        for p in props
    ]
    return {
        "id": es.get("apiId") or doc.get("name", ""),
        "label": doc.get("name", ""),
        "version": str(doc.get("version", "")),
        "host": es.get("host", ""),
        "context": es.get("context", ""),
        "url_template": es.get("urlTemplate", ""),
        "status": es.get("verified", ""),
        "auth": es.get("auth", "token"),
        "probe": es.get("probeUrl", ""),
        "notes": es.get("quirks") or [],
        "schema": {
            "note": es.get("unitsNote", ""),
            "descriptor": es.get("descriptor", ""),
            "quality": es.get("quality", ""),
            "fields": fields,
        },
        "changelog": _custom(doc, "changelog") or [],
    }


def load_sources(root) -> list[dict]:
    """Charge toutes les entrées de source depuis root/contracts/*.odcs.yaml."""
    d = Path(root) / "contracts"
    entries: list[dict] = []
    if not d.is_dir():
        return entries
    for fp in sorted(d.glob("*.odcs.yaml")):
        try:
            doc = yaml.safe_load(fp.read_text(encoding="utf-8", errors="replace"))
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and _is_source(doc):
            entries.append(_to_entry(doc))
    return entries


def find(root, query: str):
    q = (query or "").strip().lower()
    if not q:
        return None
    entries = load_sources(root)
    for e in entries:           # id exact
        if q == e["id"].lower():
            return e
    for e in entries:           # fragment d'id
        if q in e["id"].lower():
            return e
    for e in entries:           # label / context
        if q in e["label"].lower() or q in e["context"].lower():
            return e
    return None


# ── Rendu ──────────────────────────────────────────────────────────────────

def overview(root) -> str:
    entries = load_sources(root)
    lines = ["# Catalogue des APIs Météo-France\n", AUTH, "", "## Sources versionnées", ""]
    lines += ["| API | Host | Context | Version | Statut |", "|---|---|---|---|---|"]
    for e in entries:
        lines.append(f"| `{e['id']}` | `{e['host']}` | `{e['context']}` | {e['version']} | {e['status']} |")
    if not entries:
        lines.append("| (aucune source chargée) | | | | |")
    lines += ["", "## Taxonomie d'erreurs (interprétation des probes)", ""]
    for code, meaning in ERROR_TAXONOMY.items():
        lines.append(f"- **{code}** : {meaning}")
    lines += [
        "",
        "→ `meteofrance_catalog(api=\"<id>\")` pour le contrat, `topic=\"schema\"` pour les "
        "champs/unités, `topic=\"changes\"` pour l'historique versionné, `probe=true` pour tester.",
    ]
    return "\n".join(lines)


def render_contract(e: dict) -> str:
    lines = [
        f"# {e['label']}  (`{e['id']}`)  — contrat v{e['version']}",
        f"- **Host** : `{e['host']}`",
        f"- **Context** : `{e['context']}`",
        f"- **URL** : `{e['url_template']}`",
        f"- **Statut** : {e['status']}",
        f"- **Auth** : {e['auth']}",
        "",
        "**Quirks / pièges :**",
    ]
    lines += [f"- {n}" for n in e["notes"]] or ["- (aucun)"]
    return "\n".join(lines)


def render_schema(e: dict) -> str:
    sc = e["schema"]
    lines = [f"# Schéma de données — {e['label']}  (`{e['id']}`, contrat v{e['version']})"]
    if sc.get("note"):
        lines += ["", sc["note"]]
    if sc.get("quality"):
        lines += ["", f"**Qualité** : {sc['quality']}"]
    fields = sc.get("fields") or []
    if fields:
        lines += ["", "| Champ | Type | Unité | Description |", "|---|---|---|---|"]
        for f in fields:
            lines.append(f"| `{f['name']}` | {f['type']} | {f['unit']} | {f['desc']} |")
    else:
        lines += ["", "(Pas de schéma tabulaire — cf. descripteur.)"]
    if sc.get("descriptor"):
        lines += ["", f"**Descripteur exhaustif** : {sc['descriptor']}"]
    return "\n".join(lines)


def render_changes(e: dict, since: str | None = None) -> str:
    """Historique versionné depuis customProperties.changelog. `since` = date ISO (incluse).
    Filtre par date (les dates ISO se trient comme des chaînes ; pas de comparaison semver)."""
    cl = list(e.get("changelog") or [])
    if since:
        cl = [c for c in cl if str(c.get("date", "")) >= since]
    if not cl:
        base = f"# Historique — {e['label']}  (`{e['id']}`)"
        if since:
            return base + f"\n\n(Aucun changement enregistré depuis {since}.)"
        return base + "\n\n(Aucun changement enregistré : version courante du contrat.)"
    cl.sort(key=lambda c: str(c.get("date", "")), reverse=True)
    lines = [
        f"# Historique des changements — {e['label']}  (`{e['id']}`)",
        "",
        "| Version | Date | Sévérité | Type | Champs | Note |",
        "|---|---|---|---|---|---|",
    ]
    for c in cl:
        flds = ", ".join(c.get("fields") or []) or "—"
        lines.append(
            f"| {c.get('version', '?')} | {c.get('date', '?')} | **{c.get('severity', '?')}** "
            f"| {c.get('type', '?')} | {flds} | {c.get('note', '')} |"
        )
    return "\n".join(lines)


def not_found(root, query: str) -> str:
    ids = ", ".join(e["id"] for e in load_sources(root)) or "(aucune)"
    return (
        f"API Météo-France inconnue : « {query} ». APIs au catalogue : {ids}. "
        "Appelle `meteofrance_catalog()` sans argument pour la vue d'ensemble."
    )


# ── Probe (disponibilité) — inchangé ──────────────────────────────────────────

def interpret(status: int, snippet: str) -> str:
    s = snippet or ""
    if status in (200, 206):
        return "✅ servi — l'application est abonnée et l'endpoint répond."
    if status == 401:
        return "🔑 401 — token invalide/expiré (refresh nécessaire)."
    if status == 403 and "900908" in s:
        return "⛔ 403 900908 — l'application porteuse de la clé n'est PAS abonnée à cette API."
    if status == 403:
        return "⛔ 403 — accès refusé."
    if status == 404 and "NoSuchCoverage" in s:
        return "❓ 404 NoSuchCoverage — coverageId faux / sur-annoncé / non servi."
    if status == 404 and "indisponible" in s.lower():
        return "❓ 404 — path+format OK mais run/segment non servi."
    if status == 404:
        return "❓ 404 — mauvais path/context/suffixe (No matching resource)."
    if status in (400, 422):
        return f"🟡 {status} — route connue mais paramètres requis manquants (l'endpoint EXISTE)."
    if status == 405:
        return "🟡 405 — méthode non supportée (utiliser GET + Range bytes=0-0)."
    if status == 0:
        return "🌐 injoignable (réseau/DNS)."
    return f"statut {status}."


def render_probe(e: dict, client) -> str:
    url = e["probe"]
    needs_auth = e.get("auth", "token") != "none"
    res = client.probe(url, auth=needs_auth)
    status = res.get("status", 0)
    verdict = interpret(status, res.get("snippet", ""))
    lines = [
        f"# Probe — {e['label']}  (`{e['id']}`)",
        f"- **URL probée** : `{url}`",
        f"- **Statut HTTP** : {status}",
        f"- **Content-Type** : {res.get('content_type') or '—'}",
        f"- **Verdict** : {verdict}",
    ]
    snip = res.get("snippet")
    if snip and status not in (200, 206):
        lines.append(f"- **Corps** : {snip}")
    return "\n".join(lines)
```

- [ ] **Step 5 : Lancer les tests pour confirmer le succès**

Run : `cd ~/PycharmProjects/infoclimat/ic-data-bot && .venv/bin/python -m pytest tests/test_meteofrance_catalog.py -q`
Expected : PASS (tous).

- [ ] **Step 6 : Commit**

```bash
cd ~/PycharmProjects/infoclimat/ic-data-bot
git add src/ic_data_bot/meteofrance_catalog.py tests/test_meteofrance_catalog.py
git commit -m "refactor(meteofrance): le catalogue devient une vue sur contrats ODCS + historique versionné"
```

---

## Task 2 : Câbler la vue dans `ToolBox` + schéma d'outil (`topic=changes`, `since`)

**Files:**
- Modify : `src/ic_data_bot/tools.py` (entrée `SCHEMAS` `meteofrance_catalog`, `ToolBox.meteofrance_catalog`, `_dispatch`)
- Modify : `src/ic_data_bot/mcp_server.py` (docstring + signature du wrapper `@mcp.tool()`)

- [ ] **Step 1 : Écrire le test qui échoue (topic=changes via dispatch)**

Ajouter à la fin de `tests/test_meteofrance_catalog.py` :

```python
def test_dispatch_changes_with_since(tmp_path):
    _seed(tmp_path)
    out = ToolBox(tmp_path).dispatch(
        "meteofrance_catalog", {"api": "DPObs", "topic": "changes", "since": "2026-01-01"}
    )
    assert "2.0.0" in out
    assert "breaking" in out.lower()
```

- [ ] **Step 2 : Lancer pour confirmer l'échec**

Run : `cd ~/PycharmProjects/infoclimat/ic-data-bot && .venv/bin/python -m pytest tests/test_meteofrance_catalog.py::test_dispatch_changes_with_since -q`
Expected : FAIL (`since` non propagé ; `topic=changes` non géré).

- [ ] **Step 3 : Mettre à jour `ToolBox.meteofrance_catalog` dans `tools.py`**

Remplacer la méthode `meteofrance_catalog` (actuellement `tools.py:627-648`) par :

```python
    def meteofrance_catalog(self, api: str = "", topic: str = "contract", probe: bool = False,
                            since: str = "") -> str:
        from . import meteofrance_catalog as cat

        api = (api or "").strip()
        if not api:
            return cat.overview(self.root)
        entry = cat.find(self.root, api)
        if entry is None:
            return cat.not_found(self.root, api)
        if probe:
            if self.meteofrance is None:
                raise ToolError(
                    "Probe Météo-France indisponible : METEOFRANCE_APPLICATION_ID non "
                    "configuré sur ce déploiement (le contrat et le schéma restent consultables)."
                )
            return cat.render_probe(entry, self.meteofrance)
        topic = (topic or "contract").lower()
        if topic == "changes":
            return cat.render_changes(entry, since or None)
        if topic == "schema":
            return cat.render_schema(entry)
        if topic == "all":
            return cat.render_contract(entry) + "\n\n" + cat.render_schema(entry)
        return cat.render_contract(entry)
```

- [ ] **Step 4 : Propager `since` dans `_dispatch` (`tools.py`, branche `meteofrance_catalog`)**

Remplacer le bloc `if name == "meteofrance_catalog":` de `_dispatch` (actuellement `tools.py:675-680`) par :

```python
        if name == "meteofrance_catalog":
            return self.meteofrance_catalog(
                tool_input.get("api") or "",
                tool_input.get("topic") or "contract",
                bool(tool_input.get("probe")),
                tool_input.get("since") or "",
            )
```

- [ ] **Step 5 : Étendre le `SCHEMAS` `meteofrance_catalog` (enum topic + since + description)**

Dans `tools.py`, dans l'entrée `SCHEMAS` dont `"name": "meteofrance_catalog"` : (a) compléter la `description` en ajoutant cette phrase à la fin de la chaîne existante, juste avant la fermeture :
`" topic='changes' renvoie l'HISTORIQUE versionné des changements de schéma de l'API (champs renommés/supprimés, changements d'unité), avec sévérité breaking/non-breaking/deprecated — répond à « qu'est-ce qui a changé sur cette API et quand »."` ;
(b) remplacer la propriété `"topic"` et ajouter `"since"` :

```python
                "topic": {
                    "type": "string",
                    "enum": ["contract", "schema", "changes", "all"],
                    "description": "contract = URL/quirks (défaut) ; schema = champs/unités ; "
                                   "changes = historique versionné ; all = contrat + schéma.",
                },
                "since": {
                    "type": "string",
                    "description": "Avec topic='changes' : ne renvoyer que les changements à partir "
                                   "de cette date ISO (ex. '2026-01-01'). Optionnel.",
                },
```

- [ ] **Step 6 : Mettre le wrapper MCP en cohérence (`mcp_server.py`)**

Remplacer la définition `def meteofrance_catalog(...)` du `@mcp.tool()` (ajoutée à `mcp_server.py` par la branche précédente) par :

```python
@mcp.tool()
def meteofrance_catalog(api: str = "", topic: str = "contract", probe: bool = False,
                        since: str = "") -> str:
    """Catalogue de référence des APIs Météo-France (contrats ODCS versionnés) : contrat d'URL
    (host/context/auth/quirks), SCHÉMA (champs + unités — DPObs en SI brut : Kelvin/Pascal), et
    HISTORIQUE des changements (topic='changes', sévérité breaking/non-breaking/deprecated ;
    `since`=date ISO pour filtrer). `api` vide = vue d'ensemble ; probe nécessite MF_PROBE_ENABLED."""
    return _traced("meteofrance_catalog", {"api": api, "topic": topic, "probe": probe, "since": since},
                   lambda: _safe(_tb.meteofrance_catalog, api, topic, probe, since))
```

- [ ] **Step 7 : Lancer la suite complète**

Run : `cd ~/PycharmProjects/infoclimat/ic-data-bot && .venv/bin/python -m pytest -q`
Expected : PASS (133 + nouveaux tests).

- [ ] **Step 8 : Commit**

```bash
cd ~/PycharmProjects/infoclimat/ic-data-bot
git add src/ic_data_bot/tools.py src/ic_data_bot/mcp_server.py tests/test_meteofrance_catalog.py
git commit -m "feat(meteofrance): expose topic=changes + since (bot + MCP) sur le tool catalogue"
```

---

## Task 3 : Écrire les deux contrats ODCS de référence (data-platform)

**Files:**
- Create : `contracts/source-meteofrance-dpobs.odcs.yaml`
- Create : `contracts/source-meteofrance-climato-data-gouv.odcs.yaml`

- [ ] **Step 1 : Écrire `contracts/source-meteofrance-dpobs.odcs.yaml`**

Transcrire l'entrée `DPObs` de `/tmp/catalog_dict_reference.py` (Task 1 Step 1) dans ce contrat. Tous les champs de `schema.fields` du dict deviennent des `properties` (clé `unit:` conservée). Contenu :

```yaml
apiVersion: v3.0.2
kind: DataContract
id: urn:infoclimat:contract:source-meteofrance-dpobs
name: Source Météo-France — Observations stations (DPObs)
version: 1.0.0
status: active
domain: observations
tags: [source, meteofrance, api]

description:
  purpose: >-
    Contrat de la SOURCE API DPObs (observations stations RADOME, temps réel) — schéma
    brut tel que renvoyé par l'API, distinct des tables persistées qui en dérivent.
  usage: >-
    Consommé par les pipelines d'ingestion observations. Schéma en unités SI BRUTES.
  limitations: >-
    Pas d'indicateur qualité Q* sur le flux temps réel (≠ climato).

servers:
  - server: meteofrance-dpobs
    type: api
    environment: production
    location: https://public-api.meteofrance.fr/public/DPObs/v1

schema:
  - name: station-observation
    physicalType: object
    description: Observation horaire/infrahoraire d'une station, réponse JSON.
    properties:
      - name: geo_id_insee
        physicalType: TEXT
        unit: ddnnnpp
        description: ID point (département+commune Insee+précision site)
      - name: lat
        physicalType: REAL
        unit: degré
        description: latitude du poste
      - name: lon
        physicalType: REAL
        unit: degré
        description: longitude du poste
      - name: reference_time
        physicalType: TEXT
        unit: ISO 8601 UTC
        description: production de la donnée
      - name: validity_time
        physicalType: TEXT
        unit: ISO 8601 UTC
        description: validité (clé temporelle)
      - name: t
        physicalType: REAL
        unit: K (Kelvin)
        description: température sous abri (SI brut)
      - name: td
        physicalType: REAL
        unit: K (Kelvin)
        description: point de rosée sous abri (SI brut)
      - name: tx
        physicalType: REAL
        unit: K
        description: T max sur la période (horaire)
      - name: tn
        physicalType: REAL
        unit: K
        description: T min sur la période (horaire)
      - name: u
        physicalType: INTEGER
        unit: "%"
        description: humidité relative
      - name: dd
        physicalType: INTEGER
        unit: degré (rose 360)
        description: direction du vent moyen
      - name: ff
        physicalType: REAL
        unit: m/s
        description: vent moyen à 10 m
      - name: fxi10
        physicalType: REAL
        unit: m/s
        description: rafale max instantanée
      - name: rr1
        physicalType: REAL
        unit: mm
        description: précipitations (1 h horaire / 6 min infra)
      - name: t_10
        physicalType: REAL
        unit: K
        description: température du sol à 10 cm (idem t_20/t_50/t_100)
      - name: vv
        physicalType: INTEGER
        unit: m
        description: visibilité horizontale
      - name: pres
        physicalType: REAL
        unit: Pa (Pascal)
        description: pression station (SI brut)
      - name: pmer
        physicalType: REAL
        unit: Pa (Pascal)
        description: pression niveau mer (SI brut)
      - name: insolh
        physicalType: REAL
        unit: min
        description: durée d'insolation sur la période
      - name: ray_glo01
        physicalType: REAL
        unit: J/m²
        description: rayonnement global sur la période

customProperties:
  - property: externalSource
    value:
      apiId: DPObs
      host: public-api.meteofrance.fr
      context: /public/DPObs/v1
      urlTemplate: /public/DPObs/v1/station/{horaire|infrahoraire-6m}?id_station={id}&format=json
      auth: token
      probeUrl: https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations
      verified: "✅ vérifié en live"
      unitsNote: >-
        ⚠️ Unités SI BRUTES dans la réponse API : température en KELVIN, pression en PASCAL.
        Les tables persistées (tool `schema`) convertissent en °C / hPa.
      descriptor: docs/mf/observations/{horaire,infrahoraire}.csv (descripteur officiel MF complet)
      quirks:
        - Stations RADOME (2000+), 24 dernières heures. CSV ou JSON (format=json).
        - /liste-stations, /station/horaire, /station/infrahoraire-6m (pas 6 min), /synop, /bouees.
  - property: changelog
    value:
      - version: "1.0.0"
        date: "2026-06-17"
        type: initial
        severity: non-breaking
        fields: []
        note: Transcription du dict meteofrance_catalog (état vérifié en live).

team:
  - username: pam
    role: owner
    description: Data engineer de l'association — responsable du contrat.

support:
  - channel: data
    tool: email
    url: mailto:pamahe@proton.me
```

- [ ] **Step 2 : Écrire `contracts/source-meteofrance-climato-data-gouv.odcs.yaml`**

Transcrire l'entrée `climato-data-gouv` du dict. Variante open-data (`auth: none`, unités conventionnelles) :

```yaml
apiVersion: v3.0.2
kind: DataContract
id: urn:infoclimat:contract:source-meteofrance-climato-data-gouv
name: Source Météo-France — Climatologie archives open data (meteo.data.gouv.fr)
version: 1.0.0
status: active
domain: climato
tags: [source, meteofrance]

description:
  purpose: Archives climatologiques open data (Licence Ouverte Etalab 2.0), sans auth.
  usage: Ingéré par telechargement-climatologie-meteo-data-gouv → tables timescaledb.
  limitations: Bucket distinct du bucket AROME PNT.

servers:
  - server: meteofrance-climato-data-gouv
    type: api
    environment: production
    location: https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/BASE

schema:
  - name: poste-mesure
    physicalType: object
    description: Une ligne par poste et pas de temps, une colonne par paramètre + Q<PARAM>.
    properties:
      - name: NUM_POSTE
        physicalType: TEXT
        unit: 8 chiffres
        description: numéro de poste MF
      - name: AAAAMMJJHH
        physicalType: TIMESTAMP
        unit: "—"
        description: clé temporelle (selon fréquence : AAAAMMJJ, AAAAMM)
      - name: RR
        physicalType: REAL
        unit: mm
        description: précipitations (qualité QRR)
      - name: T
        physicalType: REAL
        unit: "°C"
        description: température (moy ; TN/TX min/max)
      - name: FF
        physicalType: REAL
        unit: m/s
        description: vent moyen (FXY = rafale)

customProperties:
  - property: externalSource
    value:
      apiId: climato-data-gouv
      host: object.files.data.gouv.fr
      context: /meteofrance/data/synchro_ftp/BASE/{MN,HOR,QUOT,MENS,DECAD,DECADAGRO}
      urlTemplate: https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/BASE/{FREQ}/{FREQ}_{DD}_{periode}[_{PARAM}].csv.gz
      auth: none
      probeUrl: https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/BASE/HOR/H_descriptif_champs.csv
      verified: "✅ open data (sans token)"
      unitsNote: Unités CONVENTIONNELLES (°C, 1/10) — pas SI. Indicateur qualité Q* (ou C* pour DecadaireAgro).
      descriptor: BASE/{FREQ}/{FREQ}_descriptif_champs.csv (ex. H_descriptif_champs.csv)
      quirks:
        - Sans auth (Licence Ouverte Etalab 2.0).
        - ≠ bucket AROME PNT (object.data.gouv.fr/meteofrance-pnt).
  - property: changelog
    value:
      - version: "1.0.0"
        date: "2026-06-17"
        type: initial
        severity: non-breaking
        fields: []
        note: Transcription du dict.

team:
  - username: pam
    role: owner
    description: Data engineer de l'association.

support:
  - channel: data
    tool: email
    url: mailto:pamahe@proton.me
```

- [ ] **Step 3 : Vérifier que les deux contrats parsent et sont reconnus comme sources**

Run :
```bash
cd ~/PycharmProjects/infoclimat/data-platform && python3 -c "
import sys; sys.path.insert(0, '../ic-data-bot/src')
from ic_data_bot import meteofrance_catalog as cat
es = cat.load_sources('.')
ids = sorted(e['id'] for e in es)
print('sources:', ids)
assert 'DPObs' in ids and 'climato-data-gouv' in ids, ids
print(cat.render_changes(cat.find('.', 'DPObs')))
"
```
Expected : la liste contient `DPObs` et `climato-data-gouv` ; l'historique DPObs s'affiche (1 entrée initiale).

- [ ] **Step 4 : Commit (data-platform, sans co-signature)**

```bash
cd ~/PycharmProjects/infoclimat/data-platform
git add contracts/source-meteofrance-dpobs.odcs.yaml contracts/source-meteofrance-climato-data-gouv.odcs.yaml
git commit -m "feat(contracts): sources externes DPObs + climato-data-gouv en ODCS versionné (ADR-0002)"
```

---

## Task 4 : Migrer les 9 sources restantes + retirer le dict de référence

**Files:**
- Create (×9) : `contracts/source-meteofrance-<id>.odcs.yaml`

Source : `/tmp/catalog_dict_reference.py`. Pour **chaque** entrée restante, créer un contrat en suivant exactement le gabarit DPObs (Task 3 Step 1), via cette correspondance dict→contrat (identique pour toutes) :

| Clé du dict | Emplacement dans le contrat |
|---|---|
| `id` | `customProperties.externalSource.apiId` **et** suffixe du `id:` URN / nom de fichier |
| `label` | `name:` |
| `host` | `externalSource.host` |
| `context` | `externalSource.context` ; aussi `servers[0].location` = `https://{host}{context}` |
| `url_template` | `externalSource.urlTemplate` |
| `status` | `externalSource.verified` |
| `auth` | `externalSource.auth` |
| `probe` | `externalSource.probeUrl` |
| `notes` (liste) | `externalSource.quirks` (liste) |
| `schema.note` | `externalSource.unitsNote` |
| `schema.descriptor` | `externalSource.descriptor` |
| `schema.quality` | `externalSource.quality` (omettre si vide) |
| `schema.fields[]` `{name,type,unit,desc}` | `schema[0].properties[]` `{name, physicalType: <type>, unit, description: <desc>}` |

Toujours ajouter : `apiVersion: v3.0.2`, `kind: DataContract`, `version: "1.0.0"`, `status: active`, `tags: [source, meteofrance, api]` (sans `api` si la source est un bucket fichier), un `changelog` à une entrée initiale (`version 1.0.0`, `date 2026-06-17`, `type: initial`, `severity: non-breaking`), et les blocs `team`/`support` identiques à DPObs. Pour les entrées dont `schema.fields` est vide (DPPaquetObs, DPRadar, DPPaquetRadar, AROME-OM, ARPEGE-Paquets, AROMEPI), mettre `schema[0].properties: []` et reporter la note descriptive dans `externalSource.descriptor`.

- [ ] **Step 1 : `source-meteofrance-dppaquetobs.odcs.yaml`** (id `DPPaquetObs`)
- [ ] **Step 2 : `source-meteofrance-dpradar.odcs.yaml`** (id `DPRadar`)
- [ ] **Step 3 : `source-meteofrance-dppaquetradar.odcs.yaml`** (id `DPPaquetRadar`)
- [ ] **Step 4 : `source-meteofrance-arome-wcs.odcs.yaml`** (id `AROME-WCS`)
- [ ] **Step 5 : `source-meteofrance-arome-paquets.odcs.yaml`** (id `AROME-Paquets`)
- [ ] **Step 6 : `source-meteofrance-arome-om.odcs.yaml`** (id `AROME-OM`)
- [ ] **Step 7 : `source-meteofrance-arpege-paquets.odcs.yaml`** (id `ARPEGE-Paquets`)
- [ ] **Step 8 : `source-meteofrance-aromepi.odcs.yaml`** (id `AROMEPI`)
- [ ] **Step 9 : `source-meteofrance-piaf.odcs.yaml`** (id `PIAF`, `host: api.meteofrance.fr`)

- [ ] **Step 10 : Vérifier la parité (11 sources chargées, identité avec l'ancien dict)**

Run :
```bash
cd ~/PycharmProjects/infoclimat/data-platform && python3 -c "
import sys; sys.path.insert(0, '../ic-data-bot/src')
from ic_data_bot import meteofrance_catalog as cat
ids = sorted(e['id'] for e in cat.load_sources('.'))
expected = sorted(['DPObs','DPPaquetObs','DPRadar','DPPaquetRadar','AROME-WCS',
  'AROME-Paquets','AROME-OM','ARPEGE-Paquets','AROMEPI','PIAF','climato-data-gouv'])
assert ids == expected, (ids, expected)
print('OK 11 sources :', ids)
print(cat.render_probe and 'render ok')
print(cat.overview('.')[:200])
"
```
Expected : `OK 11 sources` avec la liste complète ; aucune assertion ne casse.

- [ ] **Step 11 : Vérifier que le bot répond pour une API non-DPObs (PIAF, host commercial)**

Run :
```bash
cd ~/PycharmProjects/infoclimat/data-platform && python3 -c "
import sys; sys.path.insert(0, '../ic-data-bot/src')
from ic_data_bot.tools import ToolBox
print(ToolBox('.').meteofrance_catalog(api='piaf', topic='contract'))
"
```
Expected : affiche le contrat PIAF avec `api.meteofrance.fr`.

- [ ] **Step 12 : Commit (data-platform)**

```bash
cd ~/PycharmProjects/infoclimat/data-platform
git add contracts/source-meteofrance-*.odcs.yaml
git commit -m "feat(contracts): migration des 9 sources MF restantes en ODCS (parité avec l'ex-dict, ADR-0002)"
```

---

## Self-review (effectuée à l'écriture)

- **Couverture du spec (ADR-0002, pilier A + tool-vue) :** contrats ODCS source = Tasks 3-4 ; `customProperties` quirks + `changelog` = Tasks 3-4 ; tool devient une vue (dict supprimé) = Task 1 ; `topic="changes"` answerability = Tasks 1-2 ; sévérité 3 niveaux = portée par les données de changelog (rendue telle quelle par `render_changes`, pas de logique à coder). Piliers B-runtime et C = hors tranche 1 (tranches 2-3), explicitement exclus.
- **Placeholders :** aucun « TODO/TBD » ; le seul travail répétitif (Task 4) est cadré par une table de correspondance complète + un gabarit concret (Task 3) + une source de données précise (`/tmp/catalog_dict_reference.py`).
- **Cohérence des types/signatures :** `meteofrance_catalog(api, topic, probe, since)` cohérent entre `tools.py`, `_dispatch`, `mcp_server.py` et les tests ; `load_sources(root)`/`find(root, q)`/`render_changes(e, since)` cohérents entre module, ToolBox et tests ; clé de propriété `unit:` cohérente entre contrats (Tasks 3-4) et adaptateur `_to_entry` (Task 1).
- **Régression :** la parité 11 sources est vérifiée par assertion (Task 4 Step 10) ; la suite complète du bot passe en Task 2 Step 7.
