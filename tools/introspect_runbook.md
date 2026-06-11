# Runbook introspection prod (lecture seule) — inventaire 2026-06

Toutes les commandes sont en LECTURE SEULE. Utiliser des comptes MariaDB/PostgreSQL en
lecture seule. En cas d'erreur d'accès, rien n'est modifié.

Hôtes confirmés (cf. `inventory/storage-systems.yaml`) :
MariaDB = `ct-mariadb-1` (alias DNS `mariadb-master`) ;
TimescaleDB = `ct-timescale` (database `postgres`) ;
montages = la vue datastore et la vue modeles (détail des points de montage en interne).

Destinations des sorties (cf. READMEs `audits/` et `schemas/`) :
- volumétrie → `audits/volumetrie/` (série récurrente)
- DDL → `schemas/{mariadb,timescaledb}/schema.sql.gz` (fichier courant, historique git)
- vérité hôtes (crontabs, montages, notes) → `audits/inventaire-<AAAA-MM>/introspection/` (brut conservé en interne, non publié dans ce repo)

## 1. Inventaire tables + volumétrie (MariaDB + TimescaleDB)

```bash
cd tools
cp .env.ini.template .env.ini   # renseigner les accès LECTURE SEULE
python3 volumetrie_audit.py     # écrit dans ../audits/volumetrie/ par défaut
```

Sortie attendue : `inventaire-AAAAMMJJ.csv` (une ligne par table :
`system,database,table,row_estimate,data_bytes,index_bytes,total_bytes,extra`)
+ résumé markdown. Ce CSV est l'entrée de `reconcile.py` (réconciliation).

> Alternative sans compte dédié : via une console SQL d'administration, exécuter la requête
> information_schema de `volumetrie_audit.py` et exporter le résultat en CSV
> (fait ainsi le 2026-06-07).

## 2. Snapshots DDL (sans données)

```bash
# MariaDB — depuis un hôte ayant accès à ct-mariadb-1 (mariadb-master) :
mysqldump --host=mariadb-master --user=audit_readonly --password \
  --no-data --skip-lock-tables --skip-add-drop-table --all-databases \
  --result-file=schema.sql
gzip -9 -n schema.sql && mv schema.sql.gz ../schemas/mariadb/

# TimescaleDB — depuis ct-timescale ou un hôte y accédant :
pg_dump --host=ct-timescale --username=audit_readonly --dbname=postgres \
  --schema-only --no-owner --no-privileges --file=schema.sql
gzip -9 -n schema.sql && mv schema.sql.gz ../schemas/timescaledb/
```

Le `schema.sql.gz` **remplace** le précédent (un commit par snapshot, diff via git —
voir `schemas/README.md`). `gzip -n` obligatoire : fichier stable si le DDL n'a pas bougé.

## 3. Catalogue TimescaleDB (hypertables, aggregates, policies)

```bash
psql --host=ct-timescale --username=audit_readonly --dbname=postgres \
  -P pager=off -o timescale-catalog-$(date +%Y%m%d).txt <<'SQL'
SELECT hypertable_schema, hypertable_name, num_chunks,
       pg_size_pretty(hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass))
FROM timescaledb_information.hypertables ORDER BY hypertable_name;
SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates;
SELECT application_name, schedule_interval, proc_name FROM timescaledb_information.jobs;
SELECT matviewname, pg_size_pretty(pg_total_relation_size(format('%I.%I', schemaname, matviewname)::regclass))
FROM pg_matviews ORDER BY matviewname;
SQL
```

NB : la dernière requête liste les vues matérialisées classiques (mv_records_battus,
mv_quotidienne_realtime…) rafraîchies par les flows Kestra dataclimat.

## 4. Crontabs réels (vérité prod vs repo cron-infoclimat)

```bash
# Sur CHAQUE hôte (srx-data-2, front2, srx-nginx-2, srx-modeles-2, srx-mysql-3,
# srx-mapserver-2, et tout hôte suspect d'avoir un crontab non versionné) :
(hostname; crontab -l) > crontab-reel-$(hostname)-$(date +%Y%m%d).txt
# + crontabs système éventuels :
ls /etc/cron.d/ && tail -n +1 /etc/cron.d/* > crond-$(hostname)-$(date +%Y%m%d).txt
```

Point d'attention particulier : le crontab du repo `site-infoclimat/cron/crontab`
semble très legacy — préciser de quel serveur il provient et
s'il tourne encore.

## 5. Montages data

```bash
cd tools
./datastore_inventory.sh <montage-datastore> sortie-datastore-$(date +%Y%m%d).txt
./datastore_inventory.sh <montage-modeles>  sortie-modeles-$(date +%Y%m%d).txt
# Optionnel mais utile (des références au montage legacy fs1 existent côté mapserver) :
./datastore_inventory.sh <montage-fs1> sortie-fs1-$(date +%Y%m%d).txt
```

## 6. Dépôt des résultats

```bash
# volumétrie (déjà fait par l'outil) : audits/volumetrie/inventaire-*.csv|.md
# vérité hôtes : audits/inventaire-<AAAA-MM>/introspection/
#   → timescale-catalog-*.txt, crontab-reel-*.txt, crond-*.txt, sortie-*.txt
# DDL : schemas/{mariadb,timescaledb}/schema.sql.gz
```

Une fois déposé, prévenir : la réconciliation (`reconcile.py`) consomme
`audits/volumetrie/inventaire-*.csv` + `inventory/tables.yaml`, et le diff
crontabs réels vs repo `cron-infoclimat` met à jour `inventory/pipelines.yaml`.
