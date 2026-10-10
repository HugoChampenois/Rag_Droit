"""Configuration globale du pipeline RAG Droit.

Tous les chemins sont regroupés ici afin de garantir la modularité du module.
La racine de travail est lue depuis la variable d'environnement `RAG_BASE_DIR`
(par défaut `/opt/rag`, chemin d'installation historique du projet). Aucune
autre dépendance à l'environnement local n'est introduite dans le reste du code.
"""

import os

# Racine de travail (surchargeable via RAG_BASE_DIR).
BASE_DIR = os.environ.get("RAG_BASE_DIR", "/opt/rag")

# Entrées : archives .tar.gz (stockage seul, jamais lues par le pipeline)
ARCHIVES_BRUTES_DIR = f"{BASE_DIR}/archives_brutes"

# XML décompressés (baseline + deltas) : la source du pipeline
SOURCES_XML_DIR = f"{BASE_DIR}/sources_xml"

# Sortie 1 : base vectorielle / RAG
DONNEES_TRAITEES_DIR = f"{BASE_DIR}/donnees_traitees"
CORPUS_GLOBAL_JSONL = f"{DONNEES_TRAITEES_DIR}/corpus_global.jsonl"

# Sortie 2 : Vault Obsidian
VAULT_OBSIDIAN_DIR = f"{BASE_DIR}/Vault_Obsidian"

# Noms des dossiers sources détectables sous ARCHIVES_BRUTES_DIR.
# `capp` = Cour d'appel, `constit` = Conseil constitutionnel,
# `jade` = jurisprudence administrative (Conseil d'État, CAA, TA).
SOURCE_ARCHIVES = ("legi", "cass", "capp", "constit", "jade", "inca")

# Correspondance dossier source -> valeur du champ "source" (traçabilité)
SOURCE_DONNEES = {
    "legi": "DILA",
    "cass": "DILA_CASS",
    "capp": "DILA_CAPP",
    "constit": "DILA_CONSTIT",
    "jade": "DILA_JADE",
    "inca": "DILA_INCA",
}
