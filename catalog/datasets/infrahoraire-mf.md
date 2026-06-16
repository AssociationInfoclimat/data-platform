# Dataset — Observations infrahoraires Météo-France

| | |
|---|---|
| **Contrat** | [`contracts/infrahoraire-mf.odcs.yaml`](../../contracts/infrahoraire-mf.odcs.yaml) |
| **Domaine** | Observations temps réel |
| **Stockage** | TimescaleDB (PostgreSQL) — tables `"Infrahoraire"` (historique) et `"InfrahoraireTempsReel"` (temps réel) |
| **Fallback** | MariaDB `mf_data` (pattern dual-source) |
| **Pas temporel** | 6 minutes |
| **Owner** | pam (data engineer) |

## Flux

> Mise à jour 2026-06-17 : ingestion désormais tracée vers les repos dédiés (intégrés à l'inventaire).

```
api://meteofrance/meteo-data-gouv-daily   (archives object.files.data.gouv.fr/.../BASE/MN)
  → repo telechargement-climatologie-meteo-data-gouv  (save/saveInfrahorairesCSVsToDB.ts)
  → timescaledb://postgres/Infrahoraire             (historique, clé AAAAMMJJHHMN)

api://meteofrance/climatologie-portail-api  (API MF DPObs/DPPaquetObs infrahoraire-6m)
  → repo telechargement-climatologie-portail-api-meteofrance  (flux */3 + rattrapage 24 h)
  → timescaledb://postgres/InfrahoraireTempsReel    (temps réel, clé validity_time)

  → include/MeteoFrance/infrahoraires.php + combined.php (lecture dual-source)
  → cartes/, stations-meteo/, mobile-api/, cron climato
```

## Consommateurs connus

- `stations-meteo/tableaux.php`, `stations-meteo/getData*` — affichage détail station
- `data/cartes/generer_une_carte_etiquettes.php` — cartes étiquettes (source `mf_timescale`)
- `mobile-api/` — endpoints station/carte
- `cron/climato*.php` — agrégats climatologiques (normales, annuelle)

## Points d'attention

- **Unités SI côté temps réel** (Kelvin, Pa, m/s) vs conventions MF côté historique (°C et
  1/10) : voir [glossaire](../glossary.md#%EF%B8%8F-pi%C3%A8ges-dunit%C3%A9s-source-danomalies-classiques).
- La jointure historique/temps réel (`NUM_POSTE` = `geo_id_insee`) est de type FULL JOIN :
  une mesure peut exister d'un seul côté.
- Le mois courant est exclu de certains agrégats climato (cf. commit « ignore current
  month mf timescale data »).

## Documentation source

- `include/MeteoFrance/docs/H_HTR_I_ITR.txt` — dictionnaire complet des colonnes
- `include/MeteoFrance/docs/{Temperatures,Precipitations,Pressions,...}.txt` — par famille
