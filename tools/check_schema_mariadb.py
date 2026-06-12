#!/usr/bin/env python3
"""Vérifie les contrats MariaDB contre la production — métadonnées uniquement.

Compare les colonnes déclarées dans les contrats ODCS (servers[0].type == mysql)
avec information_schema.columns : présence et famille de type. Aucune lecture de
données (sans danger pour le serveur de production), contrairement à
`datacontract test` dont les checks scannent les tables.

Conventions lues dans les contrats :
- objets `physicalType: files` : ignorés (pas de table à vérifier) ;
- customProperty d'objet `physicalDatabase` : base réelle quand elle diffère de
  servers[0].database (datasets multi-bases) ;
- noms templates (`static_{MM}_d{1|2|3} (bases V5_data_{AAAA})`) : concrétisés sur
  la date courante (année, mois, décade).

Usage : python3 tools/check_schema_mariadb.py [contracts/x.odcs.yaml ...]
        (sans argument : tous les contrats mysql)
Prérequis : tools/.env.ini (section [mariadb]), pip install pymysql pyyaml.
"""
from __future__ import annotations

import configparser
import datetime
import glob
import re
import sys

import pymysql
import yaml

TYPE_FAMILIES = {
    'int': ['int', 'bigint', 'smallint', 'tinyint', 'mediumint', 'integer'],
    'float': ['float', 'double', 'real', 'decimal', 'numeric'],
    'text': ['varchar', 'char', 'text', 'tinytext', 'mediumtext', 'longtext', 'string'],
    'datetime': ['datetime', 'timestamp', 'timestamptz'],
    'date': ['date'],
    'enum': ['enum'],
    'bool': ['bit', 'boolean'],
    'geo': ['point', 'geometry'],
    'time': ['time'],
}
FAM = {kw: fam for fam, kws in TYPE_FAMILIES.items() for kw in kws}


def family(t: str) -> str:
    base = re.match(r'[a-z]+', str(t).strip().lower())
    return FAM.get(base.group(0) if base else '', f'?{t}')


def concretize(name: str, today: datetime.date) -> str | None:
    """static_{MM}_d{1|2|3} → static_06_d2 (décade courante). None si non-template."""
    if '{' not in name:
        return name
    m = re.match(r'([a-z]+)_\{MM\}_d\{1\|2\|3\}', name)
    if m:
        decade = min((today.day - 1) // 10 + 1, 3)
        return f"{m.group(1)}_{today.month:02d}_d{decade}"
    m = re.match(r'([a-z_]+)_\{AAAA\}_\{MM\}', name)
    if m:
        return f"{m.group(1)}_{today.year}_{today.month:02d}"
    return None  # template non reconnu : signalé non testable


def template_db(db: str, today: datetime.date) -> str:
    return db.replace('{AAAA}', str(today.year))


def custom(obj: dict, prop: str):
    for p in obj.get('customProperties', []) or []:
        if p.get('property') == prop:
            return p.get('value')
    return None


def main(argv: list[str]) -> int:
    cfg = configparser.ConfigParser()
    cfg.read('tools/.env.ini')
    m = cfg['mariadb']
    conn = pymysql.connect(host=m['host'], port=int(m.get('port', 3306)),
                           user=m['user'], password=m['password'], connect_timeout=10)
    cur = conn.cursor()
    today = datetime.date.today()

    files = argv or sorted(glob.glob('contracts/*.odcs.yaml'))
    status = 0
    for path in files:
        if '_template' in path:
            continue
        c = yaml.safe_load(open(path))
        srv = (c.get('servers') or [{}])[0]
        if srv.get('type') != 'mysql':
            continue
        if srv.get('host') not in (None, '${DB_HOST}'):
            print(f"⚪ {path} — hôte distinct ({srv.get('host')}), non testé d'ici")
            continue
        default_db = template_db(srv.get('database', ''), today)
        findings, tested = [], 0
        for obj in c.get('schema', []):
            if obj.get('physicalType') == 'files':
                continue
            phys = obj.get('physicalName') or obj['name']
            db = template_db(custom(obj, 'physicalDatabase') or default_db, today)
            table = concretize(phys, today)
            if table is None:
                findings.append(f"{phys}: template non testable")
                continue
            cur.execute(
                "SELECT column_name, column_type FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s", (db, table))
            real = {r[0]: r[1] for r in cur.fetchall()}
            tested += 1
            if not real:
                findings.append(f"{db}.{table}: TABLE ABSENTE")
                continue
            for p in obj.get('properties', []) or []:
                n = p['name']
                if n not in real:
                    findings.append(f"{db}.{table}.{n}: colonne ABSENTE")
                elif family(p.get('physicalType', '')) != family(real[n]):
                    findings.append(
                        f"{db}.{table}.{n}: contrat={p.get('physicalType')} vs prod={real[n]}")
        tag = '🟢' if not findings else '🔴'
        if findings:
            status = 1
        print(f"{tag} {path} ({tested} objets vérifiés)")
        for f in findings:
            print(f"     {f}")
    conn.close()
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
