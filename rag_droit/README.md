# `rag_droit/` — module Python du pipeline RAG Droit

Code du pipeline. Aucune dépendance externe n'est requise pour le **parsing**
(bibliothèque standard uniquement) ; les dépendances d'**ingestion/recherche**
sont listées dans `requirements.txt` (`qdrant-client`, `httpx`, `fastapi`,
`uvicorn`).

## Modules

| Fichier | Rôle |
|---|---|
| `config.py` | Chemins globaux (racine `RAG_BASE_DIR`, `sources_xml`, `corpus_global.jsonl`, …) et correspondances source → `DILA_*` |
| `factory.py` | Détection de la source (chemin + racine XML) → bon parseur (Factory) |
| `pipeline.py` | Parcours streaming des XML, idempotent, écrit le JSONL |
| `outputs.py` | Formatage Markdown (frontmatter + wikilinks) et objet JSONL |
| `consolidate_vault.py` | Reconstruit le Vault Obsidian consolidé depuis le JSONL (codes, lois par année, JP par procédure) |
| `link_jurisprudence.py` | Lien best-effort CASS↔CAPP (arrêt attaqué) → index `liens_jurisprudence.json` |
| `router.py` | Routage sémantique → tags racine/matière (`resolve_legi`, `_resolve_jurisprudence`) |
| `tagging.py` | Moteur de tags déterministe (en-têtes + regex, aucune inférence) |
| `parsers/base.py` | Classe abstraite `DocumentParser` + `SkipDocument` |
| `parsers/legi.py` | Articles (`ARTICLE`), textes (`TEXTE_VERSION`), sections (`SECTION_TA`) ; ignore les sommaires `<TEXTELR>` |
| `parsers/jurisprudence.py` | CASS / CAPP / CONSTIT / JADE (`TEXTE_JURI_JUDI`, `…_CONSTIT`, `…_ADMIN`) |
| `embedder.py` | Client embedding Ollama (`/api/embed`) ou vLLM (`/v1/embeddings`, `bge-m3`) |
| `lexical.py` | Encodeur lexical (vecteur creux BM25) calculé côté client |
| `ingest.py` | Bulk embedding → Qdrant (idempotent, checkpoint) |
| `integrate_delta.py` | Intégration des deltas DILA (upsert par id, jamais de suppression) |
| `dedup.py` | Déduplication du JSONL (une seule ligne par `id`, la plus récente) |
| `legi_filter.py` / `legi_keepset.py` | Filtrage du corpus LEGI aux articles de codes + domaine budget/finances |
| `migrate_sparse.py` | Migration one-shot du vecteur creux `sparse` des points existants |
| `search.py` | API FastAPI `/search` et `/ingest` |

## Modèle de données (une ligne JSONL)

```json
{
  "id": "LEGIARTI000023098419",
  "source": "DILA",
  "statut": "abroge",
  "date": "2010-11-14",
  "date_fin": "2016-10-01",
  "num": "1382",
  "titre": "Article 1382 du Code civil",
  "tags": ["droit_civil", "article_1382", "…"],
  "markdown": "---\n…\n"
}
```

## Détails importants

- **`SkipDocument`** (dans `parsers/base.py`) : levé par un parseur pour ignorer
  proprement un fichier (ex. sommaire `<TEXTELR>`). Le pipeline le distingue
  d'une erreur réelle.
- **Numéro d'article** : exposé dans `titre` (`Article 1382 du Code civil`),
  dans `num`, et en tag `article_1382` — c'est ce qui permet de retrouver une
  ancienne numérotation par recherche vectorielle.
- **`iter_xml_files`** élague `eli/` (index sans texte) et `deltas/` (traités
  par `integrate_delta.py`).
- **Vault consolidé** (`consolidate_vault.py --full`) : reconstruit `Vault_Obsidian/`
  depuis le JSONL (source de vérité) sous `Codes/`, `Lois/{YYYY}.md`
  (+ `Finances/`, `Securite_Sociale/`) et `JP/{Inedites,Publiees}/`. Mode
  « rebuild complet » : purge des `.md` puis régénération, déduplication par `id`
  (dernière occurrence). Les procédures publiées s'appuient sur l'index produit
  par `link_jurisprudence.py --full`.

## Variantes d'environnement

| Variable | Défaut | Usage |
|---|---|---|
| `OLLAMA_BULK_URL` | `http://localhost:8000` | embedding bulk (vLLM, GPU) |
| `OLLAMA_UPDATE_URL` | `http://localhost:11434` | embedding MAJ (Ollama, CPU) |
| `RAG_BULK_BACKEND` | `openai` | backend bulk (`openai` = vLLM) |
| `RAG_UPDATE_BACKEND` | `ollama` | backend MAJ/recherche |
| `RAG_EMBED_API_KEY` | *(vide)* | clé `Bearer` pour vLLM |
| `RAG_EMBED_MODEL` | `bge-m3` | nom du modèle servi |
| `RAG_COLLECTION` | `rag_droit` | collection Qdrant |
| `QDRANT_URL` | `http://localhost:6333` | serveur Qdrant |
