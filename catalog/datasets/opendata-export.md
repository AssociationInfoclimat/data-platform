# Dataset — Export OpenData Infoclimat (v2)

| | |
|---|---|
| **Contrat** | [`contracts/opendata-export.odcs.yaml`](../../contracts/opendata-export.odcs.yaml) |
| **Domaine** | OpenData (consommateurs externes) |
| **Interface** | Observations : CSV/JSON authentifié (clé API). Métadonnées stations : GeoJSON/JSON public (sans clé) |
| **Amont** | StatIC ([fiche](static-stations-obs.md)), Synop, Météo-France ([fiche](infrahoraire-mf.md)) |
| **Profondeur** | Depuis 1996-01-01 |
| **Owner** | pam (data engineer) |

## Flux

```
StatIC + Synop + MF (bases V5_data_*, mf_data, TimescaleDB)
  → opendata-v2/common.inc.php (agrégation, mapping paramètres, contrôle d'accès)
  → export CSV/JSON par station/période
```

## Contrôle d'accès

- Clé API (tokens), reCAPTCHA pour le téléchargement manuel
- Conventions spéciales : Météo-France, ROMMA, AOC Ventoux
- Whitelist stations commerciales : `opendata-v2/authorized-stations.inc.php`
- Bans IP et rate limiting (logs vérifiés par `opendata-v2/verify_logs.php`)

## Points d'attention

- **C'est la promesse publique de l'association** : toute évolution du format ou des
  unités est une rupture de contrat vis-à-vis de consommateurs externes → bump MAJOR
  de version du contrat + communication.
- Les unités exposées sont les conventions Infoclimat (°C, hPa, km/h, mm) quelle que soit
  la source amont — la conversion (notamment Kelvin→°C, m/s→km/h) est faite à l'export.
- Évolution envisagée : exposition parquet via une future data API
  (`/v1/datasets/{name}/export?format=parquet`), gouvernée par ce même contrat.

## Export public des métadonnées stations (sans clé)

En complément de l'export des observations (authentifié), les **métadonnées** des
stations sont exposées **sans clé API** en GeoJSON (`FeatureCollection`) ou JSON sur
[`www.infoclimat.fr/opendata/`](https://www.infoclimat.fr/opendata/) :

- champs : `id`, `name`, `elevation`, `license` (objet complet), `country`,
  `departement`, `last_activity`, position (`geometry`) ;
- couvre les stations StatIC et synop Météo-France ;
- filtre par défaut sur les licences non fermées (`0,1,2`) ; un paramètre
  `display_closed` permet d'afficher l'ensemble ;
- ne sert que des **métadonnées** (pas d'observations) — la distinction observations
  (clé requise) / métadonnées (publiques) est intentionnelle.

Cette surface est décrite dans le contrat
[`static-stations-obs`](../../contracts/static-stations-obs.odcs.yaml)
(`publicMetadataExport`). Signalée par erratum (bot Discord) le 2026-06-12.
