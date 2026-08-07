"""Wrapper de lineage pour pipelines cron (OpenLineage, hors monolithe).

S'utilise en tête de ligne crontab pour émettre des RunEvents OpenLineage
START puis COMPLETE/FAIL autour d'une commande, sans modifier le code du
pipeline. Les événements sont écrits en JSONL local (append atomique) et
relayés vers Marquez par lineage_forward.py.

Garantie « jamais bloquant » : aucune erreur interne du wrapper (spool
inaccessible, disque plein…) n'empêche l'exécution de la commande ni n'altère
son exit code, qui est toujours propagé tel quel.

Exemple (crontab) :
  */5 * * * * python3 lineage_run.py --job cron.metar_synop -- php .../cron/metars.php
"""

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PRODUCER = "https://github.com/infoclimat/site-infoclimat"
SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent"
ERROR_FACET_SCHEMA = "https://openlineage.io/spec/facets/1-0-0/ErrorMessageRunFacet.json"
DEFAULT_NAMESPACE = "cron://infoclimat"
DEFAULT_SPOOL = "/var/spool/lineage/events.jsonl"
DEFAULT_EVIDENCE = ""
EVIDENCE_ENV = "LINEAGE_EVIDENCE_PATH"
EVIDENCE_FACET = "infoclimat_station_reference"
EVIDENCE_FACET_SCHEMA = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/BaseFacet"
MAX_EVIDENCE_BYTES = 64 * 1024
EVIDENCE_KEYS = {
    "schema_version",
    "input_snapshot_ids",
    "output_snapshot_ids",
    "ingest_run_id",
    "status_counts",
    "flag_counts",
    "registry_version",
}

HELP_TEXT = f"""\
Usage: python3 lineage_run.py --job <nom> [options] -- <commande> [args…]

Émet un RunEvent OpenLineage START avant la commande, puis COMPLETE ou FAIL
selon son exit code (propagé tel quel). Append JSONL local, jamais bloquant.

Options (--flag=value ou --flag value) :
  --job <nom>          Nom du job (cf. data-platform/lineage/jobs.yaml), requis
  --namespace <ns>     Namespace du job (défaut : {DEFAULT_NAMESPACE})
  --spool <chemin>     Fichier JSONL de spool (défaut : {DEFAULT_SPOOL})
  --evidence <chemin>  JSON métier borné, lu après la commande (ou {EVIDENCE_ENV})
  --help               Affiche cette aide

Tout ce qui suit `--` est la commande à exécuter, lancée avec les stdio
hérités (les redirections de la ligne cron restent effectives).

Conventions : data-platform/lineage/namespaces.md ; format de référence :
data-platform/lineage/examples/run-event-complete.json.
"""


def parse_cli_args(argv: list) -> tuple:
    """Sépare argv en (options, commande) autour du premier `--`."""
    options = {
        "job": "",
        "namespace": DEFAULT_NAMESPACE,
        "spool": DEFAULT_SPOOL,
        "evidence": os.environ.get(EVIDENCE_ENV, DEFAULT_EVIDENCE),
        "help": False,
    }
    flags_with_value = {
        "--job": "job",
        "--namespace": "namespace",
        "--spool": "spool",
        "--evidence": "evidence",
    }
    command = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            command = argv[index + 1 :]
            break
        if arg == "--help":
            options["help"] = True
        elif "=" in arg and arg.split("=", 1)[0] in flags_with_value:
            flag, value = arg.split("=", 1)
            options[flags_with_value[flag]] = value
        elif arg in flags_with_value:
            index += 1
            if index >= len(argv):
                raise ValueError(f"valeur manquante pour {arg}")
            options[flags_with_value[arg]] = argv[index]
        else:
            raise ValueError(f"option inconnue : {arg}")
        index += 1
    return options, command


def utc_now_iso() -> str:
    """Horodatage ISO 8601 UTC milliseconde, suffixe Z (format des exemples)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    )


def build_event(event_type: str, run_id: str, namespace: str, job: str, run_facets: dict) -> dict:
    """Construit un RunEvent OpenLineage minimal (inputs/outputs : forwarder)."""
    run = {"runId": run_id}
    if run_facets:
        run["facets"] = run_facets
    return {
        "eventType": event_type,
        "eventTime": utc_now_iso(),
        "producer": PRODUCER,
        "schemaURL": SCHEMA_URL,
        "run": run,
        "job": {"namespace": namespace, "name": job},
    }


def emit(spool: str, event: dict) -> None:
    """Append une ligne JSONL au spool. Toute erreur est avalée (jamais bloquant)."""
    try:
        path = Path(spool)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception as error:  # noqa: BLE001 — le lineage ne doit jamais casser un cron
        print(f"lineage_run: événement non écrit ({error})", file=sys.stderr)


def process_facet(command: list, exit_code: int = None, duration: float = None) -> dict:
    """Facet custom décrivant le process wrappé (host, commande, exit code, durée)."""
    facet = {
        "_producer": PRODUCER,
        "_schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/BaseFacet",
        "hostname": socket.gethostname(),
        "command": " ".join(command),
    }
    if exit_code is not None:
        facet["exitCode"] = exit_code
    if duration is not None:
        facet["durationSeconds"] = round(duration, 3)
    return facet


def _bounded_string(value, field: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{field} must be a non-empty string of at most {limit} characters")
    return value


def _bounded_string_map(value, field: str, integer_values: bool = False) -> dict:
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError(f"{field} must be an object with at most 32 entries")
    result = {}
    for key, item in value.items():
        key = _bounded_string(key, f"{field} key", 256)
        if integer_values:
            if not isinstance(item, int) or isinstance(item, bool) or item < 0:
                raise ValueError(f"{field}.{key} must be a non-negative integer")
        else:
            item = _bounded_string(item, f"{field}.{key}", 256)
        result[key] = item
    return result


def load_evidence(path: str) -> dict:
    """Charge la preuve métier bornée sans jamais exposer de lignes ou secrets."""
    if not path:
        return {}
    evidence_path = Path(path)
    if evidence_path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError(f"evidence exceeds {MAX_EVIDENCE_BYTES} bytes")
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != EVIDENCE_KEYS:
        raise ValueError("evidence must contain only the documented station-reference keys")
    if document["schema_version"] != "1.0":
        raise ValueError("unsupported evidence schema_version")
    return {
        "schema_version": "1.0",
        "input_snapshot_ids": _bounded_string_map(
            document["input_snapshot_ids"], "input_snapshot_ids"
        ),
        "output_snapshot_ids": _bounded_string_map(
            document["output_snapshot_ids"], "output_snapshot_ids"
        ),
        "ingest_run_id": _bounded_string(document["ingest_run_id"], "ingest_run_id"),
        "status_counts": _bounded_string_map(
            document["status_counts"], "status_counts", integer_values=True
        ),
        "flag_counts": _bounded_string_map(
            document["flag_counts"], "flag_counts", integer_values=True
        ),
        "registry_version": _bounded_string(
            document["registry_version"], "registry_version"
        ),
    }


def evidence_facet(path: str) -> dict:
    if not path:
        return {}
    try:
        evidence = load_evidence(path)
    except Exception as error:  # noqa: BLE001 — preuve non bloquante comme le spool
        print(f"lineage_run: preuve métier ignorée ({error})", file=sys.stderr)
        return {}
    return {
        EVIDENCE_FACET: {
            "_producer": PRODUCER,
            "_schemaURL": EVIDENCE_FACET_SCHEMA,
            **evidence,
        }
    }


def main(argv: list) -> int:
    try:
        options, command = parse_cli_args(argv)
    except ValueError as error:
        print(f"lineage_run: {error}\n\n{HELP_TEXT}", file=sys.stderr)
        return 2
    if options["help"]:
        print(HELP_TEXT)
        return 0
    if not options["job"] or not command:
        print(f"lineage_run: --job et une commande après `--` sont requis\n\n{HELP_TEXT}", file=sys.stderr)
        return 2

    run_id = str(uuid.uuid4())
    namespace, job, spool = options["namespace"], options["job"], options["spool"]

    emit(spool, build_event("START", run_id, namespace, job,
                            {"infoclimat_process": process_facet(command)}))

    started = time.monotonic()
    error_message = ""
    try:
        command_env = os.environ.copy()
        if options["evidence"]:
            command_env[EVIDENCE_ENV] = options["evidence"]
        exit_code = subprocess.run(command, env=command_env).returncode  # stdio hérités du cron
    except OSError as error:  # commande introuvable / non exécutable
        exit_code = 127
        error_message = str(error)
        print(f"lineage_run: échec du lancement : {error}", file=sys.stderr)
    duration = time.monotonic() - started

    facets = {"infoclimat_process": process_facet(command, exit_code, duration)}
    facets.update(evidence_facet(options["evidence"]))
    if exit_code == 0:
        emit(spool, build_event("COMPLETE", run_id, namespace, job, facets))
    else:
        facets["errorMessage"] = {
            "_producer": PRODUCER,
            "_schemaURL": ERROR_FACET_SCHEMA,
            "message": error_message or f"exit code {exit_code}",
            "programmingLanguage": "shell",
        }
        emit(spool, build_event("FAIL", run_id, namespace, job, facets))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
