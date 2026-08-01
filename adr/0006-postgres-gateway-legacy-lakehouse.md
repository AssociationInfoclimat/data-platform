# ADR-0006 — Postgres comme gateway unique du legacy vers le lakehouse

- Statut : proposée
- Date : 2026-07-11
- Décideurs : data engineer (pam)

> Découle du POC lakehouse 2025 (année complète d'observations en Iceberg/Parquet,
> 2,44 Md de mesures canoniques) et du spike gateway mesuré le 2026-07-11 :
> PHP 7.4 + PDO pgsql — le driver exact de `combined.php` — requêtant le lakehouse
> à travers une extension Postgres, sans changement de driver côté monolithe.
> S'appuie sur ADR-0003 (Iceberg), ADR-0004 (vocabulaire), ADR-0005 (identité).

## Contexte

Le monolithe PHP 7.4 (~2 200 fichiers) est couplé au stockage de deux façons :

- **241 fichiers** référencent les bases shardées `V5_data_*` en MySQL, dont ~130
  interpolent l'année dans le nom de base (`V5_data_{$year}`) — une requête
  pluriannuelle assemble à la main des dizaines de tables ;
- les lectures Météo-France passent déjà par **une couche unique**,
  `include/MeteoFrance/combined.php` (~5 400 lignes), en **PDO `pgsql:`** vers
  TimescaleDB — requêtes à FULL JOIN 4 sources + COALESCE en cascade.

Si le lakehouse (ADR-0003) devient la source de vérité de l'historique, il faut
un chemin d'accès pour ce code. Trois options examinées :

1. **API HTTP intermédiaire** (pattern climato-froid, prouvé en prod) : robuste,
   mais chaque page legacy migrée exige de passer du SQL à des appels HTTP —
   un changement de paradigme pour 241 fichiers.
2. **Réécriture directe** vers un client Iceberg : inexistant en PHP 7.4, exclu.
3. **Gateway protocole Postgres** : une extension Postgres embarquant DuckDB
   (pg_duckdb, ou pg_lake) expose les tables Iceberg/Parquet comme des tables
   SQL. Le legacy garde PDO `pgsql:`, seule la requête change — et elle se
   simplifie (le FULL JOIN multi-sources devient un GROUP BY sur la table
   canonique `observation`).

Le spike (POC itération 3, conteneur `pgduckdb/pgduckdb:17-main`, vues générées
depuis les fichiers actifs Iceberg, bench PDO PHP 7.4.33 sur les 2,44 Md de
mesures 2025, table **non triée ni partitionnée** = borne haute) :

| Pattern legacy rejoué | p50 mesuré |
|---|---|
| Page station, wide 8 jours (équiv. `get_combined_between`) | 473 ms |
| Série climato tn/tx sur l'année | 425 ms |
| Snapshot carte France à une heure | 183 ms |
| **Dernière observation d'une station (chemin chaud)** | **1 494 ms** |

## Décision

**Le protocole Postgres est l'interface unique du legacy vers la donnée : les
lectures chaudes restent sur les tables natives (TimescaleDB), les lectures
d'historique et d'analytique passent par des vues gateway sur les tables
Iceberg — dans la même connexion PDO `pgsql:`.**

1. **Répartition chaud/froid par latence mesurée, pas par principe.**
   - *Chaud* (dernière obs, live, upserts de modération, continuous aggregates) :
     tables natives Postgres/Timescale. Le spike confirme que le point-lookup
     n'est pas le métier du lakehouse (1,5 s).
   - *Froid/analytique* (pages climato, séries longues, cartes historiques,
     exports) : vues gateway sur Iceberg. **Confirmé par le spike
     tri/partitionnement** (réécriture des 2,44 Md de mesures en partition
     month(dh_utc) + tri (station_uid, dh_utc), même count exact, 62 min) —
     p50 mesurés : page station 8 j **473 → 109 ms (4,3×)**, série année
     **425 → 118 ms (3,6×)**, dernière obs **1 494 → 215 ms (7×)**, snapshot
     carte 183 → 273 ms (le tri station-major dégrade légèrement la coupe
     temporelle pure — arbitrage assumé, la partition mensuelle borne le coût).
     Toutes les requêtes analytiques tiennent en 100-300 ms via PDO PHP 7.4.
     Nota : la table triée pèse +13 % (l'entrelacement des paramètres par
     station compresse moins bien que l'écriture par branches) — le tri
     s'achète en octets, se paie en latence.
2. **TimescaleDB est repositionnée : serving chaud, plus jamais archive.**
   Rétention glissante (~2 ans, à calibrer par l'usage réel des pages) +
   compression ; le lakehouse est la seule source de vérité de l'historique.
   Conséquence sur le plan BDD (`audits/bdd/`) : le P2 « migrer StatIC vers
   TimescaleDB » (~1 Tio) est re-scopé en « StatIC live → serving chaud ;
   historique StatIC → lakehouse » ; le P-parallèle « cold storage Parquet »
   devient le chantier principal.
3. **Choix d'extension : pg_duckdb d'abord, pg_lake en challenger.** pg_duckdb a
   fait le spike (fonctionnel, syntaxe `r['col']`, vues sur `read_parquet`) ;
   pg_lake (ex-Crunchy, open-sourcé 2025) apporte l'intégration catalogue
   Iceberg + écritures transactionnelles et sera évalué au même banc. Critère :
   lecture du **catalogue** Iceberg (pas de listes de fichiers générées) et
   cohabitation avec l'extension timescaledb sur la même instance — sinon,
   instance gateway dédiée à côté du serving (deux Postgres, un seul protocole).

   *Spike métadonnées du 2026-07-11* : pg_lake n'a **pas d'images publiées**
   (build depuis les sources — évaluation différée) ; testé à la place :
   pg_duckdb + extension DuckDB `iceberg` (installable depuis le conteneur),
   vue par `iceberg_scan(metadata.json)` — fonctionne (count exact, zéro liste
   de fichiers) mais coûte **~+400 ms par requête** (498-1004 ms vs 109-215 ms
   en liste statique) : les manifests sont relus à chaque requête, et la table
   du POC traîne **1 227 snapshots** (un par append de 2 M de lignes).
   Enseignements prod : (a) commits gros et rares à l'écriture, (b) maintenance
   de table obligatoire (expire_snapshots/rewrite_manifests — absents de
   pyiceberg 0.11, nécessitent un moteur ou une lib plus récente), (c) le
   cache de métadonnées est LE critère d'évaluation de pg_lake. D'ici là, les
   vues à liste statique restent le chemin rapide — régénérées à chaque commit,
   acceptable pour des archives en lecture seule.
4. **Migration en strangler, par chemin de lecture.** `combined.php` est la
   couture naturelle (les lectures MF y sont déjà centralisées) ; chaque page
   migrée supprime sa gymnastique `V5_data_{$year}` multi-bases. Jamais de
   bascule globale. Chaque vue gateway exposée = un contrat ODCS (les vues sont
   des produits dérivés reconstructibles, ADR-0004 §4).
5. **L'API HTTP reste le canal externe** (opendata, MCP, tiers — pattern
   climato-froid) ; la gateway est un canal **interne** pour le legacy. Les deux
   lisent les mêmes tables Iceberg.

## Justification

- **Le spike l'a prouvé au lieu de le supposer** : PHP 7.4 inchangé (driver,
  connexion, `fetchAll`) lit 2,44 Md de mesures en sub-seconde sur les patterns
  analytiques — sur une table même pas optimisée.
- **Coût de migration minimal par page** : changer une requête SQL (en la
  simplifiant), pas un paradigme. La couture `combined.php` existe déjà.
- **Un seul protocole à opérer et superviser** côté legacy ; l'alternative API
  aurait ajouté un saut HTTP et un service à la disponibilité duquel chaque page
  du site serait suspendue.
- **La répartition chaud/froid suit une mesure reproductible** (le bench est
  versionné dans le POC) — la frontière pourra bouger quand le tri/partition
  changera les chiffres, sans rouvrir l'architecture.

## Conséquences

- (+) Le décommissionnement du sharding `V5_data_*` a enfin un chemin incrémental
  chiffrable (nombre de fichiers legacy encore couplés = métrique de progrès).
- (+) TimescaleDB passe de 780 GiB (et croissant) à un serving borné (~<100 GiB
  compressé estimé) — la compression P0 reste utile, la crainte capacitaire
  disparaît.
- (+) Les requêtes legacy migrées se simplifient (suppression des FULL JOIN
  multi-sources : la fusion est faite une fois, en Silver).
- (−) Une extension non triviale (pg_duckdb/pg_lake) entre en prod dans le
  chemin de lecture du site : à isoler (instance gateway dédiée si la
  cohabitation timescaledb+pg_duckdb n'est pas sereine), à superviser (mémoire
  DuckDB bornée — `duckdb.max_memory`).
- (−) Le chemin chaud et le chemin froid divergent dans le code le temps de la
  migration : la couture `combined.php` doit router explicitement (fenêtre
  temporelle demandée → chaud ou gateway), règle simple mais à tester.
- (−) Les vues gateway du spike reposent sur des listes de fichiers générées
  (`gen_init.py`) : fragile face aux commits Iceberg. Levée par l'intégration
  catalogue (critère du point 3) — c'est le principal écart spike → prod.

**Critères de réouverture** : les requêtes mono-station plafonnent à ~105-120 ms
p50 (plancher protocole + vue à ~1 200 fichiers inclus) — acceptable pour des
pages archives ; si un usage exige mieux, la piste est l'intégration catalogue
(pruning de partitions au lieu d'une liste plate) avant de rouvrir la frontière
chaud/froid ; si ni pg_duckdb ni
pg_lake ne cohabitent proprement avec timescaledb ET que l'instance dédiée est
jugée trop lourde, revenir à l'option API interne (le pattern existe déjà).

## Références

- POC : `poc-lakehouse-2025/` (README §Itération 3, `deploy/pg-gateway/` —
  compose, gen_init.py, bench.php avec les chiffres)
- Étude R&D « évolution de schéma data » 2026-07-11 (§5.4, question serving)
- `site-infoclimat/include/MeteoFrance/combined.php` (la couture) ;
  `audits/bdd/reconciliation-proposition-migration.md` (P0-P3 à re-scoper)
- ADR-0003 (Iceberg), ADR-0004 (vocabulaire — vues = produits dérivés),
  ADR-0005 (identité stations)
- pg_duckdb (MotherDuck/Hydra) ; pg_lake ; contrats `mf-data-fallback` /
  `dual-source-targets.yaml` (le pattern de bascule mesurée à répliquer)
