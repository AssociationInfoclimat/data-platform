# ADR-0001 — Contextual Retrieval pour l'index de code (contexte LLM par fichier, hybride RRF)

- Statut : acceptée
- Date : 2026-06-16
- Décideurs : data engineer (pam)

> Première ADR du repo `data-platform`. Numérotation propre à ce repo (les ADR du pilote
> lineage vivent dans `site-infoclimat/migration-data/adr/`).

## Contexte

`tools/code_index/` indexe le code des repos cœur dans LanceDB via les embeddings Mistral
`codestral-embed` et le requête en langage naturel. Jusqu'ici chaque chunk était embeddé
**brut** : un extrait isolé perd son fichier/sa fonction d'origine → rappel dégradé.

La recette **Contextual Retrieval** d'Anthropic répond à ça : préfixer à chaque chunk un
court contexte généré par LLM (le document servant de contexte, mis en cache), indexer le
texte contextualisé en vectoriel **et** en BM25, fusionner, reranker. On veut l'appliquer
avec l'API Mistral, plus une réécriture de la requête côté recherche.

Deux contraintes vérifiées orientent la conception :

- **Mistral n'expose pas d'endpoint de rerank** dédié (≠ Cohere/Voyage).
- **Mistral n'a pas de prompt-caching manuel** : un appel LLM par chunk re-paierait le
  fichier ~N fois (Anthropic, lui, le met en cache).
- **LanceDB fait du hybrid search natif** (vecteur + FTS BM25 Tantivy) avec `RRFReranker`
  intégré, sans API externe.

## Décision

1. **Contexte par fichier, pas par chunk** : un appel chat Mistral (`mistral-small-latest`)
   par fichier renvoie en JSON le contexte de tous ses chunks (~6k appels vs ~39k).
   Stratégie réglable (`CODE_INDEX_CONTEXT` = `llm` | `struct` | `off`) ; tout trou/échec
   retombe sur un contexte **structurel déterministe** (repo, chemin, symbole englobant).
2. **Recherche hybride dans LanceDB** : vecteur + BM25 sur la colonne `contextualized`,
   fusionnés par **RRF** (`RRFReranker`). Rerank LLM optionnel (`CODE_INDEX_RERANK=llm`).
3. **Réécriture de la requête** (chat Mistral) avant recherche, partagée CLI + bot.
4. Le `text` stocké/renvoyé reste le **chunk brut** ; le contexte vit dans `context` /
   `contextualized`. Une constante `EMBED_VERSION` invalide l'index à tout changement de
   stratégie (réindexation même à sha inchangé).

## Justification

- **Coût maîtrisé sans cache.** Le groupage par fichier remplace le prompt-caching qu'on
  n'a pas, en divisant les appels par ~6 et les tokens d'entrée d'autant.
- **Aucune nouvelle dépendance lourde.** BM25 + fusion vivent dans le store LanceDB déjà en
  place ; RRF ne coûte aucun appel réseau (pertinent vu l'absence de reranker Mistral).
- **Dégradation sûre.** Contexte LLM → structurel ; réécriture/rerank → identité ; hybride →
  vecteur seul si pas d'index FTS. L'indexation et la recherche ne cassent jamais.
- **Réversible.** `CODE_INDEX_*` ramène au comportement historique ; l'index `.lancedb/` est
  un artefact regénérable.

## Conséquences

- (+) Meilleur rappel attendu : le chunk « connaît » son fichier/fonction ; le lexical
  rattrape les requêtes à mots-clés exacts que le vectoriel manque.
- (+) Signature `search_code()` inchangée → le wrapper MCP d'ic-data-bot en hérite sans
  modification de fond.
- (−) Rebuild plein nécessaire au premier passage (l'embedding change). Coût one-off estimé
  ~2-3 $ (contexte) + ~5-6 $ (ré-embedding) ; `--dry-run` chiffre avant tout appel.
- (−) Rerank plafonné à RRF + LLM optionnel : pas de reranker neuronal tiers. Critère de
  réouverture : si l'A/B montre un plafond de précision, évaluer un reranker dédié.

## Références

- `tools/code_index/README.md` (section Contextual Retrieval, variables d'environnement)
- Anthropic, « Introducing Contextual Retrieval » : <https://www.anthropic.com/news/contextual-retrieval>
- LanceDB hybrid search / RRF : <https://lancedb.com/documentation/guides/search/hybrid-search.html>
