# Dataset — Export OpenData Infoclimat (v2)

| | |
|---|---|
| **Contrat** | [`contracts/opendata-export.odcs.yaml`](../../contracts/opendata-export.odcs.yaml) |
| **Domaine** | OpenData (consommateurs externes) |
| **Interface** | `opendata-v2/` — téléchargement CSV/JSON authentifié |
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
