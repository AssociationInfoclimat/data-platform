# Marquez local — sink OpenLineage de validation

Stack Docker locale pour valider la chaîne de lineage :
`lineage_run.py` (wrapper cron) → spool JSONL → `lineage_forward.py` → Marquez.

Le déploiement production (LXC via infrapilot) est une tâche séparée — cette
stack ne sert qu'au développement et à la démo.

## Démarrage

```bash
docker compose up -d
# API : http://localhost:5002/api/v1/namespaces — UI : http://localhost:3000
```

## Chaîne complète en local

```bash
cd ..
python3 lineage_run.py --job cron.radar --spool /tmp/lineage.jsonl -- sh -c 'sleep 1'
python3 lineage_forward.py --spool /tmp/lineage.jsonl --once   # [marquez] url dans .env.ini
```

Puis vérifier dans l'UI (namespace `cron://infoclimat`) ou via l'API :

```bash
curl -s "http://localhost:5002/api/v1/namespaces/cron%3A%2F%2Finfoclimat/jobs" | python3 -m json.tool
```

## Remise à zéro

```bash
docker compose down -v   # -v supprime le volume Postgres (toutes les données Marquez)
```
