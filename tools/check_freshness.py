#!/usr/bin/env python3
"""Contrôle de fraîcheur des données contre la production.

Rend vérifiables les SLA `frequency` des contrats : pour chaque cible de
`audits/freshness-targets.yaml`, calcule `now_utc - MAX(colonne)` et compare au
seuil déclaré.

PROD-SAFE :
- MariaDB : la colonne doit être indexée en tête (information_schema.statistics,
  seq_in_index=1), sinon le MAX serait un full scan → la cible est sautée (⚪) ;
- TimescaleDB : viser la colonne de partitionnement (MAX par exclusion de chunks).

Garde-fou : chaque cible doit référencer un objet existant d'un contrat (sinon
échec). Templates `{AAAA}/{MM}/d{1|2|3}` concrétisés sur la date courante.

Usage : python3 tools/check_freshness.py [--check]
  --check : code de sortie 1 si une cible est en retard (pour la CI / un cron).
Prérequis : tools/.env.ini (sections [mariadb] et [timescaledb]),
            pip install pymysql 'psycopg[binary]' pyyaml.
"""
from __future__ import annotations

import configparser
import datetime
import glob
import re
import sys

import yaml

TARGETS = 'audits/freshness-targets.yaml'


def parse_threshold(s: str) -> datetime.timedelta:
    m = re.fullmatch(r'(\d+)\s*([hd])', s.strip())
    if not m:
        raise ValueError(f"seuil invalide : {s!r} (attendu Nh ou Nd)")
    n, unit = int(m.group(1)), m.group(2)
    return datetime.timedelta(hours=n) if unit == 'h' else datetime.timedelta(days=n)


def concretize(name: str, today: datetime.date) -> str:
    """Réduit un nom d'objet (éventuellement template) au nom de table physique."""
    base = name.split(' (')[0]  # retire la parenthèse explicative "(bases ...)"
    base = base.replace('{MM}', f'{today.month:02d}').replace('{AAAA}', str(today.year))
    base = re.sub(r'd\{1\|2\|3\}', f'd{min((today.day - 1) // 10 + 1, 3)}', base)
    return base


def contract_object_dbs(today: datetime.date) -> dict:
    """(contract_id court, objet) -> (server_type, database, physicalName)."""
    out = {}
    for f in glob.glob('contracts/*.odcs.yaml'):
        if '_template' in f:
            continue
        c = yaml.safe_load(open(f))
        cid = c['id'].split(':')[-1]
        srv = (c.get('servers') or [{}])[0]
        default_db = (srv.get('database') or '').replace('{AAAA}', str(today.year))
        for o in c.get('schema', []):
            key = o.get('physicalName') or o['name']
            db = default_db
            for p in o.get('customProperties', []) or []:
                if p.get('property') == 'physicalDatabase':
                    db = str(p['value']).replace('{AAAA}', str(today.year))
            out[(cid, key)] = (srv.get('type'), db, key)
    return out


def main(argv: list[str]) -> int:
    cfg = configparser.ConfigParser()
    cfg.read('tools/.env.ini')
    today = datetime.date.today()
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    catalog = contract_object_dbs(today)
    targets = yaml.safe_load(open(TARGETS))['targets']

    my = pg = None
    stale = 0
    for t in targets:
        ref = (t['contract'], t['object'])
        if ref not in catalog:
            print(f"🔴 cible inconnue des contrats : {t['contract']} / {t['object']}",
                  file=sys.stderr)
            return 1
        stype, db, _ = catalog[ref]
        table = concretize(t['object'], today)
        col = t['column']
        thr = parse_threshold(t['threshold'])
        label = f"{t['contract']} · {table}.{col}"

        if stype == 'mysql':
            import pymysql
            if my is None:
                m = cfg['mariadb']
                my = pymysql.connect(host=m['host'], port=int(m.get('port', 3306)),
                                     user=m['user'], password=m['password'], connect_timeout=10)
            cur = my.cursor()
            cur.execute("""SELECT COUNT(*) FROM information_schema.statistics
                           WHERE table_schema=%s AND table_name=%s AND column_name=%s
                             AND seq_in_index=1""", (db, table, col))
            if not cur.fetchone()[0]:
                print(f"⚪ {label} — colonne non indexée, check sauté (full scan évité)")
                continue
            cur.execute(f"SELECT MAX(`{col}`) FROM `{db}`.`{table}`")
            last = cur.fetchone()[0]
        elif stype == 'postgres':
            import psycopg
            if pg is None:
                p = cfg['timescaledb']
                pg = psycopg.connect(host=p['host'], port=5432, dbname=p['database'],
                                     user=p['user'], password=p['password'],
                                     options='-c client_encoding=UTF8')
            cur = pg.cursor()
            cur.execute(f'SELECT MAX("{col}") FROM public."{table}"')
            last = cur.fetchone()[0]
        else:
            print(f"⚪ {label} — type serveur {stype} non géré")
            continue

        if last is None:
            print(f"🔴 {label} — table vide ou MAX nul")
            stale += 1
            continue
        if isinstance(last, datetime.date) and not isinstance(last, datetime.datetime):
            last = datetime.datetime.combine(last, datetime.time())
        lag = now - last
        ok = lag <= thr
        if lag.total_seconds() < 0:
            human = "à jour (horodatage en avance)"
        else:
            secs = int(lag.total_seconds())
            human = f"{secs // 86400}j {secs % 86400 // 3600}h" if secs >= 86400 else f"{secs // 3600}h{secs % 3600 // 60:02d}"
        print(f"{'🟢' if ok else '🔴'} {label} — retard {human} (seuil {t['threshold']})")
        if not ok:
            stale += 1

    if my:
        my.close()
    if pg:
        pg.close()
    if stale and '--check' in argv:
        print(f"\n{stale} cible(s) en retard.", file=sys.stderr)
        return 1
    print(f"\n{len(targets)} cibles, {stale} en retard.")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
