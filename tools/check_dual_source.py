#!/usr/bin/env python3
"""Contrôle de cohérence dual-source MariaDB ↔ TimescaleDB.

Pour chaque appariement de `audits/dual-source-targets.yaml`, compare la COUVERTURE
(stations présentes de chaque côté) et les COMPTES de lignes par station/jour sur une
fenêtre récente. C'est la métrique de readiness au décommissionnement du fallback
MariaDB (cf. contrat mf-data-fallback, decommissionPlan).

PROD-SAFE : deux agrégats GROUP BY bornés par la fenêtre, sur colonnes temps indexées
des deux côtés (MariaDB : index en tête vérifié ; TimescaleDB : colonne de
partitionnement → exclusion de chunks). Aucun scan de valeurs.

Usage : python3 tools/check_dual_source.py [--check]
  --check : code de sortie 1 si la couverture passe sous min_coverage_pct ou si des
            (station, jour) communs dépassent max_count_delta_pct.
Prérequis : tools/.env.ini ([mariadb] et [timescaledb]),
            pip install pymysql 'psycopg[binary]' pyyaml.
"""
from __future__ import annotations

import configparser
import datetime
import glob
import re
import sys

import yaml

TARGETS = 'audits/dual-source-targets.yaml'


def monthly_tables(template: str, start: datetime.date, end: datetime.date) -> list[str]:
    """mf_data_{AAAA}_{MM} → tables des mois couverts par [start, end] (souvent 1, 2 près
    d'une bascule de mois). Le partitionnement est par mois d'ingestion, donc lire les
    tables des mois de la fenêtre suffit."""
    base = template.split(' (')[0]
    names, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        names.append(base.replace('{AAAA}', str(y)).replace('{MM}', f'{m:02d}'))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return names


def contract_db(cid: str, obj: str, today: datetime.date) -> str:
    """Base physique d'un objet de contrat (customProperty physicalDatabase ou servers[0])."""
    for f in glob.glob('contracts/*.odcs.yaml'):
        if '_template' in f:
            continue
        c = yaml.safe_load(open(f))
        if c['id'].split(':')[-1] != cid:
            continue
        srv = (c.get('servers') or [{}])[0]
        db = (srv.get('database') or '').replace('{AAAA}', str(today.year))
        for o in c.get('schema', []):
            if (o.get('physicalName') or o['name']) == obj:
                for p in o.get('customProperties', []) or []:
                    if p.get('property') == 'physicalDatabase':
                        db = str(p['value']).replace('{AAAA}', str(today.year))
                return db
        return db
    raise SystemExit(f"cible inconnue des contrats : {cid} / {obj}")


def main(argv: list[str]) -> int:
    cfg = configparser.ConfigParser()
    cfg.read('tools/.env.ini')
    today = datetime.date.today()
    spec = yaml.safe_load(open(TARGETS))
    window = datetime.timedelta(days=spec.get('window_days', 7))
    since = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - window)
    since_str = since.strftime('%Y-%m-%d %H:%M:%S')

    import pymysql
    import psycopg
    m = cfg['mariadb']
    my = pymysql.connect(host=m['host'], port=int(m.get('port', 3306)),
                         user=m['user'], password=m['password'], connect_timeout=10)
    ts = cfg['timescaledb']
    pg = psycopg.connect(host=ts['host'], port=5432, dbname=ts['database'], user=ts['user'],
                         password=ts['password'], options='-c client_encoding=UTF8')

    failures = 0
    for pair in spec['pairs']:
        md, tsd = pair['mariadb'], pair['timescaledb']
        db = contract_db(md['contract'], md['object'], today)
        tables = monthly_tables(md['object'], since.date(), today)

        # MariaDB : comptes par (station, jour) sur la fenêtre — garde-fou index
        mc = my.cursor()
        mc.execute("""SELECT COUNT(*) FROM information_schema.statistics
                      WHERE table_schema=%s AND table_name=%s AND column_name=%s
                        AND seq_in_index=1""", (db, tables[-1], md['time']))
        if not mc.fetchone()[0]:
            print(f"⚪ {pair['name']} — {db}.{tables[-1]}.{md['time']} non indexée, "
                  f"check sauté (full scan évité)")
            continue
        maria = {}
        for tbl in tables:
            mc.execute("""SELECT COUNT(*) FROM information_schema.tables
                          WHERE table_schema=%s AND table_name=%s""", (db, tbl))
            if not mc.fetchone()[0]:
                continue
            mc.execute(
                f"SELECT `{md['key']}`, DATE(`{md['time']}`), COUNT(*) "
                f"FROM `{db}`.`{tbl}` WHERE `{md['time']}` >= %s GROUP BY 1, 2", (since_str,))
            for stn, day, n in mc.fetchall():
                maria[(stn, str(day))] = maria.get((stn, str(day)), 0) + n

        # TimescaleDB : comptes par (station, jour) sur la fenêtre
        pc = pg.cursor()
        pc.execute(
            f'SELECT "{tsd["key"]}", date_trunc(\'day\', "{tsd["time"]}")::date, COUNT(*) '
            f'FROM public."{tsd["object"]}" WHERE "{tsd["time"]}" >= %s GROUP BY 1, 2', (since_str,))
        timescale = {(stn, str(day)): n for stn, day, n in pc.fetchall()}

        maria_stations = {s for s, _ in maria}
        ts_stations = {s for s, _ in timescale}
        common_stations = maria_stations & ts_stations
        coverage = 100.0 * len(common_stations) / len(ts_stations) if ts_stations else 0.0

        # écarts de comptes sur les (station, jour) communs
        common_keys = set(maria) & set(timescale)
        tol = pair.get('max_count_delta_pct', 5)
        out_of_tol = []
        for k in common_keys:
            a, b = maria[k], timescale[k]
            ref = max(a, b)
            if ref and 100.0 * abs(a - b) / ref > tol:
                out_of_tol.append((k, a, b))

        floor = pair.get('min_coverage_pct', 80)
        cov_ok = coverage >= floor
        tag = '🟢' if cov_ok and not out_of_tol else '🔴'
        print(f"{tag} {pair['name']} (fenêtre {window.days} j) — "
              f"MariaDB {len(maria_stations)} stations / TimescaleDB {len(ts_stations)} / "
              f"communes {len(common_stations)}")
        print(f"     couverture MariaDB ÷ TimescaleDB : {coverage:.1f} % "
              f"(plancher {floor} %){'' if cov_ok else '  🔴 fallback sous-alimenté'}")
        if out_of_tol:
            print(f"     {len(out_of_tol)} (station, jour) communs hors tolérance {tol} % "
                  f"(ex. {out_of_tol[0][0]}: MariaDB {out_of_tol[0][1]} vs TS {out_of_tol[0][2]})")
        if not cov_ok or out_of_tol:
            failures += 1

    my.close()
    pg.close()
    if failures and '--check' in argv:
        print(f"\n{failures} appariement(s) hors critères.", file=sys.stderr)
        return 1
    print(f"\n{len(spec['pairs'])} appariement(s), {failures} hors critères.")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
