# Dataset — Vues matérialisées climatologiques (TimescaleDB)

| | |
|---|---|
| **Contrat** | [`contracts/climato-mf-timescale.odcs.yaml`](../../contracts/climato-mf-timescale.odcs.yaml) (draft — colonnes après export du DDL) |
| **Domaine** | Climatologie |
| **Stockage** | TimescaleDB (PostgreSQL) — 6 vues matérialisées dans la base `infoclimat` |
| **Pas de rafraîchissement** | Toutes les 6 min (refresh-materialized-views) et toutes les 15 min (mv_records_battus) |
| **Owner** | pam |

## Tables (vues matérialisées)

| Table | Contenu | Producteur | Fréquence |
|---|---|---|---|
| `mv_quotidienne_realtime` | Agrégats quotidiens temps réel | refresh-materialized-views | 6 min |
| `mv_mensuelle_realtime` | Agrégats mensuels temps réel | refresh-materialized-views | 6 min |
| `mv_records_absolus_par_mois` | Records absolus par mois | refresh-materialized-views | 6 min |
| `mv_itn_daily_all_years` | Indicateur national journalier | refresh-materialized-views | 6 min |
| `mv_records_battus` | Records battus (historique) | refresh-mv-records-battus | 15 min |
| `mv_records_battus_realtime` | Records battus temps réel | refresh-mv-records-battus-realtime | désactivé |

## Flux

```
timescaledb://infoclimat/Infrahoraire
timescaledb://infoclimat/Horaire
  → REFRESH MATERIALIZED VIEW CONCURRENTLY
  → mv_quotidienne_realtime, mv_mensuelle_realtime,
    mv_records_absolus_par_mois, mv_itn_daily_all_years
  (kestra.infoclimat.db.dataclimat.refresh-materialized-views — toutes les 6 min)

timescaledb://infoclimat/Infrahoraire
timescaledb://infoclimat/Horaire
  → REFRESH MATERIALIZED VIEW CONCURRENTLY
  → mv_records_battus
  (kestra.infoclimat.db.dataclimat.refresh-mv-records-battus — toutes les 15 min)
```

## Consommateurs connus

- `climato/mgetData.php` — endpoint API climatologie (lecture mv_quotidienne_realtime,
  mv_mensuelle_realtime pour les graphes et comparaisons historiques)
- API mobile (lecture des records et indicateurs)

## Points d'attention

- `mv_records_battus_realtime` : le flow producteur
  `kestra.infoclimat.db.dataclimat.refresh-mv-records-battus-realtime` est **désactivé**
  (status: mort) — la vue existe mais n'est plus rafraîchie automatiquement.
- Les vues sont calculées à partir des données infrahoraires et horaires MF ; elles
  héritent des unités SI (Kelvin, Pa) de `InfrahoraireTempsReel` : voir le glossaire
  pour les pièges de conversion.
- `REFRESH MATERIALIZED VIEW CONCURRENTLY` requiert un index unique sur la vue ;
  un verrou exclusif serait bloquant pour les lectures — surveiller les latences.

## Documentation source

- `data-platform/lineage/jobs.yaml` — jobs OpenLineage des flows de refresh
- `data-platform/inventory/tables.yaml` — entrées `timescaledb://infoclimat/mv_*`
