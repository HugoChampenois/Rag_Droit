# RAG Droit — base de connaissances juridiques

Pipeline complet qui transforme les archives open data de la **DILA** (Direction
de l'information légale et administrative : LEGI, CASS, CAPP, CONSTIT, JADE) en
une **base vectorielle interrogeable** (RAG, moteur [Qdrant](https://qdrant.tech/)),
doublée d'un **Vault Obsidian** navigable.

> **Principe fondateur** : ce n'est pas un flux de nouveautés, mais une **base
> complète ancrée dans la réalité des évolutions du droit**. Toutes les versions
> des textes sont conservées (y compris abrogées) : l'ancien article 1382 du
> Code civil (devenu 1240 en 2016) reste retrouvable, avec son numéro et sa
> rédaction d'époque, pour résoudre les situations qui s'y rattachent.

## Sommaire

- [Flux de données](#flux-de-données)
- [Arborescence](#arborescence)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Configuration](#configuration)
- [API de recherche](#api-de-recherche)
- [Mise à jour quotidienne](#mise-à-jour-quotidienne)
- [Avertissement sur le volume des données](#avertissement-sur-le-volume-des-données)
- [Licences et mentions légales](#licences-et-mentions-légales)

## Flux de données

```
archives_brutes/*.tar.gz   (sources brutes, jamais lues directement)
        │  décompression
        ▼
sources_xml/*.xml          (LEGI, CASS, CAPP, CONSTIT, JADE + deltas/)
        │  main.py  (parsing + tagging)
        ▼
donnees_traitees/corpus_global.jsonl   (1 objet JSON par ligne — log d'événements)
        │  consolidate_vault.py --full
        ▼
Vault_Obsidian/{Codes,Lois,JP}/…       (fichiers Markdown consolidés)
        │  ingest.py  (embedding bge-m3 → Qdrant)
        ▼
Qdrant (collection `rag_droit`)   ←  search.py (API /search, /ingest)
```

## Arborescence

| Dossier | Rôle |
|---|---|
| `archives_brutes/` | `.tar.gz` uniquement (archives globales + deltas téléchargés) |
| `sources_xml/` | XML décompressés (baseline + `deltas/`) — source du pipeline |
| `donnees_traitees/` | `corpus_global.jsonl` (sortie RAG) |
| `Vault_Obsidian/` | fichiers `.md` (sortie navigable) |
| `rag_droit/` | code Python (parsing, tagging, routage, ingestion, recherche) |
| `maj/` | téléchargeur des mises à jour quotidiennes DILA |

## Prérequis

- **Python 3.10+** (le parsing XML n'utilise que la bibliothèque standard).
- **Qdrant** : soit via Docker (`docker compose up -d`), soit une instance
  distante (voir `QDRANT_URL`).
- **Un moteur d'embedding** exposant le modèle `bge-m3` :
  - [Ollama](https://ollama.com/) (endpoint natif `/api/embed`), ou
  - [vLLM](https://docs.vllm.ai/) (endpoint OpenAI-compatible `/v1/embeddings`).

## Installation

```bash
# 1. Récupérer le code
git clone https://github.com/HugoChampenois/Rag_Droit.git
cd Rag_Droit

# 2. Créer un environnement virtuel et installer les dépendances
python -m venv venv
venv/bin/pip install -r requirements.txt

# 3. Configurer l'environnement
cp .env.example .env
#    puis renseignez les valeurs dans .env (URL des serveurs d'embedding, etc.)

# 4. Démarrer Qdrant (si instance locale)
docker compose up -d
```

## Utilisation

```bash
# 1. Générer le corpus (idempotent)
venv/bin/python main.py                      # toutes les sources
venv/bin/python main.py --source jade        # une seule source

# 2. Intégrer les mises à jour (deltas) — upsert par id, jamais de suppression
venv/bin/python -m rag_droit.integrate_delta --all

# 3. (Re)construire le Vault Obsidian consolidé (purge + régénération)
venv/bin/python -m rag_droit.consolidate_vault --full

# 4. Embedder le corpus dans Qdrant
venv/bin/python -m rag_droit.ingest

# 5. Servir l'API de recherche
venv/bin/uvicorn rag_droit.search:app --host 0.0.0.0 --port 8010
```

## Configuration

Toute la configuration passe par des **variables d'environnement** (voir
`.env.example`). La racine du projet est lue depuis `RAG_BASE_DIR`
(défaut `/opt/rag`, chemin d'installation historique) — surchargez-la si vous
installez le projet ailleurs.

| Variable | Défaut | Rôle |
|---|---|---|
| `RAG_BASE_DIR` | `/opt/rag` | racine du projet |
| `OLLAMA_BULK_URL` | `http://localhost:8000` | serveur d'embedding bulk (vLLM) |
| `OLLAMA_UPDATE_URL` | `http://localhost:11434` | serveur d'embedding MAJ/recherche (Ollama) |
| `RAG_BULK_BACKEND` | `openai` | backend bulk (`openai` = vLLM, `ollama`) |
| `RAG_UPDATE_BACKEND` | `ollama` | backend MAJ/recherche |
| `RAG_EMBED_API_KEY` | *(vide)* | clé `Bearer` pour le backend OpenAI/vLLM |
| `RAG_EMBED_MODEL` | `bge-m3` | modèle d'embedding servi |
| `RAG_EMBED_DIM` | `1024` | dimension des vecteurs |
| `RAG_COLLECTION` | `rag_droit` | collection Qdrant |
| `QDRANT_URL` | `http://localhost:6333` | serveur Qdrant |

## API de recherche

Une fois Qdrant peuplé et le serveur lancé (`uvicorn`), les endpoints suivants
sont disponibles :

- `GET  /health` → état et collection ;
- `POST /search` → `{"query": "...", "limit": N, "search_type": "dense|sparse|hybrid"}` ;
- `POST /ingest` → mise à jour incrémentale de documents.

## Mise à jour quotidienne

Le dossier `maj/` contient un programme autonome qui télécharge chaque jour les
deltas DILA publiés en open data. Voir `maj/README.md` pour son fonctionnement
et sa mise en place (cron). Il est volontairement **isolé** du pipeline : il
collecte les fichiers sans toucher au reste du système.

## Avertissement sur le volume des données

Les sources DILA représentent plusieurs **millions de fichiers XML** et le corpus
généré pèse plusieurs **gigaoctets** (le Vault Obsidian et la base Qdrant
comptent plusieurs millions de documents). L'ingestion complète (embedding du
corpus sur GPU) peut prendre de l'ordre de la journée. Les données générées ne
sont **pas** versionnées dans ce dépôt (voir `.gitignore`) ; seuls le code et la
documentation le sont.

## Licences et mentions légales

- **Ce dépôt (code source)** est distribué sous licence **MIT** — voir `LICENSE`.
- **Qdrant** (base de données vectorielle) est © Qdrant Solutions GmbH et est
  distribué sous **Apache License 2.0** — voir `THIRD_PARTY_LICENSES` et
  <https://www.apache.org/licenses/LICENSE-2.0>.
- **Les données juridiques** (LEGI, CASS, CAPP, CONSTIT, JADE) sont des données
  publiques produites par la **DILA** et mises à disposition sous **Licence
  Ouverte** (Etalab). Elles ne sont pas incluses dans ce dépôt ; elles sont à
  télécharger depuis les sources officielles (`echanges.dila.gouv.fr/OPENDATA/`).

Pour le détail du code, consultez `rag_droit/README.md`.
