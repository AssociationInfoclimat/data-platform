# Dataset — API de prévision point (opendata)

| | |
|---|---|
| **Contrat** | [`contracts/previsions-api-opendata.odcs.yaml`](../../contracts/previsions-api-opendata.odcs.yaml) (draft) |
| **Domaine** | Prévisions |
| **Interface** | API HTTP GET publique — formats : `json`, `xml`, `csv`, `iframeSLIDE` |
| **Amont** | Modèles NWP ([fiche](modeles-nwp.md) / contrat `modeles-nwp-fichiers`) |
| **Méthodes** | `gfs` (modèle global) · `wrf` (AROME haute résolution) |
| **Fréquence** | Par run de modèle — GFS ~4×/j, AROME selon les runs Météo-France |
| **Owner** | pam (intérim, pôle Prévision & vigilance) |

## Description

API HTTP publique de prévision météo en un point (latitude/longitude), issue des modèles numériques
exploités par l'association. Elle sert une série temporelle de paramètres prévus par échéance.

Deux méthodes disponibles :

- **`gfs`** — modèle global (GFS NOAA), couverture mondiale, maille ~0,25°
- **`wrf`** — AROME haute résolution (Météo-France), couverture France métropolitaine et outre-mer,
  maille métrique

## Accès

Requête HTTP GET sur l'endpoint public `https://www.infoclimat.fr/opendata/` avec les paramètres :
latitude, longitude, méthode (`gfs` ou `wrf`), format de sortie.

L'accès automatisé (scripts, applications) nécessite une clé d'API, obtenue via le site. L'accès
manuel au travers du site web ne requiert pas de clé. Les modalités de quota et de contrôle d'accès
sont hors périmètre de ce contrat.

## Flux

```
Sorties modèles NWP (GRIB2/NetCDF, dernier run)
  → interpolation ponctuelle (lat/lon)
  → sérialisation par échéance
  → API HTTP — json / xml / csv / iframeSLIDE
```

Seul le dernier run disponible est servi ; il n'existe pas d'archive de prévisions exposée via cette
API.

## Schéma de sortie

Chaque réponse contient une enveloppe (état de requête + métadonnées de run) et une série de pas de
temps. Les paramètres ci-dessous correspondent aux noms des champs JSON.

| Paramètre | Type | Description |
|---|---|---|
| `request_state` | TEXT | Code d'état de la requête (succès / erreur) |
| `echeance` | TEXT | Horodatage de validité du pas de temps |
| `t2m` | REAL | Température à 2 m (°C) |
| `tsol` | REAL | Température du sol (°C) |
| `hr` | REAL | Humidité relative à 2 m (%) |
| `pres` | REAL | Pression réduite au niveau de la mer (hPa) |
| `vent` | REAL | Vent moyen à 10 m (km/h) — direction `vdir`, composantes `u10m`/`v10m` |
| `rafales` | REAL | Rafales de vent (km/h) |
| `pluie_1h` | REAL | Précipitations sur 1 h (mm) — cumul dérivé |
| `neige` | REAL | Précipitations neigeuses (cumul converti) |
| `nebul` | REAL | Nébulosité totale (%) — couches `low_cloud`, `mid_cloud`, `hig_cloud` |
| `iso0` | REAL | Altitude de l'isotherme 0 °C (m) |
| `cape` | REAL | Énergie potentielle de convection disponible (J/kg) — indices associés : `cin`, `li`, `kindex` |

La disponibilité des paramètres varie selon la méthode (`gfs` ≠ `wrf`). La liste exhaustive par
méthode sera publiée dans ce catalogue lorsqu'elle sera stabilisée ; le code de sérialisation fait
foi en attendant.

## Licence

Opendata Infoclimat — réutilisation autorisée y compris à des fins commerciales (précisions du
conseil, 2026-06-12). Attribution Infoclimat attendue. Voir
[https://www.infoclimat.fr/opendata/](https://www.infoclimat.fr/opendata/).

Les modèles sources amont conservent leurs propres licences (cf. contrat `modeles-nwp-fichiers`).

## Points d'attention

- **Prévision, pas observation** : les données sont issues d'un modèle numérique. L'exactitude est
  décroissante avec l'échéance et dépend de la qualité du dernier run ingéré.
- La profondeur temporelle (nombre d'échéances servies) est bornée par le run disponible — aucune
  garantie de couverture fixe n'est offerte par ce contrat.
- Toute évolution des noms de paramètres ou des unités est une rupture de contrat pour les
  consommateurs externes → bump MAJOR de version du contrat.
- Les formats `xml` et `iframeSLIDE` sont historiques ; `json` est le format recommandé pour les
  nouveaux développements.
