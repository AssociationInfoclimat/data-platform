#!/usr/bin/env python3
"""Génère le registre RGPD des traitements depuis audits/rgpd/traitements.yaml.

Garde-fou de complétude : toute table `personal_data: true` de inventory/tables.yaml
doit apparaître dans un traitement, et toute table citée dans traitements.yaml doit
exister dans l'inventaire avec le flag. En cas d'écart, le script échoue (code 1) —
le registre ne peut donc pas dériver en silence de l'inventaire.

Usage :
  python3 tools/build_rgpd_register.py            # régénère le registre
  python3 tools/build_rgpd_register.py --check    # vérifie complétude sans écrire (CI)
"""
from __future__ import annotations

import sys

import yaml

INVENTORY = 'inventory/tables.yaml'
SOURCE = 'audits/rgpd/traitements.yaml'
OUTPUT = 'audits/rgpd/registre-traitements.md'


def load_personal_tables() -> set[str]:
    inv = yaml.safe_load(open(INVENTORY))
    return {e['name'] for e in inv['tables'] if e.get('personal_data')}


def check(data: dict, inventory: set[str]) -> list[str]:
    declared = {t for tr in data['traitements'] for t in tr['tables']}
    errors = []
    for missing in sorted(inventory - declared):
        errors.append(f"table personal_data absente du registre : {missing}")
    for extra in sorted(declared - inventory):
        errors.append(f"table du registre absente/non-flag dans l'inventaire : {extra}")
    return errors


def _flat(value) -> str:
    """Aplatit un scalaire YAML multi-ligne (bloc `>-`) en une ligne."""
    return ' '.join(str(value).split())


def render(data: dict, inventory: set[str]) -> str:
    n_tr = len(data['traitements'])
    n_tab = len({t for tr in data['traitements'] for t in tr['tables']})
    meta = data.get('meta', {})
    lines = [
        "# Registre des traitements de données personnelles — volet data-platform",
        "",
        "> **Document généré** par `tools/build_rgpd_register.py` depuis "
        "`audits/rgpd/traitements.yaml`. Ne pas éditer à la main — modifier la source.",
        "",
        "Ce registre recense **où vivent les données personnelles** dans le système "
        "d'information, regroupées par finalité. Il constitue la contribution technique "
        "de la data-platform au registre des traitements de l'association (art. 30 RGPD).",
        "",
        f"**{n_tr} traitements**, **{n_tab} tables** porteuses de données personnelles "
        f"(source de vérité du périmètre : `inventory/tables.yaml`, flag `personal_data`).",
        "",
    ]
    if meta.get('responsable'):
        lines += [f"- **Responsable de traitement** : {_flat(meta['responsable'])}"]
    if meta.get('socle_securite'):
        lines += [f"- **Socle de sécurité commun** : {_flat(meta['socle_securite'])}"]
    if meta.get('note_juridique'):
        lines += [f"- **Réserve juridique** : {_flat(meta['note_juridique'])}"]
    lines.append("")

    for tr in data['traitements']:
        lines.append(f"## {tr['finalite']}")
        lines.append("")
        lines.append(f"- **Identifiant** : `{tr['id']}`")
        lines.append(f"- **Personnes concernées** : {tr['personnes']}")
        lines.append(f"- **Données** : {tr['donnees']}")
        if tr.get('destinataires'):
            lines.append(f"- **Destinataires** : {_flat(tr['destinataires'])}")
        if tr.get('transferts'):
            lines.append(f"- **Transferts hors-UE** : {_flat(tr['transferts'])}")
        lines.append(f"- **Base légale** : {tr['base_legale']}")
        lines.append(f"- **Conservation** : {tr['conservation']}")
        if tr.get('localisation'):
            lines.append(f"- **Localisation** : {_flat(tr['localisation'])}")
        lines.append(f"- **Mesures de sécurité** : "
                     f"{_flat(tr['securite']) if tr.get('securite') else 'socle commun (cf. en-tête)'}")
        contrat = tr.get('contrat')
        if contrat:
            lines.append(f"- **Contrat de données** : [`{contrat}`]"
                         f"(../../contracts/{contrat}.odcs.yaml)")
        else:
            lines.append("- **Contrat de données** : —")
        if tr.get('note'):
            lines.append(f"- **Note** : {_flat(tr['note'])}")
        lines.append("- **Tables** :")
        for t in tr['tables']:
            dead = t not in inventory
            tag = " _(morte / hors flag)_" if dead else ""
            lines.append(f"    - `{t}`{tag}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    data = yaml.safe_load(open(SOURCE))
    inventory = load_personal_tables()
    errors = check(data, inventory)
    # les tables explicitement mortes du registre sont tolérées si l'inventaire les a en statut mort
    if errors:
        inv_all = {e['name']: e.get('status') for e in yaml.safe_load(open(INVENTORY))['tables']}
        errors = [e for e in errors
                  if not (e.startswith("table du registre absente")
                          and inv_all.get(e.split(': ')[1]) == 'mort')]
    if errors:
        print("Registre RGPD incohérent avec l'inventaire :", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    if '--check' in argv:
        print(f"Registre RGPD cohérent ({len(data['traitements'])} traitements).")
        return 0
    open(OUTPUT, 'w').write(render(data, inventory) + "\n")
    print(f"Écrit {OUTPUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
