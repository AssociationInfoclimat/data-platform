# Audit inventaire 2026-06 — constat figé

État des lieux data réalisé du 2026-06-05 (analyse code, 23 repos) au 2026-06-07
(introspection prod MariaDB + réconciliation). **Ce dossier est une photo : ne plus
y éditer que des corrections d'erreurs factuelles.**

| Fichier                        | Rôle                                                                                                                    |
|--------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| `reconciliation.md`            | Bilan de l'audit : couverture, chiffres de réconciliation, corrections appliquées                               |
| `reconcile-output-20260607.md` | Sortie brute de `tools/reconcile.py` (générée, ne pas éditer)                                                           |
| `introspection/`               | Vérité prod collectée : crontabs réels, scripts hôtes, notes — **conservée en interne, non publiée dans ce repo** |

Les **registres vivants** issus de cet audit (`tables.yaml`, `pipelines.yaml`,
`file-datasets.yaml`, `external-sources.yaml`, `storage-systems.yaml`) ont été promus
dans [`../../inventory/`](../../inventory/) le 2026-06-07 — leur état au moment de la
clôture de l'audit reste consultable dans l'historique git de ce dossier.

Artefacts liés ailleurs :
- volumétrie : `../volumetrie/inventaire-20260607.{csv,md}` (série récurrente)
- DDL MariaDB : `../../schemas/mariadb/schema.sql.gz`
