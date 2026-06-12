# Dataset — Modèles NWP (fichiers GRIB/NetCDF)

| | |
|---|---|
| **Contrat** | [`contracts/modeles-nwp-fichiers.odcs.yaml`](../../contracts/modeles-nwp-fichiers.odcs.yaml) (draft) |
| **Domaine** | Modèles NWP |
| **Stockage** | `file://srx-modeles-2/modeles/` (host-local srx-modeles-2) + `file://modeles/modeles.infoclimat.net` (NFS) |
| **Formats** | GRIB2 (GFS, GEFS, ECMWF, GEM, GEMENS) ; GRIB2/NetCDF (AROME, ARPEGE) |
| **Rétention** | Purge automatique (cleanup-modeles-ncl) : mtime+2j pour AROME/AROMEhr/GFS/GEFS/GFSHD |
| **Owner** | pam |

## Inventaire des modèles

| Modèle | Chemin | Source | Pipeline | Statut |
|---|---|---|---|---|
| AROME | `modeles/AROME/` | api://meteofrance/dcpc-nwp | `cron.recup-arome` (srx-modeles-2) | actif |
| AROMEhr | `modeles/AROMEhr/` | api://meteofrance/dcpc-nwp | `cron.recup-arome-hr` | actif |
| AROME_antilles | `modeles/AROME_antilles/` | api://meteofrance/dcpc-nwp | `cron.recup-arome-antilles` | actif |
| ARPEGE | `modeles/ARPEGE/` | api://data.gouv.fr/meteofrance-pnt-arome | `cron.recup-arpege` | actif |
| GFS (0.5°) | `modeles/GFS/` | api://noaa/nomads-gfs | `kestra.infoclimat.forecast.gfs.fetch-gfs-modeles-2` | mort (disabled) |
| GFSHD (0.25°) | `modeles/GFSHD/` | api://noaa/nomads-gfs | même pipeline | mort (disabled) |
| GFS1deg | `modeles/GFS1deg/` | api://noaa/nomads-gfs | même pipeline | mort (disabled) |
| GEFS | `modeles/GEFS/` | api://noaa/nomads-gefs | `kestra.infoclimat.forecast.gefs.fetch-gefs-modeles-2` | mort (disabled) |
| ECMWF | `modeles/ECMWF/` | api://ecmwf/opendata (FTP) | `kestra.infoclimat.forecast.ecmwf.fetch-ecmwf-modeles-2` | mort (disabled) |
| GEM | `modeles/GEM/` | api://eccc/model-gem-global | `kestra.infoclimat.forecast.gem.fetch-gem-modeles-2` | mort (disabled) |
| GEMENS | `modeles/GEMENS/` | api://eccc/ensemble-naefs | `kestra.infoclimat.forecast.gemens.fetch-gemens-modeles-2` | mort (disabled) |

## Flux actif principal (AROME/ARPEGE)

```
api://meteofrance/dcpc-nwp
  → cron/recup_arome.php (srx-modeles-2, toutes les 5-10 min)
  → modeles/AROME/{date}{run}/*.grib2

modeles/AROME/
  → modeles-ncl/worker.sh (daemon permanent)
  → modeles-php/public-api → modeles.infoclimat.net
  → mariadb://V5/api_previ_acces (quota API)
```

## Points d'attention

- Tous les flows Kestra pour GFS/GEFS/ECMWF/GEM/GEMENS sont **désactivés** (status:mort).
  Les crons sur srx-modeles-2 pour AROME/ARPEGE sont actifs mais certains sont douteux
  (scripts prod non mappés dans les clones — à confirmer).
- Namespace `file://srx-modeles-2/` est un namespace host-local (srx-modeles-2) officialisé
  dans `lineage/namespaces.md`. Ces fichiers ne sont pas montés sur datastore.
- Une vue NFS (namespace `file://modeles/`) permet l'accès depuis
  d'autres hôtes — à préciser lors d'une prochaine introspection.
- Rétention 2j pour AROME/ARPEGE/GFS/GEFS/GFSHD via `cleanup-modeles-ncl`
  (`find ... -mtime +2 -delete`) sur srx-modeles-2.

## Documentation source

- `data-platform/inventory/file-datasets.yaml` — entrées `file://srx-modeles-2/modeles/`
- `data-platform/inventory/pipelines.yaml` — pipelines `kestra.infoclimat.forecast.*`
