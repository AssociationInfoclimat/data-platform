# ADR-0007 — Serving chaud : le modèle canonique long sur Postgres/Timescale

- Statut : proposée
- Date : 2026-07-11
- Décideurs : data engineer (pam)

> Referme la boucle ouverte par ADR-0006 (qui repositionne TimescaleDB en
> « serving chaud, plus jamais archive ») : à quoi ressemble ce serving chaud
> refait à l'état de l'art, sans contrainte legacy. Source : étude compagnon
> « serving chaud » du 2026-07-11. S'appuie sur ADR-0004 (vocabulaire) et
> ADR-0005 (identité stations).

> **Amendée le 2026-07-11** (audit de traduisibilité legacy) : la table
> canonique `observation` — au chaud COMME au lakehouse (Silver) — gagne deux
> attributs optionnels issus des trous de modélisation identifiés :
> `dh_occurrence` et la position par observation (voir Décision §1bis).

## Contexte

Le TimescaleDB actuel (780 GiB) est un produit d'accrétion : 4 hypertables wide
Météo-France (~200 colonnes `PARAM`/`QPARAM`) aux identifiants et unités
divergents entre historique et temps réel, 12 matviews non versionnées
rafraîchies par Kestra, base en SQL_ASCII, compression jamais activée, et un
monolithe qui fusionne les 4 sources à chaque requête (FULL JOIN + COALESCE
dans `combined.php`). ADR-0006 lui retire le rôle d'archive ; reste à décider
le format du chaud (~2 ans glissants).

Profil de charge du serving, mesuré ou connu : point-lookups à la milliseconde
(« dernière obs », des milliers/min sur les pages), petites fenêtres récentes
par station, snapshots carte, upserts continus (flux 6 min, corrections de
modération, réémissions MF), agrégats quotidiens/mensuels temps réel, records.

## Décision

**Le chaud adopte le modèle canonique du lakehouse — la table `observation` au
format long (ADR-0004/0005) — sur Postgres/TimescaleDB, avec deux mécanismes
dédiés aux lectures à la milliseconde. Chaud et froid deviennent deux fenêtres
temporelles du même modèle logique.**

1. **Même modèle logique, deux moteurs.** Une hypertable `observation`
   (station_id int, dh_utc timestamptz, parametre_id smallint, duree_s, valeur,
   qc_flag smallint, version_obs, source_id), clés entières compactes issues
   des référentiels répliqués depuis le lakehouse (jamais édités à chaud).
   La fusion des sources est faite **une fois, à l'ingestion** — le FULL JOIN
   4 sources disparaît ; la frontière chaud/froid dans la couture `combined.php`
   (ADR-0006 §4) devient un prédicat de temps sur le même SQL.
1bis. **Deux attributs optionnels sur `observation`** (amendement 2026-07-11,
   valables au chaud ET en Silver — même modèle logique) :
   - **`dh_occurrence timestamptz NULL`** : heure/date d'occurrence d'un
     extrême ou d'un événement dans la période de la mesure (TN/HTN, TX/HTX,
     rafale/HXY, record de normale). NULL pour les mesures instantanées.
     Précédents : descripteurs associés BUFR/OMM, couples TN/HTN du wide MF,
     MIDAS Met Office. Colonne d'attribut plutôt que paramètre apparié : le
     couple (valeur, occurrence) reste insécable au QC et au filtrage.
   - **`lat float8 NULL, lon float8 NULL`** : position PAR observation pour
     les plateformes mobiles (bouées dérivantes, navires, demain AMDAR/ACARS).
     NULL = la position est celle de `dim_station`. Précédents : ICOADS
     (l'archive marine de référence stocke lat/lon par relevé), Argo,
     featureType `trajectory` des conventions CF. Les vues Gold exposent la
     **position effective** `COALESCE(obs.lat, station.lat)` pour des requêtes
     spatiales uniformes.
   Coût : colonnes creuses (NULL massivement dominant), négligeable en
   columnar compressé des deux côtés.
2. **Postgres/Timescale est conservé, par convergence et non par legacy.**
   Le profil (point-lookups, upserts, petites fenêtres) est le métier d'un
   Postgres, et ADR-0006 en fait déjà le protocole unique vers le froid — un
   seul dialecte, une opération mono-steward. ClickHouse est le challenger
   documenté, avec critère de réouverture explicite (voir Conséquences).
3. **Physique de la table** : chunks 7 jours ; Hypercore
   (`compress_segmentby = station_id, parametre_id`, `compress_orderby =
   dh_utc`) au bout de 7 jours — le long segmenté est le cas d'école de la
   compression Timescale (2-4 o/ligne attendus) ; **rétention 24 mois**
   (à calibrer sur la distribution réelle des fenêtres demandées), le lakehouse
   ayant l'intégralité. Cible : **20-40 GiB compressés** contre 780 GiB
   aujourd'hui.
4. **Les lectures milliseconde ne touchent jamais le long** :
   - `obs_last` (station × paramètre × durée → dernière valeur, ~1,6 M lignes,
     UPSERT à l'ingestion) : « dernière obs » = index scan &lt;1 ms — le chemin
     que la gateway froide sert en 215 ms au mieux (bench ADR-0006) ;
   - **continuous aggregates hiérarchiques temps réel** (`cagg_hourly_wide` —
     le wide redevient un dérivé, ici aussi — → `cagg_daily` tn/tx/rr/raf →
     `cagg_monthly`) : remplacent les 12 matviews + refresh Kestra — le P1 du
     plan BDD (`audits/bdd/`) prend cette forme définitive. Les records battus
     = `cagg_daily` × table des records synchronisée du lakehouse.
5. **Base neuve, pas de migration in place** : UTF-8 (l'actuelle est en
   SQL_ASCII), `timestamptz` UTC. **Trajectoire choisie par le CA
   (2026-07-11), pour minimiser la charge des développeurs** : le Timescale
   legacy reste la cible de l'ingestion actuelle et n'est PAS modifié ; un
   **pipeline de tail incrémental** micro-batch (~6 min) lit la fenêtre
   récente des 4 tables wide legacy (avec chevauchement de quelques heures
   pour les réémissions/corrections MF), convertit wide→long via le
   vocabulaire (ADR-0004) et le crosswalk (ADR-0005), et **UPSERT idempotent**
   dans le nouveau Timescale canonique. Pas de CDC Debezium/Kafka (déjà écarté
   au recadrage prestataire ; réplication logique piégeuse sur hypertables) —
   un watermark + fenêtre de relecture suffit sur des tables append-mostly à
   clés temporelles. Les pages basculent une à une ; readiness mesurée au
   pattern `check_dual_source` ; le jour où plus rien ne lit le wide, on coupe
   le tail et on adapte enfin l'ingestion (pointage direct sur le canonique) —
   c'est la DERNIÈRE étape, pas la première.
6. **Corrections = versions**, comme au lakehouse (`version_obs`, la vue de
   serving prend la dernière) ; l'`UPDATE qc_flag` reste toléré à chaud
   (pragmatisme modération) mais est répercaté au froid par le flux de
   synchronisation — **jamais l'inverse**.
7. **Un seul flux chaud → froid** : export quotidien des jours clos (J-2) vers
   Iceberg, idempotent (overwrite de partition), counts contrôlés. Le chaud
   n'est jamais une archive, le froid n'est jamais écrit à la main.

## Justification

- **Un seul modèle à maintenir** : vocabulaire, identité, QC et sémantique des
  durées sont définis une fois (ADR-0004/0005) et valent pour les deux moteurs ;
  plus aucune réconciliation de schémas chaud/froid, plus de piège d'unités.
- **Le long à chaud est éprouvé** : c'est le modèle « narrow » recommandé pour
  capteurs hétérogènes par Timescale même, et la sparsité des familles (2 à
  ~90 paramètres selon la source) le rend inévitable — le wide MF actuel le
  prouve par ses cimetières de NULL.
- **Les deux objections classiques au long à chaud tombent** avec les mécanismes
  dédiés : le point-lookup par `obs_last` (O(1)), le wide de page par les caggs
  (pré-pivotés, temps réel). Le long n'est le chemin de personne, il est la
  vérité de tous.
- **La volumétrie cesse d'être un sujet** : 20-40 GiB compressés tiennent en
  RAM d'un serveur modeste — les questions réplicas/capacité du dossier BDD
  changent d'échelle.

## Conséquences

- (+) `combined.php` se réduit à un routage temporel + un GROUP BY ; les
  contrats `horaire-mf-timescale`/`infrahoraire-mf`/`mf-data-fallback`
  convergent vers un contrat unique `observation-chaud`.
- (+) Extinction programmée : 4 hypertables wide, 12 matviews, refresh Kestra,
  fallback `mf_data` — chaque pièce a un remplaçant nommé dans cette ADR.
- (+) L'ingestion TS/Prisma existante se simplifie (une table cible au lieu de
  18 modèles wide), mais doit intégrer le mapping vocabulaire (ADR-0004) —
  c'est le vrai chantier de code.
- (−) Réécriture des flux d'ingestion et double-alimentation transitoire :
  coût réel, borné par le pattern de bascule mesurée déjà rodé (dual-source).
- (−) `obs_last` et les caggs sont des états supplémentaires à surveiller
  (lag de matérialisation, dérive vs le long) — checks de cohérence à ajouter
  aux contrôles CI/prod existants.
- (−) Questions ouvertes assumées : sentinelle `duree_s` (0 vs NULL vs -1),
  `float4` vs `float8` pour `valeur`, PostGIS à chaud pour les cartes live,
  et co-hébergement gateway pg_duckdb / serving sur la même instance (dépend
  du spike de cohabitation ADR-0006 §3).

**Critères de réouverture** : si un produit exige de l'analytique sub-seconde
sur l'intégralité du chaud (au-delà des caggs), ré-évaluer ClickHouse comme
moteur du chaud ; si la rétention nécessaire dépasse ~3-4 ans (usage réel des
pages), la frontière chaud/froid d'ADR-0006 est à recalibrer avant d'agrandir
le chaud.

## Références

- Étude compagnon « serving chaud » 2026-07-11 (workspace — DDL cible complet,
  volumétries, trajectoire en Y) ; étude R&D « évolution de schéma » (§4, §5.4)
- Bench ADR-0006 (chemin chaud 215 ms au mieux via gateway → besoin d'obs_last)
- POC `poc-lakehouse-2025/` (vocabulaire et crosswalk réutilisables tels quels)
- `audits/bdd/reconciliation-proposition-migration.md` (P0 compression, P1
  continuous aggregates — absorbés par cette ADR), inventaire TimescaleDB
  2026-06-09 (SQL_ASCII, 0 policy, matviews non versionnées)
- Audit de traduisibilité legacy 2026-07-11 (`audit-traduisibilite-legacy-2026-07.md`,
  workspace — source des amendements §1bis et de la table de préséance à venir)
- ADR-0004, ADR-0005, ADR-0006 ; Timescale Hypercore / continuous aggregates
- BUFR/OMM (heure d'occurrence associée) ; ICOADS, Argo, CF `trajectory`
  (position par relevé)
