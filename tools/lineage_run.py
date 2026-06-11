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

HELP_TEXT = f"""\
Usage: python3 lineage_run.py --job <nom> [options] -- <commande> [args…]

Émet un RunEvent OpenLineage START avant la commande, puis COMPLETE ou FAIL
selon son exit code (propagé tel quel). Append JSONL local, jamais bloquant.

Options (--flag=value ou --flag value) :
  --job <nom>          Nom du job (cf. data-platform/lineage/jobs.yaml), requis
  --namespace <ns>     Namespace du job (défaut : {DEFAULT_NAMESPACE})
  --spool <chemin>     Fichier JSONL de spool (défaut : {DEFAULT_SPOOL})
  --help               Affiche cette aide

Tout ce qui suit `--` est la commande à exécuter, lancée avec les stdio
hérités (les redirections de la ligne cron restent effectives).

Conventions : data-platform/lineage/namespaces.md ; format de référence :
data-platform/lineage/examples/run-event-complete.json.
"""


def parse_cli_args(argv: list) -> tuple:
    """Sépare argv en (options, commande) autour du premier `--`."""
    options = {"job": "", "namespace": DEFAULT_NAMESPACE, "spool": DEFAULT_SPOOL, "help": False}
    flags_with_value = {"--job": "job", "--namespace": "namespace", "--spool": "spool"}
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
        exit_code = subprocess.run(command).returncode  # stdio hérités du cron
    except OSError as error:  # commande introuvable / non exécutable
        exit_code = 127
        error_message = str(error)
        print(f"lineage_run: échec du lancement : {error}", file=sys.stderr)
    duration = time.monotonic() - started

    facets = {"infoclimat_process": process_facet(command, exit_code, duration)}
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
