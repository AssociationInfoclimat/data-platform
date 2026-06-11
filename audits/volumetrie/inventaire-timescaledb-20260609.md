# Volumétrie TimescaleDB — ct-timescale (db=postgres) — 2026-06-09

Source : introspection en lecture seule (PostgreSQL / TimescaleDB).

**37 relations** (tables + hypertables + matviews, schéma `public`) — **780.8 GiB** au total.

Hypertables = tailles agrégées sur tous les chunks (`hypertable_detailed_size`).
Le schéma `cron` (pg_cron) est hors du périmètre introspecté.

## Top 12 par taille totale

| relation                    | type       | lignes (est.) |      total |
|-----------------------------|------------|--------------:|-----------:|
| Infrahoraire                | hypertable | 2 827 541 504 | 477.40 GiB |
| Horaire                     | hypertable |   589 952 832 | 199.35 GiB |
| InfrahoraireTempsReel       | hypertable |   170 777 184 |  36.45 GiB |
| Quotidienne                 | table      |   134 346 192 |  29.90 GiB |
| QuotidienneAutresParametres | table      |    53 944 516 |  11.98 GiB |
| Decadaire                   | table      |    13 770 095 |   6.13 GiB |
| mv_quotidienne_tn           | matview    |    51 707 716 |   5.68 GiB |
| mv_quotidienne_tx           | matview    |    51 555 320 |   5.67 GiB |
| HoraireTempsReel            | hypertable |    18 165 216 |   4.30 GiB |
| Mensuelle                   | table      |     5 086 026 |   2.02 GiB |
| DecadaireAgro               | table      |     2 914 602 |   0.73 GiB |
| mv_record_event_min_history | matview    |     4 375 677 |   0.51 GiB |
