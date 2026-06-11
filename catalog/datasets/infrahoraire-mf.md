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

```
API/fichiers Météo-France
  → include/MeteoFrance/load_data.php (ingestion)
  → TimescaleDB "Infrahoraire" / "InfrahoraireTempsReel"
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
