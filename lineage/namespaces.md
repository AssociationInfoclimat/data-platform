# Conventions OpenLineage Infoclimat

Conventions de nommage des namespaces, datasets et jobs pour les RunEvents OpenLineage.
Implémentation cible : emitter PHP `include/communs/Lineage/` (écriture JSONL locale,
jamais bloquante) + forwarder `tools/lineage_forward.py` → backend Marquez self-hosted.

## Namespaces de datasets

| Namespace | Système | Exemples de datasets |
|---|---|---|
| `mariadb://V5` | MariaDB base V5 | `temps_calme`, `comptes` |
| `mariadb://V5_data_params` | MariaDB référentiels | `static`, `stations` |
| `mariadb://V5_data_{AAAA}` | MariaDB séries StatIC | `static_03_d2` |
| `mariadb://V5_climato` | MariaDB climatologie | `climato_journaliere_auto` |
| `mariadb://mf_data` | MariaDB données MF (fallback) | `mf_data` |
| `timescaledb://infoclimat` | TimescaleDB | `Infrahoraire`, `InfrahoraireTempsReel`, `Horaire` |
| `file://datastore` | Stockage fichiers partagé (datastore) | `tiles/...`, `opendata/exports/...` |
| `file://srx-modeles-2` | Chemins host-locaux srx-modeles-2 | `modeles/AROME/`, `modeles/GFS/` |
| `file://modeles` | Vue NFS du stockage modèles | `modeles.infoclimat.net` |
| `file://front2` | Chemins locaux front2 (legacy) | `/dev/shm/cache/MeteoAlerte/`, `webroot/meteoalerte/cache/` |
| `sphinx://` | Index de recherche Sphinx | `infoclimat_stations`, `infoclimat_forums` |
| `api://meteofrance` | Sources externes | `paquets-observations`, `fichiers-climatologiques` |

> **Note** : les namespaces `file://srx-modeles-2` et `file://front2` sont des chemins
> host-locaux transitoires. srx-modeles-2 stocke les modèles NWP en local (non monté sur
> datastore). front2 est un hôte legacy en cours de remplacement (migration vers nginx2/Kestra) — ses
> datasets fichiers locaux seront déplacés vers `file://datastore` à terme.

## Jobs

| Namespace de job | Convention | Exemples |
|---|---|---|
| `cron://infoclimat` | `cron.<nom_du_script>` | `cron.load_data_mf`, `cron.climato_annuelle`, `cron.recup_metars` |
| `kestra://infoclimat` | `<namespace_flow>.<nom_flow>` | `data.meteofrance.vigilance`, `db.dataclimat.refresh-materialized-views` |
| `api://infoclimat` | `<section>.<action>` | `opendata-v2.export`, `mobile-api.station` |
| `webhook://infoclimat` | `<reseau>.uplink` | `liveobjects.uplink`, `ttn.uplink` |
| `daemon://infoclimat` | `<service>.<role>` | `station-autonome.udp-server`, `python-climate-services.pluviometrie` |

## Règles

1. Un RunEvent `START` + un `COMPLETE` (ou `FAIL`) par exécution de pipeline ; `runId` UUIDv4
   unique par exécution.
2. `inputs`/`outputs` listent les datasets aux noms physiques réels (table, fichier).
   Dans les registres publiés, les préfixes système (docroot, points de montage) sont
   abstraits (`webroot/`, `modeles/`, `datastore:/`) — la correspondance exacte est tenue en interne.
3. L'émission ne doit JAMAIS bloquer ni faire échouer le pipeline (append fichier local,
   forwarding asynchrone).
4. Le champ `producer` vaut `https://github.com/infoclimat/site-infoclimat` (versionné).
5. Les pipelines contractualisés référencent leur job via la customProperty `lineageJob`
   du contrat ODCS.

## Pipelines prioritaires à instrumenter

1. Ingestion MF → TimescaleDB (`include/MeteoFrance/load_data.php`)
2. METAR/SYNOP (`data/metars_synops/`)
3. Agrégats climato (`cron/climato*.php`)
4. Exports opendata (`opendata-v2/`)
