"""Forwarder du spool lineage local vers Marquez (OpenLineage).

Lit le spool JSONL produit par lineage_run.py (ou tout autre emitter respectant
les conventions de lineage/namespaces.md), enrichit chaque RunEvent avec les
inputs/outputs déclarés dans lineage/jobs.yaml quand l'événement n'en porte
pas, puis POSTe vers l'API Marquez (/api/v1/lineage).

L'offset (en octets) n'avance qu'après acquittement de Marquez : une relance
reprend où elle s'était arrêtée, sans doublon ni perte. Conçu pour tourner en
cron (--once) ou en boucle (--interval).
"""

import configparser
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_ENV_FILE = str(Path(__file__).parent / ".env.ini")
DEFAULT_SPOOL = "/var/spool/lineage/events.jsonl"
DEFAULT_JOBS_YAML = str(Path(__file__).parent.parent / "lineage" / "jobs.yaml")
HTTP_TIMEOUT_SECONDS = 10

HELP_TEXT = f"""\
Usage: python3 lineage_forward.py [options]

Relaye le spool JSONL de lineage vers Marquez, avec enrichissement des
inputs/outputs déclarés dans jobs.yaml. Offset durable : relance idempotente.

Options (--flag=value ou --flag value) :
  --env-file <chemin>     Fichier ini avec la section [marquez] (défaut : {DEFAULT_ENV_FILE})
  --spool <chemin>        Spool JSONL à relayer (défaut : {DEFAULT_SPOOL})
  --offset-file <chemin>  Fichier d'offset (défaut : <spool>.offset)
  --jobs-yaml <chemin>    Mapping jobs OpenLineage (défaut : {DEFAULT_JOBS_YAML})
  --once                  Un seul passage puis sortie (défaut)
  --interval <secondes>   Boucle avec pause entre les passages
  --help                  Affiche cette aide

Le fichier ini attend une section [marquez] avec `url` (ex. http://localhost:5000).
"""


@dataclass
class ForwardConfig:
    """Paramètres d'exécution résolus depuis la ligne de commande."""

    env_file: str = DEFAULT_ENV_FILE
    spool: str = DEFAULT_SPOOL
    offset_file: str = ""
    jobs_yaml: str = DEFAULT_JOBS_YAML
    interval: int = 0
    show_help: bool = False


def parse_cli_args(argv: list) -> ForwardConfig:
    """Analyse argv (forme --flag=value ou --flag value) vers une ForwardConfig."""
    config = ForwardConfig()
    flags_with_value = {
        "--env-file": "env_file",
        "--spool": "spool",
        "--offset-file": "offset_file",
        "--jobs-yaml": "jobs_yaml",
        "--interval": "interval",
    }
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--help":
            config.show_help = True
        elif arg == "--once":
            config.interval = 0
        elif "=" in arg and arg.split("=", 1)[0] in flags_with_value:
            flag, value = arg.split("=", 1)
            setattr(config, flags_with_value[flag], value)
        elif arg in flags_with_value:
            index += 1
            if index >= len(argv):
                raise ValueError(f"valeur manquante pour {arg}")
            setattr(config, flags_with_value[arg], argv[index])
        else:
            raise ValueError(f"option inconnue : {arg}")
        index += 1
    config.interval = int(config.interval)
    if not config.offset_file:
        config.offset_file = config.spool + ".offset"
    return config


def load_marquez_url(env_file: str) -> str:
    """Lit l'URL Marquez dans la section [marquez] du fichier ini."""
    parser = configparser.ConfigParser()
    if not parser.read(env_file):
        raise RuntimeError(f"fichier de configuration introuvable : {env_file}")
    if not parser.has_option("marquez", "url"):
        raise RuntimeError(f"section [marquez] avec `url` requise dans {env_file}")
    return parser.get("marquez", "url").rstrip("/")


def load_declared_datasets(jobs_yaml: str) -> dict:
    """Index job_name → {inputs, outputs} déclarés dans jobs.yaml (si présents)."""
    with open(jobs_yaml, encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    declared = {}
    for job in document.get("jobs", []):
        datasets = {}
        for direction in ("inputs", "outputs"):
            if job.get(direction):
                datasets[direction] = job[direction]
        if datasets:
            declared[job["job_name"]] = datasets
    return declared


def enrich_event(event: dict, declared: dict) -> dict:
    """Injecte les datasets déclarés si l'événement n'en porte pas déjà."""
    job_name = event.get("job", {}).get("name", "")
    datasets = declared.get(job_name)
    if not datasets:
        return event
    for direction in ("inputs", "outputs"):
        if direction in datasets and not event.get(direction):
            event[direction] = datasets[direction]
    return event


def post_event(marquez_url: str, event: dict) -> None:
    """POSTe un RunEvent vers Marquez ; lève en cas d'échec (offset non avancé)."""
    payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        marquez_url + "/api/v1/lineage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"Marquez a répondu {response.status}")


def read_offset(offset_file: str) -> int:
    try:
        return int(Path(offset_file).read_text(encoding="utf-8").strip() or "0")
    except FileNotFoundError:
        return 0


def write_offset(offset_file: str, offset: int) -> None:
    Path(offset_file).write_text(str(offset), encoding="utf-8")


def forward_once(config: ForwardConfig, marquez_url: str, declared: dict) -> tuple:
    """Relaye les événements depuis l'offset courant. Retourne (relayés, restants)."""
    spool = Path(config.spool)
    if not spool.exists():
        return 0, 0
    offset = read_offset(config.offset_file)
    forwarded = 0
    with open(spool, "rb") as handle:
        handle.seek(offset)
        while True:
            line = handle.readline()
            if not line or not line.endswith(b"\n"):
                break  # fin de fichier ou ligne en cours d'écriture : on s'arrête là
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                print(f"lineage_forward: ligne illisible ignorée à l'offset {offset} ({error})",
                      file=sys.stderr)
                offset += len(line)
                write_offset(config.offset_file, offset)
                continue
            try:
                post_event(marquez_url, enrich_event(event, declared))
            except (urllib.error.URLError, RuntimeError, OSError) as error:
                print(f"lineage_forward: envoi interrompu, reprise au prochain passage ({error})",
                      file=sys.stderr)
                break
            offset += len(line)
            write_offset(config.offset_file, offset)
            forwarded += 1
        remaining = spool.stat().st_size - offset
    return forwarded, remaining


def main(argv: list) -> int:
    try:
        config = parse_cli_args(argv)
    except ValueError as error:
        print(f"lineage_forward: {error}\n\n{HELP_TEXT}", file=sys.stderr)
        return 2
    if config.show_help:
        print(HELP_TEXT)
        return 0
    try:
        marquez_url = load_marquez_url(config.env_file)
        declared = load_declared_datasets(config.jobs_yaml)
    except (RuntimeError, OSError, yaml.YAMLError) as error:
        print(f"lineage_forward: {error}", file=sys.stderr)
        return 1

    while True:
        forwarded, remaining = forward_once(config, marquez_url, declared)
        print(f"lineage_forward: {forwarded} événement(s) relayé(s), {remaining} octet(s) en attente")
        if config.interval <= 0:
            return 0 if remaining == 0 else 1
        time.sleep(config.interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
