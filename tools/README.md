# Outillage data-platform

Deux familles d'outils, selon qu'ils ont besoin ou non d'accéder aux bases de
production.

## Contrôles statiques — tournent en CI GitHub (sans accès base)

| Outil | Rôle |
|---|---|
| `datacontract lint` | Validité ODCS des contrats (`contracts/*.odcs.yaml`) |
| `build_rgpd_register.py --check` | Cohérence du registre RGPD avec l'inventaire |
| `pytest tests/` | Tests de `reconcile.py` |

Ils ne touchent aucune donnée et s'exécutent sur chaque commit
(`.github/workflows/ci.yml`).

## Contrôles de production — tournent depuis le réseau interne

GitHub n'atteint pas les bases (réseau privé). Ces contrôles s'exécutent depuis le
réseau interne (ou via VPN), avec le compte **lecture seule** renseigné dans
`tools/.env.ini` (jamais committé). Ils ont vocation à devenir un job interne
récurrent (cron / Kestra) qui publiera son résultat.

| Outil | Rôle | Sûreté prod |
|---|---|---|
| `test_contracts.sh <contrat…>` | `datacontract test` complet contre TimescaleDB | scanne les tables — réservé à TimescaleDB |
| `check_schema_mariadb.py` | Présence + type des colonnes vs `information_schema` | métadonnées seules — sûr partout |
| `check_freshness.py [--check]` | Fraîcheur : `now - MAX(colonne)` vs seuil des cibles | saute les colonnes MariaDB non indexées (pas de full scan) |
| `check_license_conformity.py [--check]` | Domaine du champ `static.licence` + distribution | un `GROUP BY` sur un référentiel |
| `check_dual_source.py [--check]` | Couverture/comptes MariaDB ↔ TimescaleDB par station/jour (cibles `audits/dual-source-targets.yaml`) | 2 agrégats bornés par fenêtre, colonnes indexées des deux côtés |
| `volumetrie_audit.py` | Inventaire de volumétrie des bases | lecture `information_schema` |

Prérequis Python : `pip install pymysql 'psycopg[binary]' pyyaml 'datacontract-cli[postgres,mysql]'`.

### Pièges connus

- La base TimescaleDB est en encodage **SQL_ASCII** : forcer `PGCLIENTENCODING=UTF8`
  (déjà fait par les scripts), sinon les noms reviennent en `bytes`.
- `datacontract test` **scanne les données** : utilisable sur TimescaleDB, mais pas
  sur le master MariaDB de production (timeout / charge) → `check_schema_mariadb.py`
  fait l'équivalent métadonnées-seules pour MySQL.
- Les seuils et cibles de fraîcheur sont dans `audits/freshness-targets.yaml`.
