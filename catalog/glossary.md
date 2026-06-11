# Glossaire métier — données Infoclimat

Vocabulaire partagé entre les bases, les pipelines et les contrats. Référence détaillée des
paramètres Météo-France : `include/MeteoFrance/docs/*.txt`.

## Identifiants de station

| Terme | Définition |
|---|---|
| `NUM_POSTE` | Numéro Météo-France du poste sur 8 chiffres (tables historiques MF : `Infrahoraire`, `Horaire`...) |
| `geo_id_insee` | ID du point au format `ddnnnpp` : `dd` = département, `nnn` = commune (`ddnnn` = code Insee), `pp` = précision du site (tables temps réel MF : `InfrahoraireTempsReel`, `HoraireTempsReel`) |
| `id_station` (StatIC) | Identifiant alphanumérique Infoclimat d'une station du réseau StatIC (référentiel `V5_data_params.static`) |
| `MFID` | Identifiant MF d'une station dans les référentiels Infoclimat (mapping vers `NUM_POSTE`) |

`NUM_POSTE` et `geo_id_insee` désignent le même poste : la jointure entre tables historique
et temps réel se fait sur ces deux colonnes (cf. `include/MeteoFrance/infrahoraires.php`).

## Axes temporels

| Terme | Définition |
|---|---|
| `AAAAMMJJHHMN` | Clé temporelle des tables MF historiques (UTC) — année mois jour heure minute |
| `AAAAMMJJHH` | Idem au pas horaire |
| `validity_time` | Date/heure de validité de la mesure (UTC, ISO-8601) — tables temps réel |
| `reference_time` | Date/heure de production de la donnée par MF |
| `insert_time` | Date/heure d'insertion en base |
| `dh_utc` | Convention Infoclimat : date/heure UTC de la mesure (StatIC, exports, vues combinées) |
| Infrahoraire | Pas de 6 minutes (MF) ; le réseau StatIC est au pas nominal de 5 minutes |
| Décade | Découpage StatIC du mois en 3 tables : `d1` (1-10), `d2` (11-20), `d3` (21-fin) |

## Paramètres météo usuels

| Mnémonique MF | Nom Infoclimat | Définition | Unité MF (historique) | Unité temps réel / StatIC |
|---|---|---|---|---|
| `T` / `t` | `temperature` | Température sous abri à 2 m | °C (et 1/10) | **K** (MF TR) / °C (StatIC) |
| `TD` / `td` | `point_de_rosee` | Point de rosée | °C | K (MF TR) / °C (StatIC) |
| `TN`, `TX` | `temperature_min/max` | Extrêmes de température sur la période | °C | K / °C |
| `U` / `u` | `humidite` | Humidité relative | % | % |
| `RR1` / `rr1` | `pluie_1h` | Précipitations sur 1 h | mm (et 1/10) | mm |
| `RR` / `rr_per` | — | Précipitations sur 6 min | mm | mm |
| `FF` / `ff` | `vent_moyen` | Vent moyen 10 min à 10 m | m/s (et 1/10) | **m/s** (MF) / **km/h** (StatIC, opendata) |
| `FXI` / `fxi` | `vent_rafales` | Rafale instantanée maximale | m/s | m/s (MF) / km/h (StatIC) |
| `DD` / `dd` | `vent_direction` | Direction du vent (rose de 360) | deg | deg |
| `PMER` / `pmer` | `pression` | Pression niveau mer | hPa (et 1/10) | **Pa** (MF TR) / hPa (StatIC) |
| `PSTAT` / `pres` | — | Pression station | hPa | Pa |
| `VV` / `vv` | `visibilite` | Visibilité horizontale | m | m |
| `N` / `n` | `nebulosite` | Nébulosité totale (9 = ciel invisible) | octa | octa |
| `WW` | `temps_omm` | Code temps présent (OMM table 4677) | code | code |
| `SSS` / `sss` | `neige_au_sol` | Épaisseur de neige au sol | m | m (MF) / cm (opendata) |
| `GLO` / `ray_glo01` | `radiations` | Rayonnement global | J/cm2 (MF) | J/m2 (MF TR) / W/m2 (opendata) |
| `INS` / `insolh` | `ensoleillement` | Durée d'insolation | mn | mn / heures (opendata) |
| `SOL` / `etat_sol` | — | Code état du sol (0=sec ... 3=inondé...) | code | code |

## ⚠️ Pièges d'unités (source d'anomalies classiques)

- **Kelvin vs Celsius** : les tables MF *temps réel* (`*TempsReel`) sont en **Kelvin** ;
  les tables MF *historiques* et tout l'écosystème Infoclimat sont en **°C**.
- **Pa vs hPa** : pression en **Pa** côté MF temps réel, **hPa** partout ailleurs.
- **m/s vs km/h** : vents MF en **m/s**, vents StatIC et opendata en **km/h**.
- **« et 1/10 »** : les fichiers climatologiques MF expriment certaines grandeurs au dixième.
- Les bornes de validité par paramètre sont déclarées dans les contrats ODCS
  (`../contracts/`) — source de vérité du contrôle qualité.

## Réseaux et sources

| Terme | Définition |
|---|---|
| StatIC | Réseau de stations amateurs Infoclimat (matériel contributeur ou association) |
| Synop | Stations synoptiques officielles (METAR/SYNOP, sources metno1, ogimet, bufr...) |
| MF | Météo-France (API + fichiers climatologiques, stockage TimescaleDB) |
| `source` | Canal logiciel d'acquisition d'une obs StatIC (weatherlink, vws, liveobjects, oy1110...) |
| LiveObjects / TTN | Réseaux LoRaWAN (Orange / The Things Network) pour capteurs IoT |
| Temps calme | Observations qualitatives communautaires (`V5.temps_calme`), modérées |

## Licences et exposition

| Terme | Définition |
|---|---|
| `licence` (station) | Niveau d'autorisation d'exposition des données d'une station StatIC (commerciale / non commerciale) |
| Whitelist opendata | `opendata-v2/authorized-stations.inc.php` — stations exposables aux consommateurs commerciaux |
