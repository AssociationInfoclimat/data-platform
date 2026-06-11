# Dataset — Données foudre

| | |
|---|---|
| **Contrat** | [`contracts/foudre.odcs.yaml`](../../contracts/foudre.odcs.yaml) (draft — DDL attendu) |
| **Domaine** | Foudre |
| **Stockage** | MariaDB `V5` — table `foudre` |
| **Fréquence d'ingestion** | Temps réel (sources multiples, fréquence selon source) |
| **Rétention** | Inconnue — pas de script de purge trouvé côté foudre |
| **Owner** | pam |

## Sources d'ingestion

| Source | Pipeline | Statut |
|---|---|---|
| `api://meteocentre/lightning-foudre` | `cron.recup-foudre` (srx-data-2) | actif |
| `api://meteocentre/lightning-anim` | `cron.recup-foudre-anim` | actif |
| `api://blitzortung/strikes` | `kestra.infoclimat.data.recup-blitzortung` | mort (disabled) |
| `api://ic-meteonet/foudre` | `data/ic_meteonet/ic-meteonet-extract-foudre.php` | douteux |

## Flux actif principal

```
api://meteocentre/lightning-foudre
  → cron/recup_foudre.php  (srx-data-2, toutes les 2 min)
  → INSERT INTO V5.foudre
  → mariadb://V5/foudre

mariadb://V5/foudre
  → cron/notif_foudre.php  (kestra, toutes les 2 min)
  → mariadb://V5/appli_notifications  (push mobile)
```

## Consommateurs connus

- `cron/notif_foudre.php` — notifications push mobiles (éclair à proximité)
- `include/Foudre/` — affichage carte foudre temps réel
- `mobile-api/` — endpoint foudre API mobile

## Points d'attention

- Le flow Blitzortung (`kestra.infoclimat.data.recup-blitzortung`) est **désactivé**
  (status: mort). La source était `api://blitzortung/strikes` ; Blitzortung a
  modifié son accès vers 2023, le script ne fonctionnait plus.
- La source `api://ic-meteonet/ic-meteonet-extract-foudre` est inventoriée comme
  interne mais le script n'est pas mappé dans les clones (douteux).
- La table `V5.foudre` est déclarée avec INSERT qualifié
  (`INSERT INTO V5.foudre`) — base confirmée dans le code (recup_blitzortung.php:9,
  compo_new_1.php:173).

## Documentation source

- `data-platform/inventory/tables.yaml` — entrée `mariadb://V5/foudre`
- `data-platform/inventory/external-sources.yaml` — sources foudre
