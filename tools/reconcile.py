"""Réconciliation inventaire code (tables.yaml) vs existant prod (CSV volumetrie_audit).

Croise les tables référencées dans le code et les tables réellement présentes en base :
  - matched : référencées ET présentes
  - ghosts  : référencées dans le code, absentes en base (code mort probable)
  - orphans : présentes en base, jamais référencées (candidates archivage)
Usage : python3 reconcile.py --tables ../inventory/tables.yaml \
        --csv ../audits/volumetrie/inventaire-AAAAMMJJ.csv \
        --output ../audits/inventaire-2026-06/reconcile-output-AAAAMMJJ.md
"""

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Tokens réellement utilisés dans les champs name: de tables.yaml (grep '  - name:' tables.yaml).
# {AAAA} et {MM} et {1-3} sont les seuls tokens dans les noms de tables.
# {YYYY} et {dd} sont des variantes orthographiques vues dans les commentaires/notes du YAML
# (ex. INSERT INTO V5_data_{YYYY}.bouees_{MM}_d{dd}) et couverts ici par précaution.
PATTERN_TOKENS = {
    "{AAAA}": r"\d{4}",
    "{YYYY}": r"\d{4}",
    "{MM}": r"\d{2}",
    "{1-3}": r"[1-3]",
    "{dd}": r"\d{2}",
    # {XX} : code à 2 lettres (pays ISO / paramètre clim). Couvre les familles
    # data_geo/geoNames_{XX} et V5_climato/eca_{XX}_{XX} (ajouté 2026-06-09).
    "{XX}": r"[A-Za-z]{2}",
}

HELP_TEXT = """\
Usage: python3 reconcile.py --tables <tables.yaml> --csv <inventaire.csv> --output <rapport.md>

Options (--flag=value ou --flag value) :
  --tables <chemin>   Inventaire des tables référencées dans le code (YAML)
  --csv <chemin>      Inventaire prod produit par volumetrie_audit.py (CSV)
  --output <chemin>   Rapport markdown de réconciliation à écrire
  --help              Affiche cette aide
"""


@dataclass(frozen=True)
class TableRecord:
    name: str
    source: str


@dataclass(frozen=True)
class ReconcileResult:
    matched: list
    ghosts: list
    orphans: list


def pattern_to_regex(pattern_name: str) -> str:
    escaped = re.escape(pattern_name)
    for token, regex in PATTERN_TOKENS.items():
        escaped = escaped.replace(re.escape(token), regex)
    return f"^{escaped}$"


def expand_pattern_name(pattern_name: str, concrete_name: str) -> bool:
    return re.match(pattern_to_regex(pattern_name), concrete_name) is not None


def match_referenced_to_actual(csv_row: dict) -> TableRecord:
    name = f"{csv_row['system']}://{csv_row['database']}/{csv_row['table']}"
    return TableRecord(name=name, source="db")


def reconcile(referenced: list, actual: list) -> ReconcileResult:
    matched = []
    orphans = []
    ghost_candidates = {record.name: record for record in referenced}
    for actual_record in actual:
        matching_refs = [r for r in referenced if expand_pattern_name(r.name, actual_record.name)]
        if matching_refs:
            matched.append(actual_record)
            for ref in matching_refs:
                ghost_candidates.pop(ref.name, None)
        else:
            orphans.append(actual_record)
    ghosts = sorted(ghost_candidates.values(), key=lambda record: record.name)
    return ReconcileResult(matched=matched, ghosts=ghosts, orphans=orphans)


def load_referenced(tables_yaml_path: str) -> list:
    data = yaml.safe_load(Path(tables_yaml_path).read_text(encoding="utf-8"))
    return [TableRecord(name=entry["name"], source="code") for entry in data.get("tables", [])]


def load_actual(csv_path: str) -> list:
    with Path(csv_path).open(encoding="utf-8") as handle:
        return [match_referenced_to_actual(row) for row in csv.DictReader(handle)]


def write_report(result: ReconcileResult, output_path: str) -> None:
    lines = [
        "# Réconciliation tables code vs prod",
        "",
        f"- Tables en base appariées au code : **{len(result.matched)}**",
        f"- Fantômes (code → absentes en base) : **{len(result.ghosts)}**",
        f"- Orphelines (en base, jamais référencées) : **{len(result.orphans)}**",
        "",
        "## Fantômes",
        *[f"- {record.name}" for record in result.ghosts],
        "",
        "## Orphelines",
        *[f"- {record.name}" for record in result.orphans],
        "",
    ]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def parse_cli_args(argv: list) -> dict:
    args = {"tables": None, "csv": None, "output": None}
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "--help":
            print(HELP_TEXT)
            sys.exit(0)
        if "=" in token:
            flag, value = token.split("=", 1)
        else:
            flag, value = token, argv[index + 1] if index + 1 < len(argv) else None
            index += 1
        key = flag.lstrip("-")
        if key not in args or value is None:
            print(f"Argument invalide : {token}\n{HELP_TEXT}", file=sys.stderr)
            sys.exit(2)
        args[key] = value
        index += 1
    missing = [key for key, value in args.items() if value is None]
    if missing:
        print(f"Arguments manquants : {', '.join('--' + key for key in missing)}\n{HELP_TEXT}",
              file=sys.stderr)
        sys.exit(2)
    return args


def main() -> None:
    args = parse_cli_args(sys.argv)
    result = reconcile(load_referenced(args["tables"]), load_actual(args["csv"]))
    write_report(result, args["output"])
    print(f"matched={len(result.matched)} ghosts={len(result.ghosts)} orphans={len(result.orphans)}"
          f" → {args['output']}")


if __name__ == "__main__":
    main()
