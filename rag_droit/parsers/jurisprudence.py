"""Parseur spécialisé pour la jurisprudence CASS / CAPP / CONSTIT / INCA."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Set, Tuple

from .. import outputs
from ..router import SemanticRouter
from ..tagging import DeterministicTagger
from .base import DocumentParser


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].upper()


class JurisprudenceParser(DocumentParser):
    """Parse une décision de justice (Cour de cassation / Cour d'appel /
    Conseil constitutionnel)."""

    HEADER_TAGS = (
        "ID", "CHAMBRE", "JURIDICTION", "FORMATION", "TYPE_AFFAIRE",
        "SOLUTION", "PUBLICATION", "DATE_DEC", "DATE_ARRET", "DATE_DECISION",
        "NUMERO", "NUMERO_AFFAIRE", "NUMERO_POURVOI", "NUMERO_APPEL",
        "NOR", "ECLI", "NAC", "TITRE", "SOMMAIRE",
    )

    def parse(self) -> "JurisprudenceParser":
        raw = self.read_content()
        self.compute_signature()
        self.root = ET.fromstring(raw)
        self._index_tags()
        self.signals = self._extract_signals()
        self.texte_integral = self._extract_texte_integral()
        self.liens = self._extract_liens()
        return self

    def _index_tags(self) -> None:
        self._by_tag: Dict[str, ET.Element] = {}
        for el in self.root.iter():
            local = _local(el.tag)
            if local not in self._by_tag:
                self._by_tag[local] = el

    def _first_text(self, *tags: str) -> str:
        for tag in tags:
            el = self._by_tag.get(tag.upper())
            if el is not None and el.text:
                return " ".join(el.text.split())
        return ""

    def _first_attr(self, tag: str, attr: str) -> str:
        el = self._by_tag.get(tag.upper())
        if el is None:
            return ""
        return (el.get(attr) or "").strip()

    def _publication(self) -> str:
        """Statut de publication : PUBLI_BULL@publie (JUDI) ou PUBLI_RECUEIL (JADE).

        JADE (administratif) : A/B = publié au recueil Lebon, C/C+/R = inédit.
        """
        publie = self._first_attr("PUBLI_BULL", "publie").lower()
        if publie == "oui":
            return "publie"
        if publie == "non":
            return "non publie"
        recueil = self._first_text("PUBLI_RECUEIL").upper().strip()
        if recueil in ("A", "B"):
            return "publie"
        if recueil in ("C", "C+", "R"):
            return "non publie"
        return self._first_text("PUBLICATION")

    def _extract_signals(self) -> Dict[str, str]:
        date = self._first_text("DATE_DEC", "DATE_ARRET", "DATE_DECISION")
        formation = self._first_text("FORMATION")
        return {
            "id": self._first_text("ID"),
            "num_affaire": self._first_text("NUMERO_AFFAIRE"),
            "numero": self._first_text("NUMERO"),
            "pourvoi": self._first_text("NUMERO_POURVOI", "NUMERO_AFFAIRE"),
            "appel": self._first_text("NUMERO_APPEL"),
            "nor": self._first_text("NOR"),
            "ecli": self._first_text("ECLI"),
            "chambre": self._first_text("CHAMBRE") or formation,
            "formation": formation,
            "juridiction": self._first_text("JURIDICTION"),
            "solution": self._first_text("SOLUTION"),
            "publication": self._publication(),
            "date": date,
            "titre": self._first_text("TITRE", "SOMMAIRE"),
        }

    def _extract_texte_integral(self) -> str:
        texte_el = self._by_tag.get("TEXTE")
        if texte_el is not None:
            raw = ET.tostring(texte_el, encoding="unicode")
            raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
            raw = re.sub(r"<[^>]+>", "", raw)
            return html.unescape(raw).strip()
        chunks = []
        for el in self.root.iter():
            if el.text and el.tag.rsplit("}", 1)[-1].upper() not in ("META", "META_COMMUN", "LIENS", "VISAS"):
                chunks.append(" ".join(el.text.split()))
        return "\n".join(chunks).strip()

    def _extract_liens(self) -> List[Dict[str, str]]:
        liens: List[Dict[str, str]] = []
        for lien in self.root.iter():
            if _local(lien.tag) == "LIEN":
                liens.append(
                    {
                        "num": lien.get("num", ""),
                        "texte": " ".join((lien.text or "").split()),
                        "naturetexte": lien.get("naturetexte", ""),
                        "typelien": lien.get("typelien", ""),
                        "cidtexte": lien.get("cidtexte", ""),
                        "nortexte": lien.get("nortexte", ""),
                    }
                )
        return liens

    # ------------------------------------------------------------------ #
    # Implémentation du contrat commun
    # ------------------------------------------------------------------ #
    def extract_metadata(self) -> Dict[str, Any]:
        # Pour JADE (administratif), `numero` (n° de requête) n'est pas unique
        # entre juridictions : on privilégie donc `id` (CETATEXT...) qui est global.
        id_document = (
            self.signals.get("num_affaire")
            or self.signals.get("nor")
            or self.signals.get("ecli")
            or self.signals.get("id")
            or self.signals.get("numero")
            or self._safe_basename(self.xml_path)
        )
        statut = DeterministicTagger.statut_from_solution(self.signals.get("solution")) or "inconnu"
        self.metadata = {
            "id_document": id_document,
            "source_donnee": self.detect_source(),
            "signature_extraction": self.signature_extraction,
            "date": self.signals.get("date", ""),
            "statut": statut,
            "titre": self.signals.get("titre", ""),
        }
        return self.metadata

    def generate_tags(self) -> Set[str]:
        self.tags = DeterministicTagger.generate(self.signals, self.texte_integral)
        return self.tags

    def route_file(self, vault_dir: str | None = None) -> str:
        source_archive = self._archive_name()
        self.target_dir = SemanticRouter(vault_dir).route(source_archive, self.signals, self.tags)
        return self.target_dir

    def format_outputs(self) -> Tuple[str, Dict[str, Any]]:
        markdown = outputs.build_markdown(self.metadata, self.tags, self.texte_integral, self.liens)
        jsonl = outputs.build_jsonl(self.metadata, self.tags, markdown)
        return markdown, jsonl

    def _archive_name(self) -> str:
        parts = [p.lower() for p in self.xml_path.replace("\\", "/").split("/")]
        for archive in ("cass", "capp", "constit", "jade", "inca"):
            if archive in parts:
                return archive
        return "cass"
