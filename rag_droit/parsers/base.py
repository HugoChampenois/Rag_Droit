"""Classe abstraite de parsing de documents juridiques XML.

Définit le contrat commun (Design Pattern "Factory" amont) : toute classe fille
doit implémenter `parse`, `extract_metadata`, `generate_tags`, `route_file` et
`format_outputs`.
"""
from __future__ import annotations

import hashlib
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Set, Tuple

from .. import config


class SkipDocument(Exception):
    """Document volontairement ignoré (ex. sommaire `<TEXTELR>`, non retenu)."""


class DocumentParser(ABC):
    """Parseur abstrait pour un fichier XML juridique (LEGI, CASS, INCA)."""

    def __init__(self, xml_path: str, raw_content: bytes | None = None) -> None:
        self.xml_path: str = xml_path
        self.raw_content: bytes | None = raw_content
        self.metadata: Dict[str, Any] = {}
        self.tags: Set[str] = set()
        self.signals: Dict[str, str] = {}
        self.texte_integral: str = ""
        self.visas: list[str] = []
        self.target_dir: str = ""
        self.signature_extraction: str = ""

    # ------------------------------------------------------------------ #
    # Helpers partagés (traçabilité)
    # ------------------------------------------------------------------ #
    def read_content(self) -> bytes:
        """Lit le contenu binaire du fichier, en mémoire une seule fois."""
        if self.raw_content is not None:
            return self.raw_content
        with open(self.xml_path, "rb") as handle:
            self.raw_content = handle.read()
        return self.raw_content

    def compute_signature(self) -> str:
        """Génère la signature d'extraction : hash MD5 du fichier + timestamp."""
        raw = self.read_content()
        digest = hashlib.md5(raw).hexdigest()
        timestamp = int(time.time())
        self.signature_extraction = f"{digest}_{timestamp}"
        return self.signature_extraction

    def detect_source(self) -> str:
        """Déduit la source de données à partir du dossier parent (LEGI/CASS/INCA)."""
        parts = [p.lower() for p in Path(self.xml_path).parts]
        for archive in config.SOURCE_ARCHIVES:
            if archive in parts:
                return config.SOURCE_DONNEES[archive]
        return "INCONNUE"

    # ------------------------------------------------------------------ #
    # Méthodes abstraites (contrat commun)
    # ------------------------------------------------------------------ #
    @abstractmethod
    def parse(self) -> "DocumentParser":
        """Parse le XML et peuple `signals`, `texte_integral` et `visas`."""

    @abstractmethod
    def extract_metadata(self) -> Dict[str, Any]:
        """Construit le dictionnaire de métadonnées (traçabilité + datation)."""

    @abstractmethod
    def generate_tags(self) -> Set[str]:
        """Génère le set de tags qualifiés via le moteur déterministe."""

    @abstractmethod
    def route_file(self, vault_dir: str | None = None) -> str:
        """Calcule le chemin cible du fichier .md via le routeur sémantique."""

    @abstractmethod
    def format_outputs(self) -> Tuple[str, Dict[str, Any]]:
        """Produit (texte markdown, dictionnaire JSONL) pour le document."""

    # ------------------------------------------------------------------ #
    # Utilitaires XML communs
    # ------------------------------------------------------------------ #
    @staticmethod
    def _first_text(element: Any, tag: str) -> str:
        """Retourne le texte du premier sous-élément `tag`, sinon chaîne vide."""
        node = element.find(tag)
        if node is None or node.text is None:
            return ""
        return node.text.strip()

    @staticmethod
    def _safe_basename(path: str) -> str:
        """Nom de fichier sans extension."""
        return os.path.splitext(os.path.basename(path))[0]
