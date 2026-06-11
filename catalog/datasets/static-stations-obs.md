# Dataset — Observations du réseau StatIC

| | |
|---|---|
| **Contrat** | [`contracts/static-stations-obs.odcs.yaml`](../../contracts/static-stations-obs.odcs.yaml) |
| **Domaine** | Observations temps réel (communautaire) |
| **Stockage** | MariaDB — référentiel `V5_data_params.static`, séries `V5_data_{AAAA}.static_{MM}_d{1-3}` |
| **Pas temporel** | 5 minutes (nominal, variable selon matériel) |
| **Profondeur** | Depuis 1996 |
| **Owner** | pam (data engineer) |

## Flux

```
Station contributeur (weatherlink, vws, csv, LoRaWAN oy1110/liveobjects...)
  → ingestion (data/, liveobjects/_uplink_.php, ttn/)
  → MariaDB V5_data_{AAAA}.static_{MM}_d{décade}
  → include/stations/stations.php (lecture)
  → cartes temps réel, tableaux stations, opendata-v2/, climato communautaire
  → gestion-donnees/auto_control.php (contrôle qualité)
```

## Consommateurs connus

- `stations-meteo/`, `cartes/` — affichage temps réel
- `opendata-v2/common.inc.php` — export public (selon licence)
- `gestion-donnees/` — auto-contrôle, détection d'erreurs (`trouver_erreurs*.php`)
- `mobile-api/` — endpoints mobiles

## Points d'attention

- **Partitionnement manuel** par base-année / table mois-décade : toute requête
  multi-périodes doit itérer sur les partitions (cf. `include/stations/stations.php`).
  Candidat prioritaire à la conversion hypertable (migration phase 3).
- **Qualité hétérogène** : matériel amateur, trous de connectivité. La fraîcheur < 1 h
  vaut détection de panne station, pas d'anomalie pipeline.
- Le champ `complements` est un fourre-tout `@`-séparé : ne pas créer de nouvelle
  dépendance dessus sans contractualiser le sous-champ.
- `id_compte` relie la station à un compte utilisateur → **donnée personnelle indirecte**
  (registre RGPD à tenir dans `audits/rgpd/`).
