"""Index sémantique du code Infoclimat (embeddings Mistral + LanceDB).

Sous-paquet d'outillage : indexe le code source des repos cœur de l'écosystème
(voir `manifest.yaml`) dans une base vectorielle locale, et permet de la requêter en
langage naturel. Les dépendances lourdes (`mistralai`, `lancedb`) sont importées
paresseusement dans `embed`/`store` : importer `code_index`, `walk` ou `chunk` ne
requiert que la stdlib + `pyyaml`, pour que les tests `walk`/`chunk` tournent en CI.

`search_code` est exposé en import paresseux (PEP 562) pour ne pas charger `search`
— ni ses dépendances — à l'import du paquet, et éviter l'avertissement runpy quand on
lance `python -m code_index.search`.
"""
from __future__ import annotations

__all__ = ["search_code"]


def __getattr__(name: str):
    if name == "search_code":
        from .search import search_code
        return search_code
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
