"""Encodeur lexical (vecteur creux BM25) calculé côté client.

Ollama (`/api/embed`) ne renvoie que le dense bge-m3 ; les fréquences de termes
sont donc produites localement, sans dépendance lourde. Qdrant applique ensuite
`Modifier.IDF` à la requête au moment de la recherche.
"""
from __future__ import annotations

import re
import zlib
from collections import Counter
from typing import Dict, List

from qdrant_client.models import SparseVector

from .tagging import fold_accents

SPARSE_VECTOR_NAME = "sparse"

STOPWORDS = frozenset({
    # déterminants / articles
    "le", "la", "les", "un", "une", "des", "du", "de", "au", "aux", "l", "d",
    # pronoms
    "il", "ils", "elle", "elles", "on", "je", "j", "tu", "nous", "vous",
    "se", "me", "te", "lui", "leur", "leurs", "ce", "ceci", "cela", "celle",
    "celles", "celui", "ceux", "cet", "cette", "ces", "qui", "que", "quoi",
    "dont", "où", "lequel", "laquelle", "lesquels", "lesquelles", "y", "en", "soi",
    # verbes auxiliaires / formes de "être" et "avoir" (fréquentes)
    "est", "etait", "etaient", "ete", "etre", "etes", "etant", "sera", "seront",
    "serait", "seraient", "sont", "sommes", "soit", "soient", "suis", "es",
    "a", "ont", "avait", "avaient", "avoir", "avons", "avez", "aura", "auront",
    "aurait", "auraient", "eu", "eus", "eut", "ayant", "fut", "furent",
    # prépositions / conjonctions
    "apres", "avant", "avec", "chez", "dans", "depuis", "derriere", "devant",
    "durant", "entre", "envers", "hors", "jusque", "jusqu", "malgre", "par",
    "parmi", "pendant", "pour", "sans", "sauf", "selon", "sous", "sur", "vers",
    "via", "contre", "comme", "lorsque", "quand", "si", "sinon", "tandis",
    "afin", "car", "donc", "et", "mais", "ni", "or", "ou", "puis", "quoique",
    "parce", "puisque", "lors", "nonobstant",
    # adverbes / autres mots-outils
    "ne", "pas", "plus", "moins", "peu", "tres", "trop", "aussi", "ainsi",
    "alors", "bien", "deja", "encore", "enfin", "ici", "la", "meme",
    "notamment", "cependant", "toutefois", "neanmoins", "toujours", "jamais",
    "souvent", "parfois", "tout", "toute", "toutes", "tous", "autre", "autres",
    "aucun", "aucune", "certain", "certaine", "certains", "certaines", "chaque",
    "plusieurs", "quelque", "quelques", "tel", "telle", "tels", "telles",
    # possessifs / démonstratifs
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses", "notre", "nos",
    "votre", "vos",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _token_index(token: str) -> int:
    """Index u32 stable, cohérent entre les process ingest (bulk) et search (API)."""
    return zlib.crc32(token.encode("utf-8")) & 0xFFFFFFFF


def tokenize(text: str) -> List[str]:
    folded = fold_accents(text or "")
    return [t for t in _TOKEN_RE.findall(folded)
            if t not in STOPWORDS and len(t) > 1]


def text_to_sparse(text: str, as_query: bool = False) -> SparseVector:
    """Doc -> TF ; requête -> présence (l'IDF est appliqué par Qdrant)."""
    counts: Dict[int, int] = Counter(_token_index(t) for t in tokenize(text))
    indices, values = [], []
    for idx in sorted(counts):
        indices.append(idx)
        values.append(1.0 if as_query else float(counts[idx]))
    return SparseVector(indices=indices, values=values)
