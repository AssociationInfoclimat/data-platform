# ADR-0005 — Identité unifiée des stations (`dim_station`, crosswalk historisé)

- Statut : proposée
- Date : 2026-07-11
- Décideurs : data engineer (pam)

> Phase 0 de l'étude R&D « évolution de schéma » du 2026-07-11, volet 2/2 (le volet
> vocabulaire des paramètres est ADR-0004). Cadre R&D open-source : le champ licence
> par station est **explicitement hors périmètre** de cette ADR.

## Contexte

Quatre systèmes d'identifiants de stations coexistent sans réconciliation d'ensemble :

| Identifiant | Système | Format |
|---|---|---|
| `stations.id` | `V5_data_params.stations` (54 781 lignes, annuaire IC, genre enum) | char(15) |
| `NUM_POSTE` | TimescaleDB historique MF (Horaire, Quotidienne…) | char(8) |
| `geo_id_insee` | TimescaleDB temps réel MF | `ddnnnpp` |
| OACI / OMM / MFID | metar (`id_station` char(4)), `mf_stations`, normales (`ID_wmo`) | divers |

Le crosswalk existe **en morceaux** : `ommid` (mapping mfid↔stid), `metsyn`
(id textuel↔numérique), `mf_stations.STID`, et la règle documentée au glossaire
« `NUM_POSTE` = `geo_id_insee` tronqué à 7 caractères, avec précision » — un
appariement non trivial appliqué au cas par cas dans le code. S'ajoutent :
`stations_europe` dupliquée dans 2 bases, `communes` en 3 exemplaires, aucune FK
nulle part (MyISAM), et des métadonnées riches mais orphelines — `static_qualite`
(qualité déclarée par paramètre), `static_instruments` (historique d'équipement,
hauteurs, emplacements), datées mais non reliées à une entité station stable.

Conséquences : toute fusion multi-source (le cœur de la table canonique `observation`
de l'étude), tout dataset publiable, tout appariement obs↔grille repose sur des
jointures conventionnelles fragiles refaites à chaque usage. C'est le blocage n° 1
identifié par l'étude.

## Décision

Créer une **entité station pivot, historisée, source de vérité du rattachement de
toute observation**.

1. **`station_uid` : identifiant pivot interne, opaque et stable.** Jamais réutilisé,
   jamais porteur de sémantique (pas de département encodé dedans — les identifiants
   « intelligents » sont précisément ce qui a créé le problème `geo_id_insee`).
   Toute table canonique référence `station_uid`, jamais un identifiant source.
2. **Crosswalk explicite** : `ids` = map `type → valeur` (`ic_id`, `num_poste`,
   `geo_id_insee`, `oaci`, `omm`, `mfid`, `ecad`…), chaque appariement portant sa
   **méthode** (`declared` — présent dans une table de mapping source ; `derived` —
   règle documentée type troncature ; `manual` — arbitrage humain en MR) et sa
   confiance. La règle de troncature `NUM_POSTE`↔`geo_id_insee` devient du code
   versionné et testé, plus une tradition.
3. **Historisation SCD2** (`valid_from`/`valid_to`) : position, altitude, nom, réseau,
   statut d'ouverture. Une station déplacée = deux versions, pas un UPDATE — les
   études de séries longues (homogénéisation, cas d'usage IA de l'étude) exigent de
   savoir *quand* une station a bougé.
4. **Les cas insolubles ont un statut, pas une résolution forcée.** `resolution:
   resolved | ambiguous | conflicting`, avec les candidats conservés. Un appariement
   douteux marqué `ambiguous` est une information ; un appariement faux silencieux est
   une corruption. Jamais de fusion automatique de deux stations sur simple proximité
   géo + nom.
5. **Rattachement des métadonnées orphelines** : `static_qualite` et
   `static_instruments` (dictionnaires décodés via ADR-0004) deviennent des attributs
   datés de l'entité — l'historique d'instrumentation est une métadonnée de rupture
   de série de première classe.
6. **Alignement WIGOS en cible** : structure des identifiants compatible OMM
   (`0-250-x-<local>` pour un réseau tiers). La demande d'un bloc d'identifiants OMM
   pour StatIC est une **piste ouverte** (visibilité WIS 2.0), pas un prérequis — la
   colonne `wigos_id` existe, nullable.
7. **Matérialisation et gouvernance** : sources du crosswalk (règles + arbitrages
   manuels) versionnées dans le repo ; pipeline de résolution **reproductible** qui
   régénère la table `dim_station` (Iceberg + GeoParquet, ADR-0003) ; contrat ODCS
   dédié ; évolutions selon ADR-0002 (un appariement corrigé = changelog + MR).
   Sorties auditables : rapport de résolution chiffré (résolus/ambigus/conflits) à
   chaque run, comparable dans le temps.
8. **Tranches** (chaque tranche autonome) :
   1. **Squelette + crosswalk déclaré** : entité pivot sur `stations` (IC) ⋈ `ommid` ⋈
      `metsyn` ⋈ `mf_stations` — les appariements déjà présents dans les données.
   2. **Appariements dérivés** : règle de troncature codée + testée, metar OACI,
      ECA&D ; rapport d'ambiguïtés.
   3. **SCD2 + métadonnées datées** (positions historiques, instruments, qualité).
   4. **Dédoublonnage des référentiels annexes** (`stations_europe`, `communes`)
      par rattachement au pivot.

## Justification

- **Prérequis de tout le reste.** La table canonique `observation` (étude §4.2), le
  wide harmonisé, le benchmark nowcasting et les datasets publics référencent
  `station_uid` : sans identité résolue, la fusion multi-source produit des doublons
  ou des trous invisibles.
- **SCD2 plutôt qu'annuaire plat** : l'annuaire actuel (`stations`, une ligne par
  station, `last_report` écrasé) perd l'histoire ; or les séries font un siècle, et
  les déplacements/changements d'instruments sont la première cause de rupture.
- **La méthode d'appariement tracée** transforme le crosswalk en objet scientifique
  auditable — condition pour que des tiers (recherche, DataForGood) fassent confiance
  aux jointures.
- **Statut `ambiguous` assumé** : l'expérience des morceaux existants (troncature à
  précision variable, ids réutilisés) garantit des cas limites ; les nier les ferait
  ressortir en aval, en pire.

## Conséquences

- (+) Une seule réponse à « c'est quelle station ? » ; les jointures
  historique↔temps réel↔IC deviennent mécaniques.
- (+) Les 970 M d'obs StatIC deviennent appariables aux réseaux officiels — condition
  du QC par voisinage et des cas d'usage IA de l'étude.
- (+) `stations_europe`/`communes` dédupliquées par rattachement, au lieu de trois
  vérités parallèles.
- (−) Chantier de résolution d'identité : des dizaines de cas manuels probables
  (arbitrages en MR — c'est le coût de la traçabilité). Mitigé par les tranches :
  la tranche 1 ne traite que le déclaré, valeur immédiate sans arbitrage.
- (−) `station_uid` introduit une indirection : les consommateurs habitués aux ids
  source passent par le crosswalk (vue de traduction fournie — les ids source restent
  des colonnes requêtables, ils cessent juste d'être des clés).
- (−) La qualité du résultat dépend de sources amont parfois fausses
  (lat/lon `float` dans `mf_stations`, altitudes douteuses) : le rapport de résolution
  doit chiffrer les incohérences géo détectées, pas les corriger silencieusement.

**Critère de réouverture** : si la part d'`ambiguous` reste >10 % des stations actives
après la tranche 2, le modèle d'appariement (règles + manuel) est insuffisant —
ouvrir une ADR sur une résolution assistée (blocking géo + scoring), sans jamais
retirer la boucle humaine.

## Références

- Étude R&D « évolution de schéma data » 2026-07-11 (§2.2, §4.3, §7.3)
- `catalog/glossary.md` (identifiants NUM_POSTE/geo_id_insee/MFID, règle de troncature)
- Dump `schemas/mariadb/schema.sql.gz` : `V5_data_params.{stations,metsyn,
  static_qualite,static_instruments}`, `V5_data_mf.mf_stations`, doublons
  `stations_europe`/`communes`
- Timescale : `ommid`, `Station`/`StationTempsReel` (inventaire 2026-06-09)
- ADR-0003 (matérialisation Iceberg/GeoParquet) ; ADR-0004 (dictionnaires paramètres)
- WIGOS Station Identifiers (OMM) ; GeoParquet 1.1
