# code_index — index sémantique du code Infoclimat

Indexe le **code source** des repos cœur de l'écosystème (voir `manifest.yaml`) dans une
base vectorielle locale **LanceDB**, via les embeddings **Mistral `codestral-embed`**, et
permet de la requêter en langage naturel. Objectif : répondre aux questions « où / comment
est fait X dans le code » sans re-scanner tous les repos à chaque fois.

> Complète les outils lexicaux du MCP `ic-data-bot` (`grep`/`lineage`, sur l'inventaire
> data-platform). Ici on indexe le code lui-même, en recherche **sémantique**.

## Contextual Retrieval (recette Anthropic, adaptée Mistral)

Un chunk isolé perd son contexte (de quel fichier/fonction vient-il ?), ce qui dégrade le
rappel. La recette **Contextual Retrieval** corrige ça :

1. **Contexte préfixé avant embedding** — pour chaque chunk on ajoute une phrase qui le
   situe dans son fichier, *avant* de l'embedder. Deux stratégies (`CODE_INDEX_CONTEXT`) :
   - `llm` (défaut) : **un appel chat Mistral par fichier** (`mistral-small-latest`) renvoie
     en JSON le contexte de tous ses chunks. Anthropic met le doc en cache et fait un appel
     par chunk ; Mistral n'a pas de cache manuel → on groupe par fichier (~6k appels au lieu
     de ~39k). Tout trou/échec retombe sur le contexte structurel.
   - `struct` : contexte déterministe (repo, chemin, symbole englobant, position), gratuit.
   - `off` : comportement historique (chunk brut).
2. **Recherche hybride** (`CODE_INDEX_HYBRID=on`, défaut) — vecteur **+** BM25 full-text
   (index FTS LanceDB sur la colonne contextualisée), fusionnés par **RRF**
   (`RRFReranker` natif LanceDB). *Mistral n'expose pas d'endpoint de rerank* → RRF par
   défaut ; rerank LLM optionnel (`CODE_INDEX_RERANK=llm`, une passe chat).
3. **Réécriture de la requête** (`CODE_INDEX_QUERY_REWRITE=on`, défaut) — un appel chat
   reformule/élargit la question (acronymes, synonymes, noms de symboles) avant la recherche.

Le `text` stocké et renvoyé reste le **chunk brut** (affichage + n° de ligne exacts) ; le
contexte est embeddé/indexé via la colonne `contextualized`. Changer de stratégie bumpe
`EMBED_VERSION` (`config.py`) → les fichiers concernés sont ré-indexés même à sha inchangé.

### Autorité & récence (anti-legacy)

La pertinence sémantique seule laisse du vieux code (pertinent en 2024 mais plus en 2026)
saturer le top-k. Trois **métadonnées par fichier** (non embeddées) corrigent ça :

- `source` : `github` (moderne) | `gitlab` (souvent legacy) | `other` — d'après le remote git.
- `last_commit` : date du dernier commit du fichier (récence).
- `status` : `actif` | `douteux` | `mort` — depuis `inventory/pipelines.yaml` (mappé par
  `repo/script` → **autorité** côté gouvernance).
- `source_url` : **permalien web par commit SHA** vers `repo/path#Llignes` (GitHub
  `…/blob/<sha>/…#L<a>-L<b>`, GitLab self-hosted `…/-/blob/<sha>/…#L<a>-<b>`) — le SHA = le
  commit effectivement indexé, donc les n° de ligne correspondent au contenu cité. Renvoyé
  par `search_code` (`Result.source_url`) pour citer une source exacte et cliquable.

Elles sont calculées **en local** (le build sur la VM ne reçoit pas les `.git`) dans un
sidecar JSON, livré avec l'index :

```bash
python -m code_index.meta --out meta.json           # génère le sidecar (git + inventaire)
CODE_INDEX_META=meta.json python -m code_index.index # l'indexation attache les colonnes
# refresh métadonnée-seule (sans ré-embedding) : store.rebuild_with_fts(db, meta=sidecar)
```

À la recherche (`CODE_INDEX_META_RERANK=on`), un **rerank borné** s'applique après l'hybride :
le `mort` coule, le `douteux`/ancien (>3 ans) descend, l'`actif`/récent (<1 an) remonte de
quelques places — **la pertinence reste dominante** (nudge de position, pas un tri par date).
Le statut/âge est exposé dans la sortie (`Result.flag`) pour que le bot signale le legacy.

## Installation

```bash
cd data-platform/tools
pip install -e '.[code-index]'        # mistralai + lancedb
export MISTRAL_API_KEY=…              # jamais committé
```

## Construire / mettre à jour l'index

```bash
# Estimer volume et coût sans appeler l'API :
python -m code_index.index --dry-run

# Indexer un seul repo (rapide, pour valider) :
python -m code_index.index --repo data-platform

# Indexer tout le périmètre du manifeste :
python -m code_index.index
```

L'indexation est **incrémentale** : seuls les fichiers dont le contenu (sha256) a changé
sont ré-embeddés ; les fichiers disparus du disque sont retirés (dans le périmètre des
repos parcourus). Relancer la commande après quelques modifications ne recoûte presque
rien.

Ordre de grandeur (périmètre cœur complet) : ~6 000 fichiers, ~39 000 chunks,
~33 M tokens, **~5 $** au tarif `codestral-embed-2505` (0,15 $/M tokens) pour un premier
index plein.

## Requêter

```bash
python -m code_index.search "comment fonctionne le routing filesystem du monolithe ?"
python -m code_index.search "décodage HMAC des stations" --repo serveur-station-autonome --k 5
python -m code_index.search "génération des cartes isobares" --lang mapfile --full
```

En Python (réutilisé par le wrapper MCP) :

```python
from code_index import search_code
for r in search_code("anti-scraping auth", k=6, repos=["python-climate-services"]):
    print(r.location, r.score)
```

## Corpus « docs » (gouvernance) — `search_docs`

En plus du code, le même pipeline indexe la **gouvernance data-platform** (contrats ODCS,
inventory, catalog, glossaire, audits) dans une **table séparée `docs_chunks`** de la même
base, avec un **modèle d'embedding texte** (`mistral-embed`, pas codestral) et un **découpage
par entrée** (`chunk_structured` : 1 entrée de registre YAML / 1 contrat / 1 section markdown
= 1 chunk). C'est un **complément de rappel** des outils lexicaux `grep`/`lineage` (et non un
remplacement du system prompt du bot).

```bash
# périmètre = section `docs:` du manifest (globs sous data-platform/)
python -m code_index.index --corpus docs --dry-run       # estimer
python -m code_index.index --corpus docs                 # construire docs_chunks
python -m code_index.search --corpus docs "limitation du contrat foudre"
```

En Python : `from code_index import search_docs ; search_docs("anti-scraping", k=6)`.

## Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `MISTRAL_API_KEY` | — | **Requis** pour indexer/requêter |
| `CODE_INDEX_BASE_DIR` | parent de `data-platform` | Où chercher les repos siblings |
| `CODE_INDEX_DIR` | `code_index/.lancedb/` | Répertoire LanceDB (gitignoré) |
| `CODE_INDEX_MODEL` | `codestral-embed-2505` | Modèle d'embedding |
| `CODE_INDEX_DIM` | natif du modèle | Dimension de sortie (Matryoshka) |
| `CODE_INDEX_CHUNK_CHARS` / `_OVERLAP_CHARS` | 3000 / 1000 | Fenêtrage |
| `CODE_INDEX_BATCH_SIZE` | 64 | Inputs par appel embeddings |
| `CODE_INDEX_MIN_INTERVAL_S` | 0.5 | Throttle entre appels API |
| `CODE_INDEX_CONTEXT` | `llm` | Contexte préfixé : `llm` \| `struct` \| `off` |
| `CODE_INDEX_CONTEXT_MODEL` | `mistral-small-latest` | Modèle chat (contexte + réécriture + rerank LLM) |
| `CODE_INDEX_HYBRID` | `on` | Recherche hybride vecteur + BM25 (sinon vecteur seul) |
| `CODE_INDEX_RERANK` | `rrf` | Fusion/rerank : `rrf` \| `llm` \| `none` |
| `CODE_INDEX_QUERY_REWRITE` | `on` | Réécriture de la requête avant recherche |
| `CODE_INDEX_META_RERANK` | `on` | Rerank par autorité (statut gouvernance) + récence après l'hybride |
| `CODE_INDEX_META` | — | Chemin du sidecar JSON de métadonnées (source/date/statut) à l'indexation |
| `DOCS_INDEX_MODEL` | `mistral-embed` | Modèle d'embedding du corpus docs (`--corpus docs`) |

## Architecture

```
manifest.yaml ─┐
               ▼
walk.py ─► chunk.py ─► context.py ─► embed.py (Mistral) ─► store.py (LanceDB) ─► search.py / CLI
(découv.)  (fenêtres) (contexte LLM) (vecteurs, throttle)  (vector + FTS BM25)   (rewrite.py +
                       par fichier)                                               hybride + RRF)
```

L'index (sha par fichier) vit dans la table `code_chunks` elle-même : pas de fichier
d'état séparé. Le répertoire `.lancedb/` est un **artefact local regénérable**, gitignoré.

## Limites / pistes (hors périmètre de cette itération)

- Découpe par fenêtres de caractères (pas d'AST par fonction/classe).
- Un seul espace vectoriel `codestral-embed` (pas d'index docs séparé `mistral-embed`).
- Rerank limité à RRF (fusion) + rerank LLM optionnel : pas de reranker neuronal tiers
  (Cohere/Voyage), Mistral n'exposant pas d'endpoint rerank.
- Store local mono-poste (pas de pgvector/serveur partagé).
- **FTS sur peu de cœurs** : à grande échelle (~50k+ lignes), le builder FTS natif de LanceDB
  **deadlock** (futex, 0 % CPU) quand les réservations de threads IO ≥ nb de CPU
  (cf. lancedb/lancedb#2326). `config.py` pose donc `LANCE_IO_THREADS`/`LANCE_CPU_THREADS`
  par défaut sur les machines ≤4 cœurs (surchargeable) ; les régler explicitement
  (`LANCE_IO_THREADS=2 LANCE_CPU_THREADS=4`) côté build **et** service. Bumper le nb de cœurs
  seul ne suffit pas. `store.rebuild_with_fts` réécrit aussi la table en mono-fragment avant
  l'index (le builder bloque également en multi-fragment).
- Pas de régénération automatique (cron/Kestra/CI) ni de livraison de l'index sur la VM.
- **Outil MCP `search_code`** (côté `ic-data-bot`) : wrapper fin réutilisant `search_code()`
  ci-dessus ; nécessite que l'index LanceDB soit présent là où tourne le bot.
