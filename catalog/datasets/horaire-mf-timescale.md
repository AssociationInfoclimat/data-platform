# Dataset — Observations horaires Météo-France (TimescaleDB)

| | |
|---|---|
| **Contrat** | [`contracts/horaire-mf-timescale.odcs.yaml`](../../contracts/horaire-mf-timescale.odcs.yaml) (draft) |
| **Domaine** | Observations |
| **Stockage** | TimescaleDB (PostgreSQL) — tables `"Horaire"` (historique) et `"HoraireTempsReel"` (temps réel) |
| **Pas temporel** | 1 heure |
| **Owner** | pam |

## Flux

> Mise à jour 2026-06-17 : les repos d'ingestion sont désormais intégrés à l'inventaire.
> Provenance et namespace `timescaledb://postgres` corrigés.

```
api://meteofrance/climatologie-portail-api   (API MF DPObs/DPPaquetObs station/horaire)
  → repo telechargement-climatologie-portail-api-meteofrance
      src/apps/horaire/downloadAllLastHorairesData.ts   (flux 13,43 * * * *)
  → timescaledb://postgres/HoraireTempsReel            (clé validity_time, temps réel)

api://meteofrance/meteo-data-gouv-daily      (archives object.files.data.gouv.fr/.../BASE/HOR)
  → repo telechargement-climatologie-meteo-data-gouv
      scripts/update-daily.sh → save/saveHorairesCSVsToDB.ts   (quotidien 0 8 * * *)
  → timescaledb://postgres/Horaire                     (hypertable historique, clé AAAAMMJJHH)

timescaledb://postgres/Horaire
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

- **`Horaire` (historique) et `HoraireTempsReel` (flux) ont deux writers distincts** :
  l'historique vient des archives data.gouv (repo `telechargement-climatologie-meteo-data-gouv`),
  le temps réel de l'API MF (repo `telechargement-climatologie-portail-api-meteofrance`).
  Identifiants différents : `NUM_POSTE` (historique) vs `geo_id_insee` (temps réel).
- Le flow `kestra.infoclimat.data.meteofrance.climatologie-meteo-data-gouv.hourly`
  est **désactivé** (status: mort) : aucun `scripts/update-hourly.sh` dans le repo intégré.
- Le wrapper prod `ingest-horaires-temps-reel.sh` (référencé par le flow Kestra portail-api)
  n'est pas versionné dans le repo, mais l'app pnpm sous-jacente et l'output sont tracés.
- La table `Horaire` est lue depuis `combined.php` en mode dual-source : si
  `InfrahoraireTempsReel` est indisponible, `Horaire` sert de fallback.

## Documentation source

- `data-platform/inventory/tables.yaml` — entrées `timescaledb://postgres/Horaire`
  et `HoraireTempsReel` (writers renseignés)
- `data-platform/inventory/pipelines.yaml` — pipelines `climatologie-meteo-data-gouv.daily`
  et `climatologie-portail-api.horaires`
- `data-platform/catalog/datasets/infrahoraire-mf.md` — documentation analogie infrahoraire
