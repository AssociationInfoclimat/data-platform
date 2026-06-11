"""Inventaire volumétrique des bases de données Infoclimat (lecture seule).

Interroge information_schema (MariaDB) et les vues TimescaleDB pour produire un
inventaire horodaté (CSV + résumé markdown) dans data-platform/audits/volumetrie/.
Relancé périodiquement, le diff entre snapshots mesure la croissance des volumes.
"""

import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ENV_FILE = str(Path(__file__).parent / ".env.ini")
DEFAULT_OUTPUT_DIR = str(Path(__file__).parent.parent / "audits" / "volumetrie")
TOP_TABLES_IN_SUMMARY = 20
BYTES_PER_GIB = 1024 * 1024 * 1024

HELP_TEXT = f"""\
Usage: python3 volumetrie_audit.py [options]

Inventaire volumétrique lecture seule des bases MariaDB et TimescaleDB.

Options (--flag=value ou --flag value) :
  --env-file <chemin>     Fichier de connexion ini (défaut : {DEFAULT_ENV_FILE})
  --output-dir <chemin>   Dossier de sortie (défaut : {DEFAULT_OUTPUT_DIR})
  --skip-mariadb          Ne pas inventorier MariaDB (défaut : inventorié)
  --skip-timescaledb      Ne pas inventorier TimescaleDB (défaut : inventorié)
  --help                  Affiche cette aide

Sorties :
  inventaire-AAAAMMJJ.csv  une ligne par table (système, base, table, lignes, octets)
  inventaire-AAAAMMJJ.md   résumé : totaux par base + top {TOP_TABLES_IN_SUMMARY} tables

Le fichier ini attend les sections [mariadb] et [timescaledb] avec host, port,
user, password (compte LECTURE SEULE) — voir .env.ini.template.
"""


@dataclass
class AuditConfig:
    """Paramètres d'exécution résolus depuis la ligne de commande."""

    env_file: str = DEFAULT_ENV_FILE
    output_dir: str = DEFAULT_OUTPUT_DIR
    include_mariadb: bool = True
    include_timescaledb: bool = True
    show_help: bool = False


@dataclass
class TableStat:
    """Statistiques volumétriques d'une table."""

    system: str
    database: str
    table: str
    row_estimate: int
    data_bytes: int
    index_bytes: int
    total_bytes: int
    extra: str = ""


@dataclass
class InventoryResult:
    """Résultat standardisé d'une collecte par système."""

    system: str
    success: bool
    tables: list = field(default_factory=list)
    error: str = ""


def parse_cli_args(argv: list) -> AuditConfig:
    """Analyse argv (forme --flag=value ou --flag value) vers une AuditConfig."""
    config = AuditConfig()
    flags_with_value = {"--env-file", "--output-dir"}
    index = 0
    while index < len(argv):
        argument = argv[index]
        name, separator, inline_value = argument.partition("=")
        if name == "--help":
            config.show_help = True
        elif name == "--skip-mariadb":
            config.include_mariadb = False
        elif name == "--skip-timescaledb":
            config.include_timescaledb = False
        elif name in flags_with_value:
            if separator == "=":
                value = inline_value
            else:
                index += 1
                if index >= len(argv):
                    raise ValueError(f"Option {name} attend une valeur")
                value = argv[index]
            if name == "--env-file":
                config.env_file = value
            else:
                config.output_dir = value
        else:
            raise ValueError(f"Option inconnue : {argument} (voir --help)")
        index += 1
    return config


def read_ini_sections(env_file: str) -> dict:
    """Lit un fichier ini en dict {section: {clé: valeur}} sans dépendance externe."""
    path = Path(env_file)
    if not path.is_file():
        raise FileNotFoundError(
            f"Fichier de connexion introuvable : {env_file} "
            "(copier .env.ini.template vers .env.ini et le renseigner)"
        )
    sections: dict = {}
    current_section = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            sections[current_section] = {}
            continue
        key, separator, value = line.partition("=")
        if separator == "=" and current_section:
            sections[current_section][key.strip()] = value.strip().strip('"')
    return sections


def collect_mariadb_inventory(settings: dict) -> InventoryResult:
    """Inventaire information_schema.TABLES de toutes les bases non système MariaDB."""
    try:
        import pymysql
    except ImportError:
        return InventoryResult(
            system="mariadb",
            success=False,
            error="pymysql non installé (pip install -e data-platform/tools)",
        )
    query = """
        SELECT
            TABLE_SCHEMA,
            TABLE_NAME,
            COALESCE(TABLE_ROWS, 0),
            COALESCE(DATA_LENGTH, 0),
            COALESCE(INDEX_LENGTH, 0)
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA NOT IN
            ('information_schema', 'performance_schema', 'mysql', 'sys')
        ORDER BY TABLE_SCHEMA, DATA_LENGTH + INDEX_LENGTH DESC
    """
    try:
        connection = pymysql.connect(
            host=settings["host"],
            port=int(settings.get("port", "3306")),
            user=settings["user"],
            password=settings["password"],
            read_timeout=300,
        )
    except Exception as error:
        return InventoryResult(system="mariadb", success=False, error=str(error))
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
    finally:
        connection.close()
    tables = [
        TableStat(
            system="mariadb",
            database=schema,
            table=table,
            row_estimate=int(row_count),
            data_bytes=int(data_length),
            index_bytes=int(index_length),
            total_bytes=int(data_length) + int(index_length),
        )
        for schema, table, row_count, data_length, index_length in rows
    ]
    return InventoryResult(system="mariadb", success=True, tables=tables)


def collect_timescaledb_inventory(settings: dict) -> InventoryResult:
    """Inventaire des hypertables (taille, compression) et tables classiques PostgreSQL."""
    try:
        import psycopg
    except ImportError:
        return InventoryResult(
            system="timescaledb",
            success=False,
            error="psycopg non installé (pip install -e data-platform/tools)",
        )
    hypertables_query = """
        SELECT
            ht.hypertable_schema,
            ht.hypertable_name,
            COALESCE(hypertable_size(
                format('%I.%I', ht.hypertable_schema, ht.hypertable_name)::regclass
            ), 0),
            ht.num_chunks,
            ht.compression_enabled
        FROM timescaledb_information.hypertables AS ht
        ORDER BY 3 DESC
    """
    plain_tables_query = """
        SELECT
            schemaname,
            relname,
            COALESCE(n_live_tup, 0),
            COALESCE(pg_total_relation_size(relid), 0)
        FROM pg_stat_user_tables
        WHERE relname NOT LIKE '_hyper_%'
        ORDER BY 4 DESC
    """
    dsn = (
        f"host={settings['host']} port={settings.get('port', '5432')} "
        f"dbname={settings.get('database', 'postgres')} "
        f"user={settings['user']} password={settings['password']}"
    )
    try:
        connection = psycopg.connect(dsn, connect_timeout=30)
    except Exception as error:
        return InventoryResult(system="timescaledb", success=False, error=str(error))
    tables = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(hypertables_query)
            hypertable_names = set()
            for schema, name, total_bytes, num_chunks, compressed in cursor.fetchall():
                hypertable_names.add((schema, name))
                tables.append(
                    TableStat(
                        system="timescaledb",
                        database=settings.get("database", "postgres"),
                        table=f"{schema}.{name}",
                        row_estimate=0,
                        data_bytes=int(total_bytes),
                        index_bytes=0,
                        total_bytes=int(total_bytes),
                        extra=f"hypertable chunks={num_chunks} compression={compressed}",
                    )
                )
            cursor.execute(plain_tables_query)
            for schema, name, live_rows, total_bytes in cursor.fetchall():
                if (schema, name) in hypertable_names:
                    continue
                tables.append(
                    TableStat(
                        system="timescaledb",
                        database=settings.get("database", "postgres"),
                        table=f"{schema}.{name}",
                        row_estimate=int(live_rows),
                        data_bytes=int(total_bytes),
                        index_bytes=0,
                        total_bytes=int(total_bytes),
                    )
                )
    finally:
        connection.close()
    return InventoryResult(system="timescaledb", success=True, tables=tables)


def write_csv(tables: list, csv_path: Path) -> None:
    """Écrit l'inventaire complet au format CSV."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["system", "database", "table", "row_estimate",
             "data_bytes", "index_bytes", "total_bytes", "extra"]
        )
        for stat in tables:
            writer.writerow(
                [stat.system, stat.database, stat.table, stat.row_estimate,
                 stat.data_bytes, stat.index_bytes, stat.total_bytes, stat.extra]
            )


def format_gibibytes(byte_count: int) -> str:
    """Formate un volume en GiB avec deux décimales."""
    return f"{byte_count / BYTES_PER_GIB:.2f} GiB"


def write_summary(results: list, tables: list, summary_path: Path, snapshot_date: str) -> None:
    """Écrit le résumé markdown : statut par système, totaux par base, top tables."""
    lines = [f"# Inventaire volumétrie — {snapshot_date}", ""]
    for result in results:
        status = "OK" if result.success else f"ÉCHEC — {result.error}"
        lines.append(f"- **{result.system}** : {status} ({len(result.tables)} tables)")
    lines.append("")
    totals_per_database: dict = {}
    for stat in tables:
        key = f"{stat.system}/{stat.database}"
        totals_per_database[key] = totals_per_database.get(key, 0) + stat.total_bytes
    lines.extend(["## Totaux par base", "", "| Base | Volume |", "|---|---|"])
    for key, total in sorted(totals_per_database.items(), key=lambda item: -item[1]):
        lines.append(f"| {key} | {format_gibibytes(total)} |")
    grand_total = sum(totals_per_database.values())
    lines.extend(["", f"**Total : {format_gibibytes(grand_total)}**", ""])
    biggest = sorted(tables, key=lambda stat: -stat.total_bytes)[:TOP_TABLES_IN_SUMMARY]
    lines.extend(
        [f"## Top {TOP_TABLES_IN_SUMMARY} tables", "",
         "| Table | Lignes (estim.) | Volume | Notes |", "|---|---|---|---|"]
    )
    for stat in biggest:
        lines.append(
            f"| {stat.database}.{stat.table} | {stat.row_estimate:,} "
            f"| {format_gibibytes(stat.total_bytes)} | {stat.extra} |"
        )
    lines.append("")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")


def run_audit(config: AuditConfig) -> int:
    """Orchestre la collecte et l'écriture des sorties ; retourne le code de sortie."""
    sections = read_ini_sections(config.env_file)
    results = []
    if config.include_mariadb:
        results.append(collect_mariadb_inventory(sections.get("mariadb", {})))
    if config.include_timescaledb:
        results.append(collect_timescaledb_inventory(sections.get("timescaledb", {})))
    if not results:
        print("Rien à inventorier : les deux systèmes sont exclus.", file=sys.stderr)
        return 1
    tables = [stat for result in results for stat in result.tables]
    snapshot_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_dir = Path(config.output_dir)
    csv_path = output_dir / f"inventaire-{snapshot_date}.csv"
    summary_path = output_dir / f"inventaire-{snapshot_date}.md"
    write_csv(tables, csv_path)
    write_summary(results, tables, summary_path, snapshot_date)
    failures = [result for result in results if not result.success]
    for failure in failures:
        print(f"[{failure.system}] échec : {failure.error}", file=sys.stderr)
    print(f"{len(tables)} tables inventoriées → {csv_path}")
    print(f"Résumé → {summary_path}")
    return 1 if failures else 0


def main() -> None:
    """Point d'entrée CLI."""
    try:
        config = parse_cli_args(sys.argv[1:])
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
    if config.show_help:
        print(HELP_TEXT)
        sys.exit(0)
    try:
        sys.exit(run_audit(config))
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
