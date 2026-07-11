# ADR-0004 — Vocabulaire contrôlé des paramètres d'observation (`dim_parametre`)

- Statut : proposée
- Date : 2026-07-11
- Décideurs : data engineer (pam)

> Phase 0 de l'étude R&D « évolution de schéma » du 2026-07-11, volet 1/2 (le volet
> identité des stations est ADR-0005). Principe directeur hérité d'ADR-0002 :
> **git fait foi, les tables et les tools sont des vues.**

> **Amendée le 2026-07-11** (audit de traduisibilité legacy,
> `audit-traduisibilite-legacy-2026-07.md`) : ajout des conventions §7
> (dimensions verticales/couches dans la clé, marqueur `porte_occurrence`,
> frontière profils verticaux) et recadrage du volume cible (~140 entrées —
> l'audit a inventorié les 94 colonnes wide MF réellement consommées, les 34
> sous-champs packés de `static.complements` et les codes `_H` de `mf_data`
> lus par mobile-api).

## Contexte

Il n'existe aucune définition partagée de « ce qu'est un paramètre mesuré ». La même
grandeur physique vit sous des formes incompatibles selon le système :

- **Noms** : `temperature` (familles IC), `T` (wide MF historique), `t` (temps réel MF,
  en Kelvin dans l'API source), codes `_H` MF (`TSV_H`, `GLO2_H`…), éléments ECA&D
  (`TX`, `TN`, `RR`), colonnes climato (`tn`, `tx`, `rr`, `ens`).
- **Types** : `temperature` en `float` (synop/static), `tinyint` (metar — troncature
  au degré entier), `double` (bouées, mf_data) ; `nebulosite` en `enum('0'..'8')` ici,
  `int(2)` ou `tinyint(4)` là.
- **Unités** : conventions MF au 1/10 (°C, mm) dans l'historique Timescale, unités
  usuelles converties (°C, hPa, m/s) dans les tables temps réel, SI (K, Pa) dans l'API
  brute — le piège K vs °C est déjà documenté comme incohérence entre contrats
  (`climato-mf-timescale` vs `horaire-mf-timescale`).
- **Support temporel encodé dans les noms de colonnes** : `pluie_1h`/`pluie_3h`/
  `pluie_6h`/`pluie_12h`/`pluie_24h`/`pluie_cumul_0h`, `temperature_min`/`_max` sur des
  fenêtres implicites, `vent_rafales` vs `vent_rafales_10min` — la durée est une
  dimension, pas une grandeur, mais le schéma actuel les confond.
- **Dictionnaires hors modèle** : `static_qualite.id_parametre` et
  `static_instruments.id_instrument` définis dans des `COMMENT` SQL (0=Température,
  1=Vent…), non requêtables, non versionnés.

Toute fusion multi-source, tout export harmonisé, toute réponse LLM sur la donnée bute
sur cette absence de vocabulaire. Le repo a déjà l'embryon : `catalog/glossary.md`
(prose) et les contrats sources MF qui documentent champ par champ unités et types.

## Décision

Créer un **vocabulaire contrôlé des paramètres**, artefact versionné du repo, source
unique de vérité dont tables et outils dérivent.

1. **Source de vérité : `catalog/parametres.yaml`.** Une entrée par grandeur, clés :
   - `parametre` (clé stable snake_case, ex. `air_temperature`, `precipitation_amount`,
     `wind_speed_of_gust`) ;
   - `cf_standard_name` (conventions CF quand il existe, sinon `null` + justification) ;
   - `unite_si` (unité de stockage canonique : K, Pa, m/s, kg m-2, %…) ;
   - `domaine` (bornes physiques plausibles min/max — socle des contrôles qualité) ;
   - `description_fr` ;
   - `sources` : le **mapping par système** — colonne famille IC (`synop.temperature`),
     code MF historique (`T`, facteur 1/10), colonne temps réel (`t`, K), code `_H`,
     élément ECA&D, id du dictionnaire `static_qualite` — avec pour chacun le facteur
     et l'offset de conversion vers l'unité SI.
   Ordre de grandeur : ~150 entrées ; la matière existe déjà (contrats
   `source-meteofrance-*`, DDL MariaDB, glossaire) — c'est une transcription outillée,
   pas une découverte.
2. **Le support temporel est une dimension, pas un paramètre.** Le couple
   `(parametre, duree_s)` remplace les familles de colonnes : `precipitation_amount` ×
   {3600, 10800, 21600, 43200, 86400} couvre `pluie_1h`…`pluie_24h` ;
   `air_temperature_min` disparaît au profit de (`air_temperature`, agrégat min,
   `duree_s`). Le vocabulaire liste pour chaque paramètre les supports **attendus** par
   source (sert de test de complétude à l'ingestion).
3. **Convention de nommage : CF d'abord.** Quand CF définit un standard name, la clé le
   suit ; les spécificités Infoclimat (ex. qualité déclarée StatIC) prennent un préfixe
   `ic_`. Ni français ni codes MF dans les clés — le français vit dans `description_fr`,
   les codes MF dans les mappings.
4. **Matérialisations dérivées** (jamais éditées à la main) :
   - table Iceberg `dim_parametre` (ADR-0003) régénérée depuis le YAML ;
   - blocs `schema.properties` des futurs contrats ODCS des tables canoniques,
     **générés** depuis le vocabulaire (fin de la double saisie contrat/vocab) ;
   - vue MCP/bot (précédent ADR-0001/0002 : le tool lit git) — le text-to-SQL et les
     réponses du bot s'appuient sur le vocabulaire, pas sur une tradition orale.
5. **Évolution selon ADR-0002** : ajout de paramètre = MR + entrée changelog
   (`non-breaking`) ; changement d'unité ou de sémantique d'une clé existante =
   `breaking` (et donc, en pratique, création d'une nouvelle clé + dépréciation —
   patron `replace` d'ADR-0002, qui s'applique tel quel).
6. **Validation en CI** : lint du YAML (unicité des clés, unités reconnues, bornes
   cohérentes, mappings sans collision) + test croisé contre les contrats sources
   (tout champ actif d'un contrat `source-meteofrance-*` doit être mappé ou
   explicitement listé `non_retenu`).
7. **Conventions d'extension** (amendement 2026-07-11, issues de l'audit de
   traduisibilité) :
   - **Dimensions verticales et couches encodées dans la clé** quand la
     cardinalité est **bornée et fixe** : `soil_temperature_10cm/_20cm/_50cm/
     _100cm`, `cloud_layer_1_area_fraction`…`cloud_layer_4_*` — précédent
     GHCN-Daily (profondeur et couverture encodées dans le code élément).
     **Frontière explicite** : cette convention ne s'étend PAS aux niveaux
     nombreux ou variables — les profils verticaux (radiosondages, ACARS)
     exigeront une vraie colonne de niveau ou une modélisation `profile`
     dédiée (featureType CF), jamais une explosion de clés.
   - **Marqueur `porte_occurrence: true`** sur les paramètres agrégés dont la
     source fournit l'heure/date d'occurrence (TN/HTN, TX/HTX, rafales/HXY,
     records de normales…) : déclare que la mesure alimente la colonne
     `dh_occurrence` du modèle canonique (cf. ADR-0007 amendée). Le couple
     (valeur, occurrence) reste atomique — c'est le motif retenu contre le
     « paramètre apparié » (`time_of_maximum` séparé), qui expose des couples
     orphelins au QC et au filtrage.
   - **Mesures techniques** (tension batterie, facteur qualité SR50 — issues de
     `static.complements`) : entrées de plein droit avec `domaine` technique,
     taguées `technique: true` pour exclusion par défaut des produits météo.

## Justification

- **Les conversions d'unités deviennent structurellement uniques.** Un seul endroit
  (le mapping) porte « MF historique = 1/10 °C » ; la conversion vers l'affichage vit
  dans les vues Gold, une fois, testée. Le bug K vs °C cesse d'être possible par
  construction.
- **Évolution additive sans ALTER.** Un nouveau capteur StatIC ou un nouveau champ MF
  = une entrée YAML + une ligne de mapping — pas de migration sur des tables de
  centaines de GiB, pas de bump majeur en cascade.
- **C'est le prérequis du format long.** La table canonique `observation` de l'étude
  n'a de sens que si `parametre` référence un vocabulaire fermé et versionné.
- **Interopérabilité gratuite** : les clés CF alignent les exports sur ce que xarray,
  MetPy, les catalogues climat et les équipes recherche attendent.

## Conséquences

- (+) Fin des dictionnaires en COMMENT SQL : `static_qualite`/`static_instruments`
  se raccordent au vocabulaire par mapping explicite.
- (+) Les ~150 entrées documentent au passage les décisions d'harmonisation
  (ex. metar tronqué au degré : mappé avec `qc_detail` de précision — la perte est
  tracée, pas silencieuse).
- (+) Le MCP répond « quelles variables de vent existe-t-il et dans quelles sources ? »
  depuis git, offline.
- (−) Coût initial de transcription et d'arbitrage (~150 entrées, quelques cas
  ambigus : grandeurs MF sans équivalent CF, cumuls à heure d'occurrence en `char(5)`) ;
  mitigé en démarrant par le noyau commun aux 3 modèles (~30 paramètres couvrent >95 %
  des lignes).
- (−) Une dépendance de plus pour les pipelines (le vocabulaire devient bloquant à
  l'ingestion canonique) — c'est voulu : paramètre inconnu = refus d'écrire en Silver,
  la donnée reste en Bronze en attendant la MR de vocabulaire.

**Critère de réouverture** : si le YAML unique devient ingérable (>500 entrées,
conflits de MR fréquents), éclater par domaine (`parametres/{thermo,vent,precip}.yaml`)
sans changer le contrat d'interface des vues.

## Références

- Étude R&D « évolution de schéma data » 2026-07-11 (§4.4, §8 mapping de convergence)
- `catalog/glossary.md` (embryon prose), `contracts/source-meteofrance-*.odcs.yaml`
  (unités/champs bruts déjà transcrits)
- Dump `schemas/mariadb/schema.sql.gz` (dictionnaires en COMMENT, familles de colonnes)
- ADR-0002 (changelog, patron `replace`, sévérités) ; ADR-0003 (matérialisation Iceberg)
- Audit de traduisibilité legacy 2026-07-11 (`audit-traduisibilite-legacy-2026-07.md`,
  workspace — inventaire des colonnes réellement consommées, source du §7)
- CF Standard Names (conventions Climate & Forecast) ; vocabulaire OMM/WIGOS ;
  GHCN-Daily (précédent de l'encodage profondeur/couche dans le code élément)
