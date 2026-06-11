# Dataset — Observations synoptiques et METAR — réseaux étrangers

| | |
|---|---|
| **Contrat** | [`contracts/synop-metar-reseau-etranger.odcs.yaml`](../../contracts/synop-metar-reseau-etranger.odcs.yaml) (draft — DDL attendu) |
| **Domaine** | Observations |
| **Stockage** | MariaDB `V5_data_{AAAA}` — tables `synop_{MM}_d{1-3}` et `metar_{MM}_d{1-3}` (même schéma partitionné que StatIC) |
| **Stockage fichiers** | `file://datastore/data/synop/`, `file://datastore/data/metar/` (tampons transit, purge 30j) |
| **Fréquence** | Toutes les 2 min (BUFR NOAA) ; toutes les 20-26 min (METAR/SYNOP Ogimet via cron site-legacy) |
| **Rétention** | Fichiers bruts : 30 jours (data/cleanup.sh) ; tables MariaDB : pas de purge horodatée trouvée |
| **Owner** | pam |

## Flux

```
api://noaa/bufr
  → data/recuperation/synop/bufr/recuperation.bufr.sh (cron srx-mysql-3)
  → insertion.php
  → mariadb://V5_data_{AAAA}/synop_{MM}_d{DEC}

api://arpa-piemonte/observations  (webgis.arpa.piemonte.it)
api://arpa-liguria/stations       (omirl.regione.liguria.it)
  → cron/arpa/piemonte.php + liguria.php (front2)
  → mariadb://V5_data_{AAAA}/synop_{MM}_d{DEC}

api://oleg-192.16.167.24/synop-fr  (cron site-legacy — douteux)
  → data/metars_synops/datas.txt (fichier transit)
  → data/metars_synops/*.php (scripts absent du repo — douteux)
  → mariadb://V5_data_{AAAA}/synop_{MM}_d{DEC} + metar_{MM}_d{DEC}
```

## Consommateurs connus

- `stations-meteo/tableaux.php` — affichage synoptique étranger
- `cron/update_vignettes.php` — vignettes cartes (via metar/synop)
- `data/cartes/generation_cartes.php` — génération cartes synoptiques

## Points d'attention

- Les scripts `data/metars_synops/recup_metars_europe.php`, `metars_europe.php`,
  `recup_synops_ogimet_historique.php` sont listés dans `cron/crontab` mais
  absents des clones — flux douteux (à confirmer par la vérité terrain de l'hôte).
- Les tables `synop_{MM}_d{1-3}` partagent la partition mensuelle/décadaire avec
  StatIC ; seule la source diffère (réseau étranger vs réseau Infoclimat).
- Source `api://oleg-192.16.167.24/synop-fr` : IP privée non résolue, potentiellement
  décommissionnée (statut douteux).

## Sources externes connues

- NOAA BUFR : `ftp://tgftp.nws.noaa.gov/data/observations/metar/` et surface synoptic
- ARPA Piemonte : `https://webgis.arpa.piemonte.it/static_gis/meteo/meteoPiemonte/txt/`
- ARPA Liguria : `https://omirl.regione.liguria.it/`
- Ogimet : via proxy IP privé (source dépréciée probable)
