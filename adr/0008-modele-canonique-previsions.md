# ADR-0008 — Prévisions numériques : dimensions partagées, table séparée

- Statut : proposée
- Date : 2026-07-27
- Décideurs : data engineer (pam)

> Répond à une question posée pendant le POC canonique : faut-il verser les
> sorties des modèles de prévision (AROME, ARPEGE, GFS…) dans la table
> `observation` du canonique « pour tout harmoniser » ? Prolonge ADR-0004
> (vocabulaire, explicitement borné à l'observation), ADR-0005 (identité
> stations) et ADR-0007 (modèle canonique long, chaud et froid).

## Contexte

Les modèles vivent aujourd'hui dans un monde parallèle au reste de la donnée.
`modeles-ncl` télécharge et décode les runs (AROME, ARPEGE, GEFS, COAMPS, BOM,
WRF…), `modeles-php` orchestre les lancements sur srx-modeles-2, et la sortie
utile est une **image** : des cartes NCL. Entre le GRIB décodé et la carte, il
n'existe aucune matérialisation requêtable, aucun vocabulaire commun avec
l'observation, aucun rattachement au référentiel stations.

Conséquences concrètes, toutes constatées :

- **Impossible de comparer prévu et observé** sans réécrire un mapping ad hoc :
  le modèle sort `T2M` ou `t2m` en kelvin sur une grille, l'observation sort
  `air_temperature` en kelvin sur une station — les deux disent la même chose et
  ne se joignent pas.
- **Aucun score de vérification** n'est calculé ni publié (biais, RMSE, taux de
  bonne détection), alors que c'est la métrique la plus demandée sur un service
  météo participatif et le premier argument de transparence.
- **Une page station ne peut pas juxtaposer** la mesure et la prévision au même
  point : il n'y a pas de prévision « au point station », seulement des rasters.

D'où la tentation d'unifier par le bas : une seule table `observation`, on y met
tout, le problème de vocabulaire disparaît. Cette ADR tranche ce point.

Rappel du grain canonique (ADR-0007) : `(station_id, dh_utc, parametre_id,
duree_s)` → `valeur`, avec `qc_flag`, `version_obs`, `source_id`.

## Décision

**Les sorties de modèle ne rejoignent pas la table `observation`. Elles
réutilisent en revanche l'intégralité des dimensions du canonique — vocabulaire,
identité des stations, sémantique des durées, unités SI — et se matérialisent
dans une table sœur `prevision`, réservée aux prévisions ponctuelles extraites
aux stations. Les champs grillés restent dans leur format natif.**

### 1. `observation` reste la table des observations

Quatre raisons, dont la première est dirimante.

**1a. La clé n'a pas les bons axes.** Une prévision n'est pas identifiée par
`(station, instant, paramètre, durée)`. Il y manque le **run** (heure
d'analyse) : pour un même instant valide, les runs successifs produisent
plusieurs prévisions qui coexistent légitimement. Il y manque le **modèle** et,
pour les ensembles, le **membre**.

Et `version_obs` n'est pas le refuge de ces axes. Ce champ versionne la
**correction d'une vérité unique** — une mesure re-validée remplace la
précédente, la dernière version fait foi. Deux prévisions de runs différents ne
se corrigent pas l'une l'autre. Les confondre ferait mentir `obs_last`
(« dernière valeur connue » n'aurait plus de sens) et la contrainte d'unicité de
la PK.

**1b. La géométrie diffère.** `dim_station` (ADR-0005) référence un site
physique : coordonnées, altitude, classe de siting, période d'activité,
rattachement INSEE. Un modèle produit un champ sur une grille régulière. Inscrire
les points de grille comme pseudo-stations ferait passer `dim_station` de ~15 750
entrées à des millions de lignes sans métadonnée de siting, sans historique, sans
commune — ce qui viderait de sens tout ce qui s'appuie dessus : `/ref/stations`,
le crosswalk canicule, la carte de couverture, les filtres par réseau.

**1c. Le volume est d'un autre ordre.** Ordre de grandeur pour AROME seul,
hypothèses explicites : ~10⁶ points de grille × ~40 paramètres × ~50 échéances ×
8 runs/jour ≈ **10 milliards de valeurs par jour**. L'archive d'observations
complète, remontant à 1777, en compte 39 milliards. Le modèle réécrirait
l'équivalent du fonds tous les quatre jours.

Le tuning physique suit la même logique : `observation` est partitionnée en
tranches de 7 jours et compressée `segmentby (station_id, parametre_id)`, ce qui
suppose peu de stations et beaucoup d'historique. Le profil prévision est
exactement l'inverse.

**1d. Le cycle de vie est opposé.** Une observation se garde indéfiniment. Une
prévision perd sa valeur d'usage passée son échéance ; seule une fraction est
conservée, et pour un autre motif (le calcul de scores). Mélanger les deux dans
une table impose la rétention la plus longue au volume le plus gros.

### 2. Les dimensions, elles, sont partagées — c'est là qu'est l'harmonisation

- **`dim_parametre` (ADR-0004) est étendu, pas dupliqué.** Une grandeur
  pronostiquée porte la même clé que la grandeur observée : le T2M d'AROME est
  `air_temperature`, en kelvin, avec les mêmes bornes de plausibilité. Le
  nommage CF est issu des conventions *Climate and Forecast* — prévu dès
  l'origine pour couvrir les sorties de modèle. Les grandeurs sans équivalent
  observé (CAPE, hauteur de couche limite, précipitations convectives) entrent
  comme nouvelles clés du même vocabulaire, avec la même règle d'unité SI.
- **`dim_station` (ADR-0005) est partagé tel quel.** La prévision au point
  Grenoble-St-Geoirs porte le `station_uid` de Grenoble-St-Geoirs.
- **`duree_s` garde sa sémantique.** Le Tx prévu sur 24 h et le Tx observé sur
  24 h ont la même durée d'accumulation : la comparaison est licite sans
  retraitement.
- **Nouvelle dimension `dim_modele`** : identité du modèle (nom, centre
  producteur, résolution, domaine, version de cycle), versionnée comme les
  autres référentiels — git fait foi, la table est une vue (ADR-0002).

Avec ces dimensions communes, comparer prévu et observé devient une **jointure**,
pas une couche de traduction. C'est tout l'objet de l'ADR.

### 3. Table sœur `prevision`, prévisions ponctuelles aux stations

| Colonne | Type | Rôle |
|---|---|---|
| `modele_id` | smallint | → `dim_modele` |
| `run_utc` | timestamptz | heure d'analyse |
| `dh_utc` | timestamptz | instant valide (l'échéance se dérive : `dh_utc − run_utc`) |
| `station_id` | int | → `dim_station`, **même référentiel** |
| `parametre_id` | smallint | → `dim_parametre`, **même vocabulaire**, unités SI |
| `duree_s` | int | même sémantique d'accumulation |
| `membre` | smallint | 0 = déterministe, n = membre d'ensemble |
| `valeur` | float8 | |

PK : `(modele_id, run_utc, station_id, parametre_id, duree_s, membre, dh_utc)`.

Deux différences assumées avec `observation` :

- **pas de `qc_flag`** — une prévision ne se contrôle pas à l'ingestion, elle se
  vérifie a posteriori. Sa qualité est un produit dérivé (§5), pas un attribut
  de ligne ;
- **pas de `version_obs`** — l'axe `run_utc` porte déjà la temporalité des
  révisions, et deux runs ne se remplacent pas.

Volumétrie cible : ~15 000 stations au lieu de ~10⁶ points de grille, soit trois
ordres de grandeur en moins. Rétention courte par défaut sur les runs, longue sur
l'échantillon conservé pour les scores.

### 4. Les champs grillés restent dans leur format natif

GRIB2 en réception, converti en **Zarr** (ou équivalent chunké) pour l'accès
analytique, stocké sur S3 et **référencé par le catalogue** — jamais dépivoté en
lignes. Un champ grillé compressé coûte 1 à 2 octets par valeur ; la même valeur
en modèle long en coûte 5 à 20 fois plus, les clés étant répétées à chaque point.
Le lakehouse indexe les rasters, il ne les avale pas.

`prevision` est donc un **produit d'extraction** de ces champs (interpolation au
point station, méthode et voisinage documentés dans le contrat), pas leur
matérialisation exhaustive.

### 5. La vérification est un dataset Gold

Les scores (biais, RMSE, MAE par échéance et par modèle, taux de détection sur
seuils) se calculent par jointure `prevision × observation` sur
`(station_id, parametre_id, duree_s, dh_utc)` — jointure devenue triviale par
construction. Ils se publient comme les autres datasets Gold, avec contrat ODCS.

## Justification

- **L'harmonisation réelle est dans les dimensions, pas dans la table.** Ce que
  coûte aujourd'hui l'hétérogénéité — impossibilité de joindre, pièges d'unités,
  double vocabulaire — est intégralement réglé par le partage de
  `dim_parametre`/`dim_station`. Fusionner les tables n'apporte rien de plus et
  détruit les invariants de chacune.
- **Le précédent existe partout.** Aucun système d'état ne mélange observations
  et prévisions dans la même table : le WMO les sépare jusque dans les formats
  d'échange (BUFR pour l'observation, GRIB pour le champ prévu) ; les archives de
  vérification (ECMWF, MET Norway, NOAA MDL) modélisent la prévision avec l'axe
  `reference_time` × `valid_time` distinct, exactement la structure retenue ici.
- **Le coût de l'erreur inverse est asymétrique.** Séparer et devoir joindre est
  un coût de requête, borné et connu. Fusionner et devoir re-séparer, c'est une
  migration de plusieurs dizaines de milliards de lignes avec un modèle dont la
  PK est fausse — ce que le POC a précisément passé six mois à défaire sur le
  legacy.
- **La sparsité qui justifiait le long pour l'observation ne vaut pas ici.** Une
  sortie de modèle est **dense** : tous les points ont toutes les valeurs. Le
  modèle long, choisi en ADR-0007 parce que le wide MF était un cimetière de
  NULL, perd son argument principal face à un champ grillé complet — d'où le
  format natif au §4.

## Conséquences

- (+) Comparaison prévu/observé et scores de vérification deviennent
  atteignables : une jointure sur des clés partagées, un dataset Gold, un
  endpoint. C'est le produit qui manque le plus visiblement aujourd'hui.
- (+) `dim_parametre` gagne un second consommateur, ce qui **valide le pari
  d'ADR-0004** : un vocabulaire contrôlé n'a d'intérêt que s'il traverse les
  domaines. Le nommage CF y était déjà prêt.
- (+) Les invariants d'`observation` sont préservés : `obs_last` garde son sens,
  la PK reste vraie, la compression reste adaptée au profil, `dim_station`
  reste un référentiel de sites physiques.
- (+) `modeles-ncl`/`modeles-php` cessent d'être une impasse : leur sortie
  devient de la donnée requêtable, pas seulement des images.
- (−) **Une chaîne d'extraction à construire** : décodage GRIB → conversion Zarr
  → interpolation au point station → écriture `prevision`. C'est le vrai
  chantier, non trivial, avec des choix à documenter (méthode d'interpolation,
  traitement du relief, gestion des points de mer).
- (−) **Le mapping des paramètres modèles est à faire** (~40-60 clés par modèle,
  dont plusieurs sans équivalent observé). Travail comparable au mapping des 280
  entrées de l'observation, mais mieux outillé puisque le vocabulaire existe.
- (−) **Une dimension et une table de plus** à gouverner : contrat ODCS,
  lineage OpenLineage, politique de rétention par modèle.
- (−) `prevision` ne couvre pas les usages cartographiques (carte de prévision
  France entière) : ceux-ci restent servis par les champs grillés, donc **deux
  chemins de lecture** coexistent selon qu'on veut un point ou un champ.

**Critères de réouverture** : si un usage exige des prévisions sur un maillage
dense et non plus aux stations (post-traitement statistique type MOS sur grille,
downscaling par maille), réexaminer l'ajout d'un axe `cellule_id` à `prevision`
plutôt qu'un élargissement de `dim_station` — la frontière à tenir reste
« une station est un site physique ». Si le volume de `prevision` dépasse celui
d'`observation` malgré la restriction aux stations, revoir la rétention avant le
modèle.

## Références

- ADR-0004 (vocabulaire `dim_parametre`, périmètre observation — étendu ici),
  ADR-0005 (identité stations, réutilisée telle quelle), ADR-0007 (modèle
  canonique long, chaud et froid), ADR-0002 (versioning des schémas de sources
  externes — `dim_modele` suit le même régime), ADR-0003 (Iceberg)
- POC CHOM : `chom-poc-data/docs/utiliser-les-donnees.md` (format canonique tel
  que servi), `deploy/staging/initdb-canonical/01-schema.sql` (DDL `observation`)
- Repos concernés : `modeles-ncl` (downloaders et décodage AROME/ARPEGE/GEFS/
  COAMPS/BOM), `modeles-php` (orchestration des runs)
- Conventions CF (*Climate and Forecast*) — le vocabulaire d'ADR-0004 couvre par
  construction les grandeurs pronostiquées ; WMO GRIB2 (champs prévus) vs BUFR
  (observations), séparation des formats d'échange
- Pratique des archives de vérification (`reference_time` × `valid_time` × membre)
  chez ECMWF, MET Norway (Thredds/Zarr), NOAA MDL
