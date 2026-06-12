# Dataset — Observations horaires Météo-France (TimescaleDB)

| | |
|---|---|
| **Contrat** | [`contracts/horaire-mf-timescale.odcs.yaml`](../../contracts/horaire-mf-timescale.odcs.yaml) (draft) |
| **Domaine** | Observations |
| **Stockage** | TimescaleDB (PostgreSQL) — tables `"Horaire"` (historique) et `"HoraireTempsReel"` (temps réel) |
| **Pas temporel** | 1 heure |
| **Owner** | pam |

## Flux

```
api://meteofrance/climatologie-portail-api
  → ingest-horaires-temps-reel.sh (ct-timescale, toutes les 30 min)
  → timescaledb://infoclimat/Horaire et HoraireTempsReel

api://meteofrance/meteo-data-gouv-monthly
  → update-monthly.sh (ct-timescale, mensuel)
  → timescaledb://infoclimat/Horaire (historique mensuel)

timescaledb://infoclimat/Horaire
  → include/MeteoFrance/combined.php (lecture dual-source avec InfrahoraireTempsReel)
  → climato/mgetData.php
  → kestra.infoclimat.db.dataclimat.refresh-materialized-views
```

## Consommateurs connus

- `climato/mgetData.php` — graphes climatologiques mensuels
- `include/MeteoFrance/combined.php` — source secondaire (fallback infrahoraire)
- `kestra.infoclimat.db.dataclimat.refresh-materialized-views` — rafraîchissement
  des vues matérialisées `mv_quotidienne_realtime`, `mv_mensuelle_realtime`, etc.

## Points d'attention

- Le flow `kestra.infoclimat.data.meteofrance.climatologie-meteo-data-gouv.hourly`
  est **désactivé** (status: mort). Le flow mensuel reste actif.
- Les scripts d'ingestion (`ingest-horaires-temps-reel.sh`, `update-monthly.sh`)
  sont sur ct-timescale mais absents des clones Git — I/O confirmés via les flows
  Kestra uniquement.
- La table `Horaire` est lue depuis `combined.php` en mode dual-source : si
  `InfrahoraireTempsReel` est indisponible, `Horaire` sert de fallback.

## Documentation source

- `data-platform/inventory/tables.yaml` — entrées `timescaledb://infoclimat/Horaire`
  et `HoraireTempsReel`
- `data-platform/catalog/datasets/infrahoraire-mf.md` — documentation analogie infrahoraire
