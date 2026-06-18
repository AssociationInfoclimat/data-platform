# Audit des contrats de source Météo-France vs Confluence officiel — 2026-06-18

Source de vérité : espace Confluence **OPEN DATA METEO-FRANCE**
(`confluence-meteofrance.atlassian.net/wiki/spaces/OpenDataMeteoFrance`), pages lues via navigateur
(rendu JS) + API REST Confluence. Météo-France est notre source externe n°1 → exhaustivité requise.

Méthode : énumération des 52 pages de l'espace (REST CQL), lecture page par page des APIs modélisées,
et de chaque actualité datée de la page « Toute l'actualité » (1516437510). Chaque constat cite l'ID
de page MF.

## A. Couverture — nos 17 contrats vs le catalogue MF

Le catalogue MF (page 853737487) liste les APIs par catégorie. Correspondance :

| API MF (page) | Notre contrat | État |
|---|---|---|
| API Ciblée Données d'Observation (853639294) | dpobs | ⚠️ incomplet (cf. C1) |
| API Paquet Observations (854851588) | dppaquetobs | ⚠️ (cf. C1) |
| API Données Climatologiques (854261785) | dpclim | ⚠️ (cf. C4) |
| API Ciblée Radar (853639355) | dpradar | ⚠️ enrichir (cf. C5) |
| API Paquet Radar (853606673) | dppaquetradar | ✅ conforme |
| API Ciblée Modèles (854032416) | arome-wcs, aromepi | ✅ (AROME IFS déjà ajouté) |
| API Paquet Modèles (853639487) | arome-paquets, arome-om, arpege-paquets | ✅ conforme |
| API Bulletin Vigilance (854065168) | dpvigilance | ⚠️ corrections (cf. C3) |
| (archives meteo.data.gouv.fr) | climato-data-gouv | ⚠️ (cf. C6) |
| (donnees_libres) | donnees-libres-nivo, donnees-libres-marine | ✅ (dépréciation déjà notée) |
| — hors espace open-data | dpclim?/dcpc-nwp, portail-mf-station, piaf | cf. notes |

**APIs MF NON modélisées (non consommées par Infoclimat — à signaler, pas des trous) :**
API Bulletin Avalanche (854196230), API Météo des forêts (853934302), API Ciblée PE Modèles
(853934184 — ARPEGE PE + AROME PE, lancées 03/2025, page 672333871), API Environnement (1612906576),
Modèle de Vague & Surcôte (couvert par Paquet Modèles, MFWAM GLOB01 depuis 03/2025).

**PIAF** : n'apparaît PAS dans l'espace open-data (gateway commercial `api.meteofrance.fr`). NB : la
page API Ciblée Modèles (854032416) cite « PIAF (AROME-PI Agrégée Fusionnée) » parmi ses collections
WMS/WCS — **ambiguïté à lever** : PIAF est-il aussi exposé en ciblé public, ou seulement commercial ?
Notre contrat le modélise en commercial (`/pro/piaf`). À vérifier (souscription séparée confirmée).

## B. 🔴 Changement transverse BREAKING non capté : harmonisation des identifiants de stations

Page MF **1603796993** — « Météo-France harmonise ses identifiants de stations : ce qui change le
**16 avril 2026** ».
- `num_poste` = code INSEE de la commune de rattachement + n° d'ordre. Le **FORMAT ne change pas** ;
  ce sont les **VALEURS** qui changent pour ~15 stations dont la commune de rattachement a évolué.
  Exemples : ROUSSET `05127001`→`04033001` ; PEGOMAS-TANNERON `06090001`→`83133003` ;
  JOINVILLE-LE-PONT `75044001`→`94046003`.
- **Bascule directe le 2026-04-16, SANS période de cohabitation → rupture.**
- Champs touchés : `num_poste` / `Id_station` / `id`, `num_dep`, `commune` (noms de colonnes inchangés).
- **APIs concernées : API Ciblée Obs (DPObs), API Paquet Obs (DPPaquetObs), API Données Climato
  (DPClim), et meteo.data.gouv.fr (climato-data-gouv).**
- Impact Infoclimat : toute jointure/référentiel station basé sur `num_poste`/`id_station` pour ces
  postes casse au 16/04/2026.
→ **ACTION** : entrée changelog `severity: breaking`, `type: referentiel`, `date: 2026-04-16`,
  `version: 1.1.0`, dans **dpobs, dppaquetobs, dpclim, climato-data-gouv**.

## C. Corrections par contrat

### C1. DPObs (+ DPPaquetObs) — page 853639294 (MAJ 2026-03-12)
Notre contrat ne documente que les **stations terrestres**. L'API couvre en réalité **3 sous-produits** :
- **Terrestre** : `/liste-stations`, `/station/horaire`, `/station/infrahoraire-6m` — id 8 chiffres
  (zéro initial obligatoire dépt 01–09 ; erreur 400 « Identifiant station sémantiquement incorrect »
  sinon), rétention 24 h.
- **SYNOP** : `/liste-stations-synop`, `/synop` — id **OMM 5 chiffres** (`geo_id_wmo`, zéro initial),
  tri-horaire, **rétention 5 jours**, paramètres `date_debut`/`date_fin`.
- **Bouées** : `/liste-bouees`, `/bouees` — id **7 chiffres** (`id_bouees`), horaire, rétention 5 j.
→ **ACTION** : ajouter SYNOP + bouées (endpoints, id, rétention) en quirks/schema ; idem note DPPaquetObs.
Champs JSON confirmés (exemple MF) : `geo_id_insee, reference_time, insert_time, validity_time, t, td,
u, dd, ff, dxi10, fxi10, rr_per, t_10/20/50/100, vv, etat_sol, sss, insolh, ray_glo01, pres, pmer`
(+ ajouter `insert_time`, `etat_sol`, `sss`, `rr_per` manquants chez nous).
NB v2 rafale déjà corrigée (raf/ddraf/raf10/ddraf10) — conforme à la page 1688633417.

### C3. DPVigilance — page 854065168
- Endpoint réel **`/vignettenationale-J-et-J1/encours`** (nous avions `vignettenationale-J/encours`) → corriger.
- Endpoints **Outre-mer manquants** : `/vigilanceom/controle/dernier`, `/vigilanceom/flux/dernier`
  (ZIP + checksum) → ajouter.
- `color_id` : la doc indique **1-3** (jaune/orange/rouge) ; notre quirk (issu du code) disait API 1-4 /
  legacy 0-3 → **incohérence à lever** (vert = 0 ou 1 ?). Marquer comme « à confirmer », ne pas trancher
  arbitrairement.
- Schéma V6 référencé ; **Nouvelle-Calédonie migre V6, arrêt flux V5** (04/2026, page 1641480275) +
  Vigilance Outre-mer (02/2025) → note.
- Phénomènes confirmés : crues, vents, pluies/orages, vagues-submersion, etc.

### C4. DPClim — page 854261785 (+ actualités)
- Endpoints confirmés : `/liste-stations/{freq}`, `/information-station`,
  `/commande-station/{infrahoraire-6m|horaire|quotidienne}`, `/commande/fichier` — workflow asynchrone
  4 étapes ✅ (conforme à notre contrat).
- **FXI3s devient la référence rafale en climato** (06/2026, page 1697218579) : **NON-breaking** — FXI
  (instantané) ET FXI3S (max des moyennes 3 s) **coexistent**, FXI **reste disponible**, FXI3S
  *recommandé* pour les nouvelles études. Aucun changement d'accès. → entrée changelog `non-breaking`,
  `date: 2026-06`, distincte du remplacement breaking temps réel DPObs.
- « Évolution des conditions d'interrogation de l'API Données Climatologiques » (page 1507098626,
  02/2026) + « Déploiement nouvelle version API ciblée Climato » (669188141, 03/2025) → à lire en détail
  pour confirmer version/conditions (faible priorité ; non bloquant).
- Station harmonization (B) s'applique.

### C5. DPRadar — page 853639355 (enrichissement ; actuellement properties: [])
- Endpoints : `/mosaiques`, `/mosaiques/{zone}/observations/{obs}/produit?maille={res}`,
  `/liste-stations`, `/stations`, `/stations/{id}/observations/{obs}/produit?tour_antenne={n}`.
- Produits : **REFLECTIVITE, LAME_D_EAU, PAM, PAG** (80 niveaux). Formats : **BUFR (1000 m), HDF5
  (500 m)**. Rétention 20 h, fréquence 5 min, 30+ sites métropole + 6 OM.
- Évolutions réseau radar : Sembadel coupé 3 mois (dès 2026-04-01), Wideumont intégré (03/2026),
  Trappes réintégré (12/2025), Cherves renouvelé (08/2025), Nouvelle-Calédonie nouvelle chaîne (06/2026).
→ **ACTION** : enrichir produits/formats/endpoints + note évolutions réseau (opérationnel).

### C6. climato-data-gouv — meteo.data.gouv.fr
- Station harmonization (B) s'applique (num_poste).
- Enrichissements additifs : Messages Climat mensuels (06/2026), indicateur qualité ETP décadaire
  (04/2026), simulation nivologique (05/2025), historique cyclones SOOI (04/2026).
→ **ACTION** : notes additives + entrée harmonization.

## D. Conforme — pas d'action
- **DPPaquetRadar** (853606673) : /public/DPPaquetRadar/v1, /mosaique/paquet, /station/paquet, tar gzip,
  20 h, 15 min ✅.
- **Paquet Modèles** (853639487) : /previnum/DPPaquet*/v1, SP1/SP2/SP3/IP*, GRIB2, rétention 3 j ✅.
- **Ciblée Modèles** (854032416) : /public/arome/1.0/{wms,wcs}, AROME 0.025/0.01 + AROME IFS + AROME-PI,
  rétention 5 j ✅ (AROME IFS déjà intégré).
- **nivo / marine** : dépréciation donneespubliques déjà notée (commit antérieur) ✅.

## E. Synthèse des actions
1. 🔴 Entrée changelog **harmonisation identifiants** (breaking, 2026-04-16) → dpobs, dppaquetobs, dpclim, climato-data-gouv.
2. DPObs/DPPaquetObs : ajouter sous-produits **SYNOP** + **bouées** + champs manquants.
3. DPVigilance : corriger `vignettenationale-J-et-J1`, ajouter `vigilanceom/*`, noter color_id à confirmer + V6.
4. DPClim : entrée **FXI3S référence climato** (non-breaking, coexistence).
5. DPRadar : enrichir produits/formats/endpoints + évolutions réseau.
6. climato-data-gouv : notes additives (Messages Climat, ETP, nivo simulation).
7. Notes : APIs MF non consommées (Avalanche, Météo forêts, PE Modèles, Environnement, Vagues/Surcôte) ; ambiguïté PIAF ciblé/commercial.

## F. Résolutions (point 3 creusé) + corrections appliquées le 2026-06-18

- **PIAF** : CQL `title~PIAF/immédiate/AROME-PI` → 0 résultat open-data ; seule mention de passage
  « AROME-PI Agrégée Fusionnée (PIAF) » sur la page Ciblée Modèles (854032416), sans host →
  **confirmé commercial** (api.meteofrance.fr). Note ajoutée au contrat piaf.
- **DPClim conditions d'interrogation** (1507098626, 2026-02-05) : `commande-station/infrahoraire-6m`
  plafonné **1 an → 1 mois/requête** (6-min only) → **breaking** (changelog 1.1.0).
- **DPClim nouvelle version** (669188141, 2025-03-09) : pas de `/v2` (notre `/v1` tient) ; codes qualité
  + requêtes décadaires/mensuelles, coexistence transparente → quirk.
- **DPClim FXI3S** (1697218579, 06/2026) : **NON-breaking**, FXI et FXI3S coexistent → changelog 1.3.0.

**Corrections appliquées** (modélisation validée) : dpobs (SYNOP+bouées+champs+harmonisation 1.1.0),
dppaquetobs (harmonisation 1.1.0), dpclim (1.1.0 conditions / 1.2.0 harmonisation / 1.3.0 FXI3S),
dpvigilance (vignette-J-et-J1, vigilanceom/*, color_id à confirmer, V6 — 1.1.0), dpradar
(produits/formats/endpoints + réseau), climato-data-gouv (harmonisation 1.1.0 + enrichissements),
piaf (note commercial). **Parité 17 maintenue.**

**Reste non bloquant** : color_id DPVigilance (doc 1-3 vs code 1-4) à trancher sur réponse live ;
APIs MF non consommées non modélisées (choix assumé).
