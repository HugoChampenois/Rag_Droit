"""Parseurs de documents juridiques XML."""
from .base import DocumentParser
from .jurisprudence import JurisprudenceParser
from .legi import LegiParser

__all__ = ["DocumentParser", "LegiParser", "JurisprudenceParser"]
