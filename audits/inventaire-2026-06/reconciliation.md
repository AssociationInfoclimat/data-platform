# Bilan de réconciliation — inventaire data 2026-06

Audit mené du 2026-06-05 au 2026-06-09 en trois temps : inventaire côté code
(23 repos balayés), introspection de production en lecture seule (MariaDB le
2026-06-07, TimescaleDB le 2026-06-09), puis réconciliation code ↔ bases via
`tools/reconcile.py` (rapports bruts : `reconcile-output-20260607.md` et
`reconcile-output-20260609.md`).

## Couverture des repos

| Repo                      | Méthode                     | Balayé |
|---------------------------|-----------------------------|--------|
| site-infoclimat           | profond (pipelines + R/W)   | ☑      |
| cron-infoclimat           | profond (déclencheurs)      | ☑      |
| infrapilot                | profond (Kestra, topologie) | ☑      |
| modeles-ncl               | profond (pipelines)         | ☑      |
| modeles-php               | profond (pipelines)         | ☑      |
| python-climate-services   | profond (daemons + R/W)     | ☑      |
| serveur-station-autonome  | profond (daemon)            | ☑      |
| ipboard-infoclimat        | léger (R/W forums2)         | ☑      |
| sphinx-docker             | léger (indexation)          | ☑      |
| evote                     | léger                       | ☑      |
| nginx-config              | topologie (indices legacy)  | ☑      |
| dev-env                   | topologie                   | ☑      |
| php-fpm-7_4               | topologie (montages)        | ☑      |
| php-fpm-7_4-timescale-api | topologie (accès TS)        | ☑      |
| mapserver                 | léger (lecteur tuiles)      | ☑      |
| cron site (cron/crontab)  | profond                     | ☑      |
| plugins-munin             | N-A justifié (monitoring)   | ☑      |
| Documentation             | indices                     | ☑      |
| site-infoclimat-tests     | N-A justifié (tests)        | ☑      |
| appli-ios                 | léger (API only)            | ☑      |
| appli-android             | léger (API only)            | ☑      |
| infoclimat-nestjs-backend | N-A (vide)                  | ☑      |
| infoclimat-vue3-frontend  | N-A (vide)                  | ☑      |
| climate-services-docker   | N-A (vide)                  | ☑      |

## Chiffres clés (côté code, clôture 2026-06-05)

| Périmètre | Compte |
|---|---|
| Pipelines inventoriés (total) | 325 |
| Pipelines actifs | 231 |
| Pipelines douteux | 80 |
| Pipelines morts | 14 |
| Tables référencées (MariaDB + TimescaleDB + Sphinx) | 219 |
| Datasets fichiers (datastore, NFS, srx-modeles-2) | 104 |
| Sources externes (api://) | 85 |
| Systèmes de stockage inventoriés | 11 |
| Datasets catalogués (catalog.yaml) | 19 |

Détail des 325 pipelines par déclencheur : 68 flows Kestra, 65 crontab site,
79 crontab srx-data-2, 34 crontab srx-front-2, 32 crontab srx-nginx-2,
26 crontab srx-modeles-2, 8 crontab srx-mapserver-2, 2 crontab srx-mysql-3,
14 webhooks/daemons/handlers HTTP — chaque source rapprochée ligne à ligne de
son compteur attendu, sans écart inexpliqué.

## Réconciliation MariaDB (2026-06-07)

| Mesure                                   | Valeur                                       |
|------------------------------------------|----------------------------------------------|
| Tables prod appariées au code            | 15 671                                       |
| Fantômes (code → absente en base)        | 59 brut → **6 réels MariaDB**                |
| Orphelines (en base, jamais référencées) | 4 621 (quasi toutes des familles dynamiques) |

### Fantômes — 59 bruts, décomposés

- **24 `sphinx://`** + **16 `timescaledb://`** : systèmes non encore introspectés
  à cette date → indéterminés (tranchés le 2026-06-09 pour TimescaleDB, voir plus bas).
- **11 `forums`/`forums2`** : ces bases n'existent pas sur mariadb-master — la BDD
  IPBoard vit sur un hôte dédié distinct (hors périmètre) → indéterminés.
- **8 doublons `mariadb://V5/*` arbitrés** : des entrées de tables.yaml
  (satellites, vigilance_direct, vigilances_mf, bulletins_speciaux_suivi, historic_*)
  dupliquaient sous `V5` des tables ré-attribuées. La prod tranche : elles existent
  uniquement sous `V5_climato`, `data_cartes` et `V5_chroniques` → les 8 doublons
  `V5/*` ont été supprimés de tables.yaml.
- **6 fantômes réels** (code → table morte, candidats code mort) :
  `concoursprevi/participants_v5`, `concoursprevi/participations_sondages`
  (prod ne contient que `pronos` + `manches`), `data_cartes/cartes`,
  `data_cartes/cartes_zooms`, `alerte/vigi_mf` (base `alerte` inexistante —
  cohérent avec `cron/vigi_mf.php` mort mais encore schedulé sur nginx2),
  `reseau/stations` (base `reseau` inexistante ; ne pas confondre avec
  `reseau_mf`, qui existe mais est **vide**).

### Les 25 tables `douteux` statuées

- **21 confirmées existantes** en prod (apns_*, boutique*, electric_*, gcm_*,
  recherches_index, vigilance_direct_demo, mf_data, bouees_bateaux, ag_live*,
  mantis_bug_table, mod_stations, ressources_sci_*) → statut `actif` (existence) ;
  l'usage réel (writers vivants) reste à confirmer par la vérité terrain des hôtes.
- **3 mortes** : `concoursprevi/participations_sondages` (table absente),
  `reseau/stations` et `alerte/vigi_mf` (bases absentes) → statut `mort`.
- **1 hors-scope** : `sphinx://internal` (Sphinx non introspecté) → reste `douteux`.

### Orphelines — 4 621, en quasi-totalité des familles à nommage dynamique

L'analyse statique (tables.yaml = noms littéraux) ne voit pas les tables
construites par le code (`{base}_{annee}`, `{table}_{mois}_d{decade}`…) :

| Famille | Volume approx. | Lecture |
|---|---|---|
| `V5_data_{1921-2030}/mae_MM_dN`, `test_stations_autonomes_MM_dN`, `synop/static_*_bak` | ~3 700 | partitions mensuelles/décadaires ; `mae_*` (météo à l'école ?) et `test_*` à statuer ; `*_bak` purgeable |
| `data_geo/geoNames_{XX}` (1 table par pays) + villes/regions/pays | 263 | référentiel geonames, lectures dynamiques probables |
| `V5_climato/eca_{TX,TN,RR}_{PAYS}` | 77 | ECA&D par pays (le code ne référence que `eca_data`) |
| `meteo_a_l_ecole{,_2}/*` | 83 | espace appli MAE, hors périmètre code balayé |
| `weewx/*` | 53 | base alimentée hors monolithe (weewx) |
| `V5_climato_noaa/*` | 41 | ingestion NOAA, writers à tracer |
| divers (hackaton_esgi_*, V5_photolive, etc.) | ~400 | dont bases tierces et reliquats |

Gros poissons côté volumétrie à recouper avec ces orphelines :
`V5.foudrebak*` (~31 Go de backups morts), bases `V5_data_2027-2030`
pré-créées, `hackaton_esgi_groupe01-20` (~12 Go au total).

## Réconciliation TimescaleDB (2026-06-09)

Re-réconciliation sur CSV combiné (`inventaire-20260607.csv` MariaDB +
`inventaire-timescaledb-20260609.csv`) → `reconcile-output-20260609.md`.
Après corrections (label, familles, socle dataclimat) : **19 735 appariées,
36 fantômes, 594 orphelines** (contre 4 643 avant l'ajout des motifs « famille »).

**Label base corrigé `infoclimat` → `postgres`** : tables.yaml et `storage-systems.yaml`
nommaient la base `infoclimat`, mais la base physique est **`postgres`** (schéma `public`) —
aucune base `infoclimat` n'existe sur `ct-timescale`. Les 17 réfs `timescaledb://infoclimat/`
ont été réécrites en `timescaledb://postgres/` et le CSV de volumétrie remis sur le nom physique.

- **15 des 16 réfs `timescaledb://` existent** → appariées.
- **1 fantôme assumé** : `timescaledb://postgres/mv_records_battus_realtime` — **pas du code mort** :
  matview **planifiée mais pas encore créée**, référencée par le **client** DataForGood
  (`dataforgoodfr/14_ValorisationDonneeMeteo`, « path is not developed for now »). Statut `douteux`,
  repassera `actif` à la création.
- **22 ex-orphelines Timescale → 0** : ajoutées à tables.yaml comme **socle dataclimat**
  (tables station/IoT, matviews intermédiaires, `_prisma_migrations`, `station_creation_date_bak`).
  Ce socle est de l'**infra infoclimat** (alimentation ingestion + refresh Kestra hors monolithe) ;
  DataForGood en est un **client** (consommateur), pas la source.

**Familles dynamiques MariaDB** (réduction des orphelines structurelles, +token `{XX}`=code 2 lettres) :
ajout de `V5_data_{AAAA}/mae_{MM}_d{1-3}` (~3 600 tables, le gros du volume),
`…/test_stations_autonomes_*`, `…/profiles`, `…/acars`, `…/{synop,static}_*_bak`,
`data_geo/geoNames_{XX}` (~250) et `V5_climato/eca_{XX}_{XX}` (~70). **Orphelines 4 643 → 594.**
Les 594 restantes = bases d'apps tierces/ingestions hors monolithe (`weewx`, `meteo_a_l_ecole{,_2}`,
`V5_climato_noaa`), littéraux référentiels et reliquats — légitimement non référencées par le code.

> Les **11 fantômes `forums/*` (IPBoard)** restent listés mais **hors périmètre** (décision 2026-06-09 :
> techno propriétaire à gestion DB autonome). Les **18 `sphinx://`** sont des index plein-texte Sphinx,
> non réconciliables contre une volumétrie DB. Reste donc **6 fantômes MariaDB réels** comme code mort
> probable (+ 1 Timescale assumé, réf anticipée d'un client).

## Constats transverses

- **Migration Kestra en cours** : 34 pipelines cron srx-front-2 et 32 cron
  srx-nginx-2 sont des doublons de flows Kestra identifiés (+ 6 doublons
  srx-data-2) — l'hôte legacy front2 est en cours de remplacement. La migration est
  partiellement effectuée, et bidirectionnelle par endroits (flows forecast.*
  GFS/ECMWF/GEM désactivés côté Kestra au profit de crons).
- **Code mort documenté** : 14 pipelines `status: mort` (flows Kestra
  `disabled: true`), dont recup-blitzortung (source fermée), compo-new-1
  (meteomedia), launch-data-recup (remplacé par Kestra), climato-portail-api
  horly, crons-v5-data.
- **80 pipelines douteux** : principalement cron site-legacy dont les scripts
  ne sont pas versionnés dans les repos. Leur existence réelle ne peut être
  confirmée que par la vérité terrain des hôtes.
- **Bases découvertes en cours d'audit** : `data_cartes`, `V5_chroniques`,
  `V5_photolive`, `concoursprevi`, `asso`, `V5_data_mf` — ajoutées à tables.yaml
  suite à l'analyse des connexions PHP.
- **I/O non traçables — images Docker privées** : 3 pipelines Kestra
  (download-convert-radar, calc-indicateur-realtime, calc-yearly-acc) utilisent
  des images ghcr.io privées ; les sous-chemins outputs ne sont pas visibles
  dans les flows — listés avec I/O vides, à documenter côté image Docker.
- **TimescaleDB** : 16 tables référencées par le monolithe (10 hypertables +
  6 vues matérialisées) — périmètre MF exclusivement. Pas d'ingestion StatIC
  en TimescaleDB.
- **Sphinx** : 18 index documentaires — aucun pipeline batch Infoclimat ne
  les écrit directement (indexation par l'indexer Sphinx dédié, hors pipelines du site).
- **Données personnelles** : 32 tables marquées `personal_data: true` dans
  tables.yaml — graine d'un registre RGPD à formaliser.
- **Rétentions partiellement connues** : connues pour les flux
  synop/metar/mf/static (30 j), les caches images (7-30 j) et les modèles NWP
  bruts (2 j). La majorité des tables MariaDB n'a pas de politique de purge
  documentée.

## Corrections appliquées aux registres

### 8 tables réattribuées à leur base réelle

Les tables ci-dessous étaient inventoriées sous `mariadb://V5/...` dans `pipelines.yaml`,
alors que leur writer réel ouvre une connexion vers une **autre** base.

Mécanisme de résolution des fonctions de connexion :

| Fonction | Fichier de définition | Comportement |
|---|---|---|
| `connexionSQL($db)` | `include/communs/connexion_sql.php:69` | `new PDO("mysql:host=...;dbname={$db}", ...)` — l'argument est le nom de base littéral |
| `get_utf8_pdo_connection($db)` | `include/communs/PDO/pdo_helper.php:50` | Délègue à `get_pdo_connection($db)` → `new PDO("mysql:host=...;dbname={$database_name}", ...)` — idem |

**Règle appliquée :** si l'INSERT/UPDATE est non qualifié (pas de `base.table`), la base est celle de la connexion (`dbname=`). Si l'instruction est qualifiée (`INSERT INTO base.table`), la base est celle du qualificateur.

| Table | Writer | Preuve (fichier:ligne) | Base erronée | Base réelle |
|---|---|---|---|---|
| `satellites` | `cron/sat_modis.php` | `connexionSQL('data_cartes')` — sat_modis.php:38 ; `INSERT INTO satellites(...)` sans qualificateur — l.47,63 | `mariadb://V5` | `mariadb://data_cartes` |
| `vigilance_direct` | `include/Vigilances/vigilances.php` | `get_utf8_pdo_connection('V5_climato')` — l.868,923 ; `DELETE/INSERT INTO vigilance_direct(...)` sans qualificateur — l.874,926 | `mariadb://V5` | `mariadb://V5_climato` |
| `vigilances_mf` | `include/Vigilances/vigilances.php` | `insert('V5_climato', ...)` — l.1777 (RealVigilancesMFInserter) ; `INSERT INTO vigilances_mf(...)` sans qualificateur — l.1779 | `mariadb://V5` | `mariadb://V5_climato` |
| `bulletins_speciaux_suivi` | `include/Vigilances/vigilances.php` | `get_utf8_pdo_connection('V5_chroniques')` — l.1681 ; `INSERT INTO bulletins_speciaux_suivi(...)` sans qualificateur — l.1684 | `mariadb://V5` | `mariadb://V5_chroniques` |
| `historic_events` | `cron/historic.php` | `connexionSQL('V5_climato')` — l.229 ; `UPDATE/SELECT historic_events` sans qualificateur — l.394,404 | `mariadb://V5` | `mariadb://V5_climato` |
| `historic_records_depts` | `cron/historic.php` | `connexionSQL('V5_climato')` — l.229 ; `TRUNCATE/INSERT INTO historic_records_depts` sans qualificateur — l.237,239 | `mariadb://V5` | `mariadb://V5_climato` |
| `historic_records_nationaux` | `cron/historic.php` | `connexionSQL('V5_climato')` — l.229 ; `TRUNCATE/INSERT INTO historic_records_nationaux` sans qualificateur — l.236,238 | `mariadb://V5` | `mariadb://V5_climato` |
| `historic_values` | `cron/historic.php` | `connexionSQL('V5_climato')` — l.229 ; `UPDATE historic_values` sans qualificateur — l.233-235,253,288 | `mariadb://V5` | `mariadb://V5_climato` |

19 occurrences corrigées en conséquence dans `pipelines.yaml` (flows Kestra
vigilance/maj-historic/sat-modis et leurs équivalents cron site-legacy,
front2, nginx2). Un échantillon de contrôle de 5 autres writers
`connexionSQL(arg ≠ 'V5')` n'a révélé aucune anomalie supplémentaire.

### Révision des I/O déduits plutôt que tracés

Suite à revue, ~13 entrées de `pipelines.yaml` dont les I/O avaient été déduits
par analogie ou nommage ont été corrigées : I/O vidés quand ils n'étaient pas
traçables (images Docker privées, scripts prod non versionnés — ex.
`analytics.*`, `backups.tiles-backup`, `climatologie-portail-api.*`), et I/O
précisés quand le script l'établissait (ex. `forecast.{ecmwf,gefs,gem,gemens,gfs}`
vers `file://srx-modeles-2/modeles/...`, source ARPA Piemonte réécrite sur
l'URL réelle). Les namespaces host-locaux `file://srx-modeles-2/...` sont à
officialiser dans `lineage/namespaces.md`.

## Reste à faire

- Statuer les 594 orphelines tierces (weewx/MAE/NOAA — owners externes) et les
  familles `douteux` (mae, test_*, profiles, acars) au gré des owners.
- Valider les contrats `draft` contre les DDL réels (export TimescaleDB complet).
- Repasser `mv_records_battus_realtime` en `actif` à sa création en base.
