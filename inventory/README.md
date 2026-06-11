# Inventaire — registres vivants

Registres maîtres de l'inventaire data, **mis à jour en continu** (contrairement aux
`audits/`, qui sont des constats figés et datés).

| Fichier | Contenu | Maintenu par |
|---|---|---|
| `tables.yaml` | Tables référencées par le code (MariaDB, TimescaleDB, Sphinx) avec writers/readers/status | analyse code + introspection prod |
| `pipelines.yaml` | Pipelines (crons, flows Kestra, daemons, webhooks) avec inputs/outputs/status | analyse code + crontabs réels |
| `file-datasets.yaml` | Datasets fichiers (datastore, NFS, srx-modeles-2) | analyse code |
| `external-sources.yaml` | Sources externes (`api://`) | analyse code |
| `storage-systems.yaml` | Systèmes de stockage (bases, NFS, minio, memcached…) | infrapilot + analyse code |

Créés lors de l'état des lieux 2026-06 (voir `audits/inventaire-2026-06/`), puis
amendés au fil des introspections (ex. réconciliation du 2026-06-07 : statuts `douteux` tranchés
par la vérité prod). L'historique git fait office de journal des révisions.

Conventions de statut : `actif` / `douteux` / `mort` — un changement de statut doit
citer sa preuve (commentaire ou note `T<n> <date>`).
