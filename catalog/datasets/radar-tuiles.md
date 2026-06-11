# Dataset — Données radar météo

| | |
|---|---|
| **Contrat** | Non défini (prévu) |
| **Domaine** | Radar |
| **Stockage** | MariaDB `V5` (tables `radar`, `cartes`, `cartes_tuiles`) + fichiers GeoTIFF/PNG `file://datastore/tiles/` |
| **Fréquence** | Toutes les 3 min (Kestra Docker MF) ; toutes les 5 min (cron MF direct) |
| **Rétention** | Fichiers : rétention inconnue (pas de purge datée trouvée) ; MariaDB : inconnue |
| **Owner** | pam |

## Sources

| Source | Pipeline | Statut | Notes |
|---|---|---|---|
| `api://meteofrance/donnees-libres-radar` (DPRadar) | `kestra.infoclimat.data.meteorology.download-and-convert-radar` | actif | Image Docker privée — sous-chemin output non traçable |
| `api://meteofrance/donnees-libres-radar` | `cron.radarmf` (srx-data-2) | actif | Script prod direct |
| `api://meteofrance/donnees-libres-radar` | `cron.compo-new` (srx-data-2) | actif | Composition tuiles |
| `api://meteomedia/radar` | `kestra.infoclimat.data.cartes.radar.compo-new-1` | mort | Flow disabled |

## Flux principal actif

```
api://meteofrance/DPRadar
  → Docker download-convert-and-generate-accumulations:1.0.3
    (kestra.infoclimat.data.meteorology.download-and-convert-radar, toutes les 3 min)
  → file://datastore/  (sous-chemin /radar présumé mais non traçable depuis le flow)

api://meteofrance/DPRadar
  → cron/radarmf.php + compo-new.php (srx-data-2)
  → mariadb://V5/radar + mariadb://V5/cartes + mariadb://V5/cartes_tuiles
  → file://datastore/tiles/radar/

mariadb://V5/radar + file://datastore/tiles/radar/
  → include/Radar/ + mapserver/radar.map
  → affichage carte radar temps réel
```

## Consommateurs connus

- `include/Radar/generate-radaric-mf-values-accumulations/` — accumulations pluie radar
- `cron/radar_process.py` — traitement Python (écriture `V5.cartes`)
- `include/communs/jsontiles.php` — tiles JSON (lecture `V5.cartes_tuiles`)
- `mapserver/radar.map` — affichage WMS
- `cron/notif_radar_v2.php` — notifications push mobiles

## Points d'attention

- Le pipeline Docker Kestra utilise une image privée ; les I/O précis (chemin de sortie
  des tuiles radar) ne sont pas traçables depuis le flow.
- `V5.cartes_tuiles` est peuplée par `mysqlconf.py` (Python) et `tiles.py` — deux
  scripts de la chaîne accumulations.
- La source Meteomedia (`compo_new_1.php`) est désactivée (flow Kestra disabled).

## Documentation source

- `data-platform/inventory/tables.yaml` — entrées `mariadb://V5/radar`, `V5/cartes`, `V5/cartes_tuiles`
- `data-platform/inventory/file-datasets.yaml` — tuiles radar
