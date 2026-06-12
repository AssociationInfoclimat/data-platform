#!/usr/bin/env bash
# Exécute `datacontract test` contre la base TimescaleDB (lecture seule).
#
# Usage   : ./tools/test_contracts.sh contracts/<contrat>.odcs.yaml [...]
# Prérequis :
#   - tools/.env.ini renseigné (section [timescaledb]) — jamais committé ;
#   - pip install 'datacontract-cli[postgres]' 'psycopg[binary]' ;
#   - accès réseau à la base (exécution depuis le réseau interne ou VPN).
#
# NB : la base est en encodage SQL_ASCII (constat 2026-06-12) — PGCLIENTENCODING=UTF8
# est indispensable, sinon psycopg renvoie des bytes et les checks échouent.
set -euo pipefail
cd "$(dirname "$0")/.."

eval "$(python3 - <<'PY'
import configparser
c = configparser.ConfigParser(); c.read('tools/.env.ini')
ts = c['timescaledb']
print(f"export TIMESCALEDB_HOST={ts['host']}")
print(f"export DATACONTRACT_POSTGRES_USERNAME={ts['user']}")
print(f"export DATACONTRACT_POSTGRES_PASSWORD={ts['password']}")
PY
)"
export PGCLIENTENCODING=UTF8

status=0
for contract in "$@"; do
  tmp=$(mktemp)
  sed "s/\${TIMESCALEDB_HOST}/$TIMESCALEDB_HOST/" "$contract" > "$tmp"
  echo "=== $contract"
  datacontract test "$tmp" --server prod-timescaledb | tail -2 || status=1
  rm -f "$tmp"
done
exit $status
