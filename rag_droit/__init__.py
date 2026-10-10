"""RAG Droit — pipeline de traitement XML (LEGI/CASS/INCA) vers RAG + Obsidian.

Points d'entrée publics :
    - config           : chemins globaux (racine RAG_BASE_DIR)
    - ParserFactory    : fabrique de parseurs (Pattern Factory)
    - DeterministicTagger : moteur de tagging déterministe
    - SemanticRouter   : routeur sémantique des chemins Obsidian
    - run_pipeline     : traitement par flux (streaming)
"""
from . import config
from .factory import ParserFactory
from .pipeline import run_pipeline
from .router import SemanticRouter
from .tagging import DeterministicTagger

__all__ = [
    "config",
    "ParserFactory",
    "DeterministicTagger",
    "SemanticRouter",
    "run_pipeline",
]
