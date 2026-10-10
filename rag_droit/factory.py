"""Factory de parseurs (Design Pattern "Factory")."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import config
from .parsers.base import DocumentParser
from .parsers.jurisprudence import JurisprudenceParser
from .parsers.legi import LegiParser


def detect_archive(xml_path: str) -> str:
    """Détermine la source (legi/cass/capp/constit/inca) depuis le chemin,
    sinon via le tag racine du fichier."""
    parts = [p.lower() for p in Path(xml_path).parts]
    for archive in config.SOURCE_ARCHIVES:
        if archive in parts:
            return archive

    with open(xml_path, "r", encoding="utf-8", errors="ignore") as handle:
        head = handle.read(4096)
    if re.search(r"<(?:TEXTE_VERSION|ARTICLE|SECTION_TA|TEXTELR)\b", head):
        return "legi"
    if re.search(r"<TEXTE_JURI_CONSTIT\b", head):
        return "constit"
    if re.search(r"<TEXTE_JURI_ADMIN\b", head):
        return "jade"
    if re.search(r"<(?:TEXTE_JURI_JUDI|JURITEXT|JURIDOC|JURICA|DOCUMENT)\b", head):
        return "cass"
    return "legi"


class ParserFactory:
    """Retourne le parseur spécialisé adéquat pour un fichier XML donné."""

    @staticmethod
    def create(
        xml_path: str,
        raw_content: Optional[bytes] = None,
        source_archive: Optional[str] = None,
    ) -> DocumentParser:
        archive = source_archive or detect_archive(xml_path)
        if archive == "legi":
            return LegiParser(xml_path, raw_content)
        return JurisprudenceParser(xml_path, raw_content)
