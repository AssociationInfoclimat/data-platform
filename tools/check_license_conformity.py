#!/usr/bin/env python3
"""Conformité du modèle de licence opendata (référentiel stations StatIC).

L'exposition opendata des stations dépend du champ `V5_data_params.static.licence`,
défini par le propriétaire de chaque station :
  0 = Licence Ouverte (Etalab)   2 = non commerciale uniquement
  1 = commerciale autorisée      3 = fermée (jamais exposée)
  NULL = non renseignée → exclue de l'opendata (défaut fermé).

Le filtre d'export sélectionne `licence <= seuil`. Une valeur hors domaine {0,1,2,3}
y produirait un comportement imprévisible : ce contrôle valide le domaine et publie
la distribution (transparence + signal de gouvernance sur les stations non exposées).

PROD-SAFE : un seul GROUP BY sur le référentiel `static` (~2 300 lignes).

Usage : python3 tools/check_license_conformity.py [--check]
  --check : code 1 si une valeur hors domaine est trouvée.
Prérequis : tools/.env.ini (section [mariadb]), pip install pymysql.
"""
from __future__ import annotations

import configparser
import sys

import pymysql

KNOWN = {0: 'Etalab (ouverte)', 1: 'commerciale', 2: 'non commerciale', 3: 'fermée'}


def main(argv: list[str]) -> int:
    cfg = configparser.ConfigParser()
    cfg.read('tools/.env.ini')
    m = cfg['mariadb']
    conn = pymysql.connect(host=m['host'], port=int(m.get('port', 3306)),
                           user=m['user'], password=m['password'], connect_timeout=10)
    cur = conn.cursor()
    cur.execute("SELECT licence, COUNT(*) FROM V5_data_params.static GROUP BY licence")
    rows = cur.fetchall()
    conn.close()

    total = sum(n for _, n in rows)
    unknown = [(v, n) for v, n in rows if v is not None and v not in KNOWN]
    null_count = next((n for v, n in rows if v is None), 0)

    print(f"Référentiel stations : {total} entrées")
    for v, n in sorted(rows, key=lambda r: (r[0] is None, r[0])):
        label = 'NULL → exclue de l\'opendata' if v is None else KNOWN.get(v, '⚠️ HORS DOMAINE')
        exposed = '' if v is None or v == 3 else ' (exposable)'
        print(f"  licence={str(v):>4} : {n:>5}  {label}{exposed}")

    if null_count:
        pct = round(100 * null_count / total)
        print(f"\nℹ️  {null_count} stations ({pct}%) sans licence renseignée → invisibles à "
              f"l'opendata. Signal de gouvernance : à proposer aux propriétaires.")

    if unknown:
        print("\n🔴 Valeurs de licence hors domaine {0,1,2,3} :", file=sys.stderr)
        for v, n in unknown:
            print(f"  licence={v} : {n} stations", file=sys.stderr)
        return 1
    print("\n🟢 Domaine de licence conforme (toutes les valeurs dans {0,1,2,3} ou NULL).")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
