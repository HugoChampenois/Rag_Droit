# `donnees_traitees/` — corpus RAG (sortie 1)

Contient `corpus_global.jsonl` : **une ligne JSON par document traité**.

C'est un **log d'événements append-only** (chaque traitement ajoute une ligne ;
une version modifiée ajoute une nouvelle ligne). L'état courant est détenu par
**Qdrant** (voir `rag_droit/ingest.py`), qui fait foi pour la recherche.

Champs d'une ligne : `id`, `obsidian_path`, `source`, `statut`, `date`,
`date_fin`, `num`, `titre`, `tags`, `markdown`.

- Ne pas éditer à la main.
- Relancer le pipeline est sans risque : la déduplication par `id` évite les
  doublons.
