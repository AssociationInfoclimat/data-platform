# ADR-0002 — Versioning des schémas de sources externes comme faits de lineage (ODCS + détection + changelog)

- Statut : acceptée
- Date : 2026-06-17
- Décideurs : data engineer (pam)

> Tranche 1 (pilier A + tool-vue) implémentée et mergée le 2026-06-17 : les 11 sources MF sont
> des contrats ODCS (`contracts/source-meteofrance-*.odcs.yaml`), le tool du bot est devenu une
> vue (`topic="changes"` + `since`). Tranches 2 (C3) et 3 (C1+B) à suivre.

> Une source externe (API Météo-France, archives data.gouv…) qui change de schéma est un
> événement de lineage de PREMIÈRE CLASSE, au même rang qu'un changement de type ou de
> contrat interne. Cette ADR fait entrer ce principe dans le formalisme du repo.

## Contexte

La connaissance des sources externes est aujourd'hui **éclatée et non versionnée** :

- quelques contrats ODCS orientés **table persistée** (`climato-mf-timescale`, server postgres) ;
- un contrat orienté **API** (`previsions-api-opendata`, server HTTP) ;
- et surtout le **gros du savoir** (schéma brut DPObs avec unités Kelvin/Pascal, gabarits
  d'URL, quirks 403/900908, segments AROME) figé dans un **dict codé en dur** dans
  `ic-data-bot/src/ic_data_bot/meteofrance_catalog.py`, dérivé d'un skill `meteofrance-apis`,
  hors de tout versioning et maintenu à la main.

Conséquence directe : à la question « Météo-France est passée en v2 sur les données de vent
avec des breaking changes — qu'est-ce qui a changé ? », le tool **ne peut pas répondre**, et
pire, il répondrait l'état v1 avec aplomb sans signaler sa péremption (le dict n'a aucune
notion d'historique, ni de « avant/après »). Le dict est par ailleurs un **doublon** de ce
qui devrait vivre dans les contrats : deux sources de vérité divergentes.

Or le repo a déjà les primitives nécessaires : contrats **ODCS v3** avec `version:` semver et
historique git = changelog ; pilote **OpenLineage/Marquez** en cours (cf. itération lineage
hors monolithe, wrapper cron + forwarder) ; orchestration **Kestra** qui *tire déjà* la
donnée des sources ; patron de test de contrat (`tools/check_schema_*.py`) et `data-samples/`.

## Décision

Tracer **et** versionner les schémas de sources externes importantes, et exposer leurs
changements comme faits interrogeables. Quatre piliers, principe directeur **« le runtime
signale, git fait foi, le tool lit git »** :

1. **A — ODCS comme source de vérité unique.** Chaque source externe importante (DPObs,
   DPPaquetObs, DPRadar, AROME-*, ARPEGE, PIAF, climato-data-gouv…) devient un **contrat ODCS
   de plein droit**, `tags: [source, meteofrance]`, `server` pointant l'API, `schema.properties`
   = champs **bruts** (`ff` m/s, `dd` degré, `t` Kelvin…) avec `logicalType` + unité. Les quirks
   non couverts par ODCS (gabarit d'URL, contexte, taxonomie d'erreurs, segments) vont en
   **`customProperties`**. Le dict du bot est **supprimé** ; `meteofrance_catalog.py` devient
   une **vue** qui lit ces contrats depuis le snapshot data-platform (déjà synchronisé côté
   bot/MCP) et rend contract / schema / unités. Nouveau `topic="changes"` (param `since`
   optionnel) qui renvoie l'historique → rend la question « qu'a changé et quand » répondable.

2. **B — le changement = un fait de lineage, double plan (B3).**
   - **Git (fait foi)** : bump `version:` semver (mineur = additif/non-breaking, majeur =
     breaking) + un bloc **`changelog:`** structuré dans le contrat, liste de
     `{version, date, type, severity, fields, note}`. Diffable, revu en MR, lu directement
     par le tool.
   - **Runtime (signale)** : la détection émet un `RunEvent` **OpenLineage** (facet schema)
     vers Marquez — le changement devient un fait de lineage interrogeable côté observabilité.
   - **Sévérité à 3 niveaux** : `breaking` (champ supprimé/renommé, type ou **unité** changés,
     sémantique modifiée), `non-breaking` (champ ajouté, doc), `deprecated` (champ encore servi
     mais voué à disparaître — porte le préavis de migration).
   - **Humain dans la boucle** : la détection *ouvre une issue*, un mainteneur *qualifie* la
     sévérité et acte le bump en **MR**. C'est le traitement « au même rang qu'un changement de
     contrat ».

3. **C — détection (C1 + C3).**
   - **C1 (primaire, temps réel)** : une **sentinelle de schéma** réutilisable dans les flows
     Kestra d'ingestion (qui tirent déjà la donnée). Elle dérive le schéma *observé* du payload,
     le diffe contre le `schema` du contrat, classe la dérive selon la taxonomie de sévérité, et
     sur dérive : émet l'événement OpenLineage **et** ouvre une issue data-platform (capacité
     déjà présente dans le bot) avec le diff.
   - **C3 (garde-fou reproductible)** : `data-samples/<source>/<daté>` capturé + test CI (patron
     `tools/check_schema_*.py`) validant le contrat contre l'échantillon. La dérive ressort en MR
     au rafraîchissement de la capture ; l'échantillon sert aussi de fixture de test au tool.
   - C2 (watcher de descripteurs MF) écarté comme mécanisme primaire (en retard sur le réel,
     muet sur les APIs sans descripteur) — réservé aux sources purement fichier sans ingestion.

4. **Découpage en tranches** (chaque tranche autonome, valeur dès la 1) :
   1. **Fondation (A + tool-vue)** : 2-3 sources MF modélisées en ODCS avec `changelog` +
      `customProperties` ; `meteofrance_catalog.py` réécrit en vue ; `topic="changes"`.
   2. **C3** : samples figés + test CI de contrat.
   3. **C1 + B-runtime** : sentinelle Kestra (OpenLineage + ouverture d'issue sur dérive).
   4. **Généralisation** à toutes les sources importantes.

## Justification

- **Un seul formalisme, un seul versioning.** Réutiliser ODCS (déjà porteur de `version:` et de
  l'historique git) plutôt qu'un format dédié élimine le doublon dict↔contrat et place les
  sources externes au même rang que l'interne — l'exigence de départ.
- **Le tool reste simple et offline.** En lisant git (contrats + changelog) il répond sans
  dépendre d'un service runtime ; Marquez n'est sollicité que pour le plan observabilité.
- **Détection au plus près du réel et gratuite en I/O.** C1 s'appuie sur la donnée que le flow
  tire déjà ; C3 garantit la reproductibilité et fournit les fixtures.
- **Breaking qualifié par un humain.** L'issue + MR évite qu'une dérive cosmétique soit classée
  breaking (et inversement) — la sévérité engage un préavis de migration, elle se décide.
- **Réversible et incrémental.** La tranche 1 livre la valeur (question « qu'a changé » répondable)
  sans toucher à Kestra ; les tranches suivantes s'ajoutent sans réécriture.

## Conséquences

- (+) La question « variable de vent renommée en v2, quand et quelle sévérité » devient
  répondable par le bot ET le MCP, comme un changement de contrat interne.
- (+) Fin du doublon : `meteofrance_catalog.py` n'est plus une source de vérité, juste un moteur
  de rendu — moins de dérive de maintenance.
- (+) Toute dérive de source externe laisse désormais une trace (issue + changelog + événement
  OpenLineage), audit-able.
- (−) Coût initial de modélisation : écrire les contrats ODCS des sources (le savoir existe déjà
  dans le dict, c'est une transcription, pas une découverte).
- (−) ODCS n'a pas de bloc changelog natif → on l'introduit en extension (`changelog:`) ; à
  surveiller vis-à-vis de l'évolution du standard. Critère de réouverture : si une version
  future d'ODCS standardise un historique de schéma, migrer vers le champ natif.
- (−) La sentinelle C1 ajoute une étape (et un risque de faux positifs) aux flows ; mitigé par la
  classification de sévérité et la boucle humaine (jamais de bump automatique).

## Références

- `ic-data-bot/src/ic_data_bot/meteofrance_catalog.py` (dict actuel à transformer en vue)
- `contracts/*.odcs.yaml` (formalisme ODCS v3, `version:`), `inventory/external-sources.yaml`
- `tools/check_schema_*.py` (patron du test de contrat C3)
- ADR-0001 (index de code — précédent de tool-vue sur artefact versionné)
- Open Data Contract Standard (ODCS) v3 ; OpenLineage (facet schema) / Marquez
