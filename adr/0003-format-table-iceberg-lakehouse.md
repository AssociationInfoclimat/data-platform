# ADR-0003 — Apache Iceberg comme format de table du lakehouse d'observations

- Statut : acceptée (cadre R&D)
- Date : 2026-07-11
- Décideurs : data engineer (pam)

> Issue de l'étude R&D « évolution de schéma » du 2026-07-11 (hub sémantique en lakehouse,
> couches Bronze/Silver/Gold, table canonique `observation`). Cette ADR fixe le format de
> table ; le vocabulaire des paramètres et l'identité des stations sont traités par
> ADR-0004 et ADR-0005. Cadre : R&D open-source, sans contrainte d'infra ni de budget.

## Contexte

Le patrimoine d'observations vit dans deux systèmes aux modèles divergents : MariaDB
`V5_data_*` (~794 GiB, 4,4 Md lignes, sharding par nommage — 20 292 tables) et
TimescaleDB (~780 GiB, wide Météo-France). L'étude R&D conclut à un lakehouse ouvert :
Parquet sur stockage objet + format de table transactionnel + catalogue, moteurs de
requête interchangeables.

Un pilote existe déjà : `climato-froid` a migré le synop pré-2000 (392,7 M lignes) en
**Delta Lake** sur R2 — compression 6× index compris, requêtes sub-secondes en DuckDB,
principes acquis (tri `(station, date)` + zstd + partition pruning, fidélité d'archive,
overwrite prédiqué par partition, réconciliation d'historiques divergents).

Trois candidats pour généraliser :

- **Delta Lake** (continuité du pilote) : delta-rs mûr en Python/Rust, mais catalogue
  ouvert moins standardisé hors écosystème Databricks, et features récentes (variant,
  row lineage) tirées par un seul éditeur.
- **Apache Iceberg** : le format le plus neutre — spec v3 (type `variant` pour le
  semi-structuré, deletion vectors, row lineage), catalogues REST open-source
  interchangeables (Lakekeeper, Apache Polaris, Nessie), lu/écrit par DuckDB, Trino,
  Spark, ClickHouse, pyiceberg/iceberg-rust.
- **DuckLake** : catalogue = un simple Postgres, très peu de pièces mobiles — séduisant
  pour une équipe mono-steward, mais jeune et couplé à l'écosystème DuckDB.

## Décision

**Apache Iceberg (spec v3) est le format de table des nouvelles tables du lakehouse**
(Bronze, Silver, Gold de l'étude). Modalités :

1. **Catalogue REST léger.** Un catalogue Iceberg REST open-source auto-hébergé ;
   le choix de l'implémentation (Lakekeeper vs Polaris) se fait par un **spike mesuré**
   (critères : coût opérationnel mono-steward, auth simple, backup trivial) — c'est un
   détail d'exécution, pas une décision d'architecture, il ne bloque rien : pyiceberg
   sait démarrer sur un catalogue SQL minimal.

   *Précision du 2026-07-11 (décision d'hébergement full OVH, critère de
   souveraineté européenne)* : les catalogues Iceberg **managés** hors UE
   (ex. Cloudflare R2 Data Catalog, qui inclut aussi la compaction managée)
   sont **exclus par principe**, bien qu'économiquement attractifs —
   l'auto-hébergé est confirmé. Conséquence assumée : la **maintenance des
   tables (expire_snapshots + compaction) reste à notre charge**, job
   hebdomadaire non optionnel (leçon du POC : 1 227 snapshots =
   +400 ms/requête en lecture par métadonnées).
2. **Conventions physiques héritées du pilote** : partition par `annee` (+ bucket sur
   le paramètre pour la table canonique long, cf. étude), tri `(station_uid, dh_utc)`,
   compression zstd, schémas Arrow explicites dérivés des contrats — famille sans
   contrat = refus d'écrire.
3. **`variant` pour les payloads bruts.** `raw_msg` (synop, bouées), `donnees`
   (ACARS, profils) vont en Bronze dans une colonne `variant` typée — fin du `text`
   non requêtable, sans inventer un schéma pour du semi-structuré.
4. **Le pilote Delta reste tel quel.** `climatologie-cold` (R2) n'est pas re-commité :
   DuckDB lit les deux formats, l'API climato-froid ne change pas. Migration éventuelle
   vers Iceberg = décision d'exécution future, sur besoin réel (ex. unification du
   catalogue), jamais par principe.
5. **Chaque table Iceberg = un contrat ODCS** (`physicalType: iceberg-table`), versionnée
   selon ADR-0002 (bump semver + `changelog:` + RunEvent OpenLineage). Le namespace
   lineage s'étend : `iceberg://<catalogue>/<table>` à ajouter aux conventions
   (`lineage/namespaces.md`).

## Justification

- **Neutralité moteur = la garantie R&D.** Le même jeu de tables doit être requêtable
  par DuckDB (notebooks, API), Trino (SQL fédéré), Spark (ML distribué) et polars sans
  copie. Iceberg est le seul des trois candidats dont le catalogue REST est un standard
  multi-implémentations.
- **v3 couvre deux besoins précis du dossier** : `variant` (payloads bruts en Bronze)
  et row lineage (traçabilité au grain ligne, complète OpenLineage au grain job).
- **L'expérience acquise transfère.** Les concepts delta-rs (log, snapshots, overwrite
  prédiqué, vacuum) ont leurs équivalents directs Iceberg ; les pièges documentés du
  pilote (historiques divergents, sync fichiers interdite) s'appliquent à l'identique.
- **DuckLake écarté comme choix par défaut, pas enterré** : la frugalité opérationnelle
  est réelle, mais parier le schéma canonique sur un format jeune et mono-écosystème
  contredit l'objectif d'interopérabilité. Voir critère de réouverture.

## Conséquences

- (+) Toute table du lakehouse est lisible par l'écosystème entier sans export ; les
  datasets publics (phase 3 de l'étude) sont des tables Iceberg exposées telles quelles.
- (+) Schéma évolutif sans réécriture (add column, rename sûrs par ID de colonne) —
  cohérent avec le versioning ODCS.
- (−) **Une pièce d'infra en plus** (le catalogue REST) à opérer, sauvegarder,
  superviser — le point faible assumé face à DuckLake. Mitigation : spike de choix
  orienté « coût mono-steward », et démarrage possible sur catalogue SQL pyiceberg.
- (−) Deux formats coexistent (Delta du pilote + Iceberg) tant que `climatologie-cold`
  n'est pas migrée — acceptable car lecteurs communs, mais à documenter au catalogue.
- (−) L'écriture Python passe de delta-rs à pyiceberg : re-valider les débits
  d'extraction du pilote (counts exacts, reprise idempotente) sur une année témoin.

**Critère de réouverture** : si après 6 mois le catalogue REST s'avère être le poste
de coût opérationnel dominant du chantier (incidents, temps d'admin), ré-évaluer
DuckLake — la donnée reste en Parquet, le coût de conversion est un re-commit de
métadonnées, pas une réécriture.

## Références

- Étude R&D « évolution de schéma data » 2026-07-11 (workspace, hors repo — à ranger)
- Pilote : repo local `climato-froid/` (README — conventions physiques, pièges Delta/R2)
- ADR-0002 (versioning de schéma = fait de lineage — s'applique aux tables Iceberg)
- `lineage/namespaces.md` (namespace `iceberg://` à ajouter)
- Apache Iceberg spec v3 ; pyiceberg / iceberg-rust ; Lakekeeper, Apache Polaris (spike)
