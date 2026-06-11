# Schemas — DDL versionné

## Convention

**Un seul fichier « courant » par système, compressé** ; l'historique des snapshots
vit dans git (un commit par regénération, daté par le message de commit et l'en-tête
du dump).

| Fichier | Contenu | Regénération |
|---|---|---|
| `mariadb/schema.sql.gz` | DDL structure seule de mariadb-master (toutes bases, hors système) | runbook `tools/introspect_runbook.md` §2 |
| `timescaledb/` | DDL cible TimescaleDB | présent (reconstruit depuis le catalogue, 2026-06-09) |

Pourquoi compressé : le dump MariaDB fait ~23 Mo brut (20 292 tables) et ~470 Ko
gzippé ; trois snapshots par an non compressés gonfleraient l'historique de ~70 Mo/an.

## Consultation

```bash
zcat schemas/mariadb/schema.sql.gz | less
zcat schemas/mariadb/schema.sql.gz | grep -A30 'CREATE TABLE `foudre`'
```

## Diff entre deux snapshots

```bash
git log --oneline -- schemas/mariadb/schema.sql.gz   # lister les snapshots
diff <(git show <rev>:schemas/mariadb/schema.sql.gz | zcat) \
     <(zcat schemas/mariadb/schema.sql.gz)
```

(Optionnel : `echo 'schema.sql.gz diff=gzip' >> .gitattributes` + `git config
diff.gzip.textconv 'zcat'` pour des `git diff` lisibles en local.)

## Règle de regénération

Toujours **structure seule** (`--no-data` / export « structure seule »), comptes
lecture seule, et gzip avec `-n` (pas de timestamp dans l'en-tête gzip, sinon le
fichier change même quand le DDL n'a pas bougé).
