# Réconciliation Météo-France — contrats des sources manquantes — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Combler les trous de la réconciliation inventaire↔contrats côté Météo-France : créer un contrat ODCS de source pour chaque source MF consommée mais non modélisée, en **minant le code réel du consommateur** (jamais d'invention).

**Architecture:** Mêmes contrats ODCS de source que la tranche 1 (`tags: [source, meteofrance, ...]`, `customProperties.externalSource` pour host/context/url/auth/quirks, `customProperties.changelog` avec une entrée initiale). Le tool du bot les charge automatiquement (loader `meteofrance_catalog.load_sources`). Aucune modif de code : data-only + vérification par le loader.

**Tech Stack:** YAML ODCS v3.0.2, validation par `ic_data_bot.meteofrance_catalog.load_sources`.

**Sources de vérité (par contrat, à miner) :** repos clonés sous `~/PycharmProjects/infoclimat/` — `site-infoclimat/`, `modeles-php/`, `telechargement-climatologie-portail-api-meteofrance/`. Référence inventaire : `inventory/external-sources.yaml` (entrées `api://meteofrance/*`).

**Règle anti-invention :** chaque champ/URL/quirk doit provenir du code mineé ou d'un descripteur officiel. Si aucun schéma de champ propre n'est dérivable, mettre `schema[0].properties: []` et renseigner `externalSource.descriptor` (comme `dpradar`/`dppaquetobs` en tranche 1). En cas de doute sur une valeur, la reporter verbatim + noter l'incertitude dans `quirks`.

**Gabarit :** copier la structure de `contracts/source-meteofrance-dpobs.odcs.yaml` (champs avec clé `unit:`) ou, pour les sources sans table de champs, de `contracts/source-meteofrance-dpradar.odcs.yaml`.

**RAPPEL YAML (un piège déjà rencontré 2×) :** toute valeur scalaire contenant `: ` (deux-points + espace), ou commençant par `[ { * & ! @ " ` `, DOIT être double-quotée ou mise en bloc `>-`. La vérification par le loader attrape les erreurs.

---

## Périmètre : 6 contrats à créer (+ 1 décision)

| # | Source (inventaire) | Fichier contrat | apiId | Vérité dans le code |
|---|---|---|---|---|
| 1 | `climatologie-portail-api` (**DPClim**) | `source-meteofrance-dpclim.odcs.yaml` | DPClim | repo `telechargement-climatologie-portail-api-meteofrance` |
| 2 | `DPVigilance` | `source-meteofrance-dpvigilance.odcs.yaml` | DPVigilance | `site-infoclimat/include/Vigilances/vigilances.php` |
| 3 | `donnees-libres-nivo` | `source-meteofrance-donnees-libres-nivo.odcs.yaml` | donnees-libres-nivo | cron `recup-donneespub-mf-enneigement` |
| 4 | `donnees-libres-marine` | `source-meteofrance-donnees-libres-marine.odcs.yaml` | donnees-libres-marine | `site-infoclimat/data/recuperation/mf-bouees.php` |
| 5 | `portail-mf-station` | `source-meteofrance-portail-mf-station.odcs.yaml` | portail-mf-station | `site-infoclimat/cron/image_mf.php` + `mf.controller.php` |
| 6 | `dcpc-nwp` | `source-meteofrance-dcpc-nwp.odcs.yaml` | dcpc-nwp | `modeles-php/GFS/script/recup_arpege05.async.php`, `recup_arome13.async.php`, `recup_arome_antilles.php` |
| (déc.) | `donnees-climatologiques` (normales) | — | — | crons `climato-normales.mois-*` — Task 7 décide : sous-cas de DPClim ou contrat distinct |

---

## Task 1 : Contrat DPClim (climatologie portail-api) — le plus riche

**Files:** Create `contracts/source-meteofrance-dpclim.odcs.yaml`

- [ ] **Step 1 : Miner le code et les descripteurs**

Run (read-only) :
```bash
cd ~/PycharmProjects/infoclimat/telechargement-climatologie-portail-api-meteofrance
grep -rinE "DPClim|commande-station|information-station|liste-stations|commande/fichier" src/ 2>/dev/null | head -30
ls docs/mf/*/                       # descripteurs par fréquence (horaire, infrahoraire, quotidienne, mensuelle, décadaire…)
sed -n '1,60p' docs/mf/donnees-horaires/H_descriptif_champs.csv
```
Relever : host (`portail-api.meteofrance.fr`), context (`/public/DPClim/v1`), endpoints réels (`/liste-stations`, `/information-station`, `/commande-station/{freq}`, `/commande/fichier`), auth (token OAuth2), le workflow asynchrone commande→fichier (quirk), et les fréquences (horaire/infrahoraire-6min/quotidienne/mensuelle/décadaire).

- [ ] **Step 2 : Écrire le contrat** en suivant le gabarit `dpobs`. Points obligatoires :
  - `tags: [source, meteofrance, api]`, `domain: climato`, `version: "1.0.0"`.
  - `servers[0].location: https://portail-api.meteofrance.fr/public/DPClim/v1`.
  - `schema[0].properties` : transcrire les **principaux** champs du descripteur horaire (au minimum les familles vent : `FF`, `FXY`, `FXI`, **`FXI3S`** (rafale 3 s), `DXI3S`, plus `T`/`TN`/`TX`, `RR`, `U`, `PMER` ; unités CONVENTIONNELLES — °C, 1/10, m/s — PAS SI). Pour la liste exhaustive, pointer `descriptor:` vers `docs/mf/donnees-horaires/H_descriptif_champs.csv`.
  - `externalSource.unitsNote` : « Unités CONVENTIONNELLES (°C, 1/10) + indicateurs qualité Q<PARAM>. »
  - `externalSource.quirks` : workflow **commande asynchrone** (commande-station renvoie un id, puis commande/fichier récupère le CSV), référentiel stations via liste-stations/information-station.
  - `changelog` : entrée initiale `version "1.0.0"`, `date "2026-06-10"`, `type initial`, `severity non-breaking`, `note: "Sourcé sur telechargement-climatologie-portail-api-meteofrance + descripteurs MF."` **PLUS** une entrée `"2.0.0" / "2026-06-15" / rename / breaking / fields [FXI, FXI3S, DXI3S]` documentant que la climato porte aussi la rafale FXI3S (cohérence avec DPObs v2 ; FXI3S est déjà présent dans le schéma climato — cf. prisma `FXI3S`/`QFXI3S`/`NBJFXI3S*`).
  - `team`/`support` : copier de `dpobs`.

- [ ] **Step 3 : Vérifier** (le loader doit charger DPClim) :
```bash
cd ~/PycharmProjects/infoclimat/data-platform && python3 -c "
import sys; sys.path.insert(0,'../ic-data-bot/src')
from ic_data_bot import meteofrance_catalog as cat
e = cat.find('.', 'DPClim'); assert e, 'DPClim non chargé (YAML invalide ?)'
print('DPClim OK, champs:', len(e['schema']['fields']), '| changelog:', len(e['changelog']))
"
```
Expected : DPClim chargé, champs > 0, changelog 2 entrées. Si échec → corriger le YAML (quoting des `: `).

- [ ] **Step 4 : Commit** (data-platform, **sans** trailer Co-Authored-By) :
```bash
git add contracts/source-meteofrance-dpclim.odcs.yaml
git commit -m "feat(contracts): source DPClim (climatologie portail-api) en ODCS (réconciliation MF)"
```

---

## Task 2 : Contrat DPVigilance

**Files:** Create `contracts/source-meteofrance-dpvigilance.odcs.yaml`

- [ ] **Step 1 : Miner** :
```bash
cd ~/PycharmProjects/infoclimat/site-infoclimat
grep -rinE "DPVigilance|vigilance.*v1|public-api.*[Vv]igilance" include/Vigilances/ 2>/dev/null | head -20
sed -n '1,80p' include/Vigilances/vigilances.php
```
Relever : context `/public/DPVigilance/v1`, endpoints (cartes de vigilance, textes, par département), auth token, format de réponse (JSON : couleurs par département + phénomènes). NB : distinct du contrat **table** `vigilances-meteo.odcs.yaml` (qui décrit les tables persistées) — ici c'est la **source API**.

- [ ] **Step 2 : Écrire** le contrat (gabarit `dpradar` si pas de table de champs propre) : `tags: [source, meteofrance, api]`, `domain: vigilance`, `servers[0].location: https://public-api.meteofrance.fr/public/DPVigilance/v1`, `externalSource` (host/context/url/auth token/probeUrl/quirks), `schema[0].properties` = champs si dérivables du code (couleur, phénomène, département, échéance), sinon `[]` + descriptor. `changelog` : initiale `2026-06-10` non-breaking. Lier dans une note au contrat table `vigilances-meteo`.

- [ ] **Step 3 : Vérifier** :
```bash
cd ~/PycharmProjects/infoclimat/data-platform && python3 -c "
import sys; sys.path.insert(0,'../ic-data-bot/src')
from ic_data_bot import meteofrance_catalog as cat
assert cat.find('.', 'DPVigilance'), 'DPVigilance non chargé'
print('DPVigilance OK')
"
```

- [ ] **Step 4 : Commit** : `feat(contracts): source DPVigilance en ODCS (réconciliation MF)`

---

## Task 3 : Contrat donnees-libres-nivo (nivologie)

**Files:** Create `contracts/source-meteofrance-donnees-libres-nivo.odcs.yaml`

- [ ] **Step 1 : Miner** le consommateur :
```bash
cd ~/PycharmProjects/infoclimat/site-infoclimat
grep -rinlE "enneigement|nivo|donneespub.*neige" cron/ data/ include/ 2>/dev/null | head
# puis lire le fichier trouvé (cron recup-donneespub-mf-enneigement)
```
Relever : URL/host réels (portail-api ou donneespubliques selon le code), auth, format (CSV/JSON nivo), produits (hauteur de neige, etc.).

- [ ] **Step 2 : Écrire** (gabarit `dpradar` si pas de champs) : `tags: [source, meteofrance, api]` (ou sans `api` si fichier libre), `domain: observations`, `externalSource` complet, `changelog` initiale `2026-06-10`.

- [ ] **Step 3 : Vérifier** : `cat.find('.', 'donnees-libres-nivo')` non nul.

- [ ] **Step 4 : Commit** : `feat(contracts): source donnees-libres-nivo (nivologie) en ODCS (réconciliation MF)`

---

## Task 4 : Contrat donnees-libres-marine (bouées)

**Files:** Create `contracts/source-meteofrance-donnees-libres-marine.odcs.yaml`

- [ ] **Step 1 : Miner** :
```bash
cd ~/PycharmProjects/infoclimat/site-infoclimat
sed -n '1,80p' data/recuperation/mf-bouees.php
```
Relever : URL `https://donneespubliques.meteofrance.fr/donnees_libres/Txt/Marine/`, **auth: none**, format CSV (fopen direct), champs bouées (pression, vent, houle, T mer…).

- [ ] **Step 2 : Écrire** : `tags: [source, meteofrance]` (pas `api` — fichier libre sans gateway), `domain: observations`, `auth: none`, `externalSource` (host `donneespubliques.meteofrance.fr`, context `/donnees_libres/Txt/Marine/`, probeUrl = un fichier listé), `schema[0].properties` = champs bouées si dérivables du parsing CSV dans le PHP, sinon `[]` + descriptor. `changelog` initiale `2026-06-10`.

- [ ] **Step 3 : Vérifier** : `cat.find('.', 'donnees-libres-marine')` non nul ; `e['auth'] == 'none'`.

- [ ] **Step 4 : Commit** : `feat(contracts): source donnees-libres-marine (bouées) en ODCS (réconciliation MF)`

---

## Task 5 : Contrat portail-mf-station (images bulletins)

**Files:** Create `contracts/source-meteofrance-portail-mf-station.odcs.yaml`

- [ ] **Step 1 : Miner** :
```bash
cd ~/PycharmProjects/infoclimat/site-infoclimat
sed -n '1,80p' cron/image_mf.php
grep -rinE "portail-api|mf.controller|bulletin|image" include/**/mf.controller.php 2>/dev/null | head
```
Relever : endpoint portail-api utilisé pour les images de bulletins par station, auth token, format (image/PNG ou JSON+lien).

- [ ] **Step 2 : Écrire** (gabarit `dpradar`, produit non tabulaire) : `tags: [source, meteofrance, api]`, `domain: observations` (ou `cartes`), `externalSource` complet, `schema[0].properties: []` + `descriptor` décrivant le produit image, `changelog` initiale `2026-06-10`.

- [ ] **Step 3 : Vérifier** : `cat.find('.', 'portail-mf-station')` non nul.

- [ ] **Step 4 : Commit** : `feat(contracts): source portail-mf-station (images bulletins) en ODCS (réconciliation MF)`

---

## Task 6 : Contrat dcpc-nwp (service NWP legacy)

**Files:** Create `contracts/source-meteofrance-dcpc-nwp.odcs.yaml`

- [ ] **Step 1 : Miner** :
```bash
cd ~/PycharmProjects/infoclimat/modeles-php
for f in GFS/script/recup_arpege05.async.php GFS/script/recup_arome13.async.php GFS/script/recup_arome_antilles.php; do echo "### $f"; grep -inE "dcpc-nwp|PS_GetCache|token|PreviNum|GetCapabilities" "$f" 2>/dev/null | head; done
```
Relever : host `dcpc-nwp.meteo.fr`, service `/services/PS_GetCache_DCPCPreviNum`, auth `?token=` (env TOKEN_MF — **ne jamais copier le secret**), modèles servis (ARPEGE 0.5°, AROME 1.3°, AROME Antilles), format GRIB. C'est un service NWP **legacy** distinct du portail-api DPPaquet* — le noter en quirk.

- [ ] **Step 2 : Écrire** (gabarit `dpradar`) : `tags: [source, meteofrance, api]`, `domain: modeles`, `servers[0].location: http://dcpc-nwp.meteo.fr/services/PS_GetCache_DCPCPreviNum`, `externalSource.auth: token` (paramètre `?token=`, noté en quirk), `schema[0].properties: []` + descriptor, quirk « service DCPC PréviNum legacy, ≠ portail-api DPPaquetARPEGE/AROME ». `changelog` initiale `2026-06-10`.

- [ ] **Step 3 : Vérifier** : `cat.find('.', 'dcpc-nwp')` non nul.

- [ ] **Step 4 : Commit** : `feat(contracts): source dcpc-nwp (service NWP legacy) en ODCS (réconciliation MF)`

---

## Task 7 : Décision donnees-climatologiques (normales) + réconciliation finale

**Files:** éventuellement `contracts/source-meteofrance-donnees-climatologiques.odcs.yaml` ; sinon note dans le contrat DPClim. Modifier `inventory/external-sources.yaml` (ajout d'un cross-ref `contract:` par entrée MF).

- [ ] **Step 1 : Décider** : miner les crons `climato-normales.mois-*` / `climato.mensuelle` :
```bash
cd ~/PycharmProjects/infoclimat/site-infoclimat && grep -rinlE "normales|climato.*mensuelle|donneespub.*clim" cron/ data/ 2>/dev/null | head
```
Si l'endpoint = DPClim (même API, autre commande) → **documenter en quirk/note dans le contrat DPClim** (pas de nouveau fichier). Si endpoint distinct (ex. produit « normales » dédié) → créer `source-meteofrance-donnees-climatologiques.odcs.yaml` (gabarit `dpradar`, `changelog` initiale `2026-06-10`).

- [ ] **Step 2 : Cross-référencer l'inventaire** : dans `inventory/external-sources.yaml`, pour chaque entrée `api://meteofrance/*` désormais couverte, ajouter une ligne `notes` (ou un champ) pointant le contrat (`contract: source-meteofrance-<id>`), pour rendre la réconciliation traçable. Ne PAS renommer les entrées (les ids de pipeline en dépendent).

- [ ] **Step 3 : Vérification finale de réconciliation** :
```bash
cd ~/PycharmProjects/infoclimat/data-platform && python3 -c "
import sys; sys.path.insert(0,'../ic-data-bot/src')
from ic_data_bot import meteofrance_catalog as cat
ids = sorted(e['id'] for e in cat.load_sources('.'))
print('sources MF chargées (%d):' % len(ids)); print(ids)
# attendu : 11 initiales + DPClim, DPVigilance, donnees-libres-nivo, donnees-libres-marine,
# portail-mf-station, dcpc-nwp (+ éventuellement donnees-climatologiques) = 17 ou 18
assert len(ids) >= 17, ('trop peu — un contrat ne charge pas', ids)
print('overview:'); print(cat.overview('.')[:600])
"
```
Expected : ≥ 17 sources, toutes parsent, l'overview les liste. Aucun trou MF restant côté contrats.

- [ ] **Step 4 : Commit** : `feat(contracts): réconciliation MF complète + cross-ref inventaire (normales décidées)`

---

## Self-review (à l'écriture)

- **Couverture** : les 6 trous identifiés en réconciliation (DPClim, DPVigilance, nivo, marine, portail-mf-station, dcpc-nwp) ont chacun une task ; la 7ᵉ tranche le cas ambigu `donnees-climatologiques` + boucle la traçabilité inventaire.
- **Anti-invention** : chaque task commence par un Step de minage du code consommateur nommé explicitement (fichiers exacts tirés de `external-sources.yaml`), et autorise `properties: []` + descriptor quand aucun schéma propre n'existe.
- **Placeholders** : aucun « TODO » ; les commandes de minage et de vérification sont exactes. Les valeurs de champs ne sont pas pré-remplies à dessein (elles doivent venir du code, pas du plan) — le plan fournit le gabarit, les pointeurs de source, et la vérification par le loader.
- **Cohérence** : tous les contrats suivent le gabarit `dpobs`/`dpradar` de la tranche 1, `changelog` initiale datée `2026-06-10` (cohérent avec le baseline rétro-daté), vérification par `meteofrance_catalog.load_sources`.
- **Piège YAML** : rappelé en tête (quoting des `: `), déjà responsable de 2 incidents — la vérification par le loader le détecte à chaque task.
