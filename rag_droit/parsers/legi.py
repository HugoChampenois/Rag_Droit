"""Parseur spécialisé pour les fichiers LEGI (TEXTE_VERSION et ARTICLE)."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .. import outputs
from ..router import SemanticRouter
from ..tagging import DeterministicTagger
from .base import DocumentParser, SkipDocument

_TAG_RE = re.compile(r"<[^>]+>")

# Préfixes NOR (3 premières lettres) du domaine budget / finances / fiscal.
# Permet de conserver les décrets/arrêtés/ordonnances techniques du droit fiscal
# même lorsqu'ils ne mentionnent pas « loi de finances » dans leur titre.
_FINANCE_NOR_PREFIXES = ("BCR", "BCF", "CPA", "EFI", "FCP", "ECF", "BCP", "BUD")

# Mots-clés de titre pour les textes législatifs financiers (lois de finances,
# LFSS, lois de règlement, lois de programmation des finances publiques).
_FINANCE_TITLE_KEYS = (
    "de finances",
    "financement de la sécurité sociale",
    "de règlement",
    "programmation des finances",
)


class LegiParser(DocumentParser):
    """Parse un XML LEGI (texte de code / TNC ou article)."""

    def parse(self) -> "LegiParser":
        raw = self.read_content()
        self.compute_signature()
        self.root = ET.fromstring(raw)
        self._kind = self._detect_kind()
        if self._kind == "struct":
            raise SkipDocument("sommaire <TEXTELR> ignoré (structure, pas de texte)")
        self.signals = self._extract_signals()
        if self._in_tnc_folder() and not self._is_finance():
            raise SkipDocument("TNC hors domaine budget/finances, non retenu")
        self.texte_integral = self._extract_texte_integral()
        self.liens = self._extract_liens()
        return self

    # ------------------------------------------------------------------ #
    # Détection du type de document LEGI
    # ------------------------------------------------------------------ #
    def _detect_kind(self) -> str:
        tag = self.root.tag.rsplit("}", 1)[-1].upper()
        if tag == "ARTICLE":
            return "article"
        if tag == "SECTION_TA":
            return "section_ta"
        if tag == "TEXTELR":
            return "struct"
        return "texte_version"

    def _root_child_text(self, tag: str) -> str:
        child = self.root.find(tag)
        return (child.text or "").strip() if child is not None and child.text else ""

    def _in_tnc_folder(self) -> bool:
        """True si le fichier provient d'un dossier TNC (textes non codifiés)."""
        parts = [p.lower() for p in Path(self.xml_path).parts]
        return any(d in ("tnc_en_vigueur", "tnc_non_vigueur") for d in parts)

    def _is_finance(self) -> bool:
        """True si le texte/article relève du domaine budget / finances / fiscal.

        Deux critères (OU) :
          1. préfixe NOR (3 lettres) appartenant au domaine finance ;
          2. texte législatif (LOI / LOI_ORGANIQUE) dont le titre contient un
             mot-clé financier (lois de finances, LFSS, règlement, LPFP).
        """
        if self._kind == "article":
            nature = (self.signals.get("nature_texte") or "").upper()
            nor = (self.signals.get("nor_texte") or "").strip().upper()
            titre = (self.signals.get("titre") or "").lower()
        else:
            nature = (self.signals.get("nature") or "").upper()
            nor = (self.signals.get("nor") or "").strip().upper()
            titre = (self.signals.get("titrefull") or self.signals.get("titre") or "").lower()
        if nor and nor[:3] in _FINANCE_NOR_PREFIXES:
            return True
        if nature in ("LOI", "LOI_ORGANIQUE"):
            return any(key in titre for key in _FINANCE_TITLE_KEYS)
        return False

    @staticmethod
    def _child_text(node: ET.Element, tag: str) -> str:
        child = node.find(tag)
        return (child.text or "").strip() if child is not None and child.text else ""

    def _extract_signals(self) -> Dict[str, str]:
        if self._kind == "section_ta":
            return self._extract_section_signals()
        meta_commun = self.root.find("META/META_COMMUN")
        nature = self._child_text(meta_commun, "NATURE") if meta_commun is not None else ""
        identifiant = self._child_text(meta_commun, "ID") if meta_commun is not None else ""

        signals: Dict[str, str] = {"nature": nature, "id": identifiant}

        if self._kind == "article":
            meta_article = self.root.find("META/META_SPEC/META_ARTICLE")
            if meta_article is not None:
                signals["num"] = self._child_text(meta_article, "NUM")
                signals["etat"] = self._child_text(meta_article, "ETAT")
                signals["date"] = self._child_text(meta_article, "DATE_DEBUT")
                signals["date_fin"] = self._child_text(meta_article, "DATE_FIN")
            texte = self.root.find("CONTEXTE/TEXTE")
            if texte is not None:
                signals["nature_texte"] = (texte.get("nature") or "").strip()
                signals["nor_texte"] = (texte.get("nor") or "").strip()
            titre_txt = self.root.find("CONTEXTE/TEXTE/TITRE_TXT")
            if titre_txt is not None:
                signals["titre"] = (titre_txt.text or titre_txt.get("c_titre_court") or "").strip()
        else:
            meta_version = self.root.find("META/META_SPEC/META_TEXTE_VERSION")
            if meta_version is not None:
                signals["titre"] = self._child_text(meta_version, "TITRE")
                signals["titrefull"] = self._child_text(meta_version, "TITREFULL")
                signals["etat"] = self._child_text(meta_version, "ETAT")
                signals["date"] = self._child_text(meta_version, "DATE_DEBUT")
                signals["date_fin"] = self._child_text(meta_version, "DATE_FIN")
            meta_chrono = self.root.find("META/META_SPEC/META_TEXTE_CHRONICLE")
            if meta_chrono is not None:
                signals["nor"] = self._child_text(meta_chrono, "NOR")
                if not signals.get("date"):
                    signals["date"] = self._child_text(meta_chrono, "DATE_TEXTE")
        return signals

    def _extract_section_signals(self) -> Dict[str, str]:
        signals: Dict[str, str] = {
            "nature": "SECTION_TA",
            "id": self._root_child_text("ID"),
            "titre": self._root_child_text("TITRE_TA"),
        }
        titre_txt = self.root.find("CONTEXTE/TEXTE/TITRE_TXT")
        if titre_txt is not None:
            code_name = titre_txt.get("c_titre_court") or titre_txt.text or ""
            signals["titrefull"] = code_name.strip()
        return signals

    # ------------------------------------------------------------------ #
    # Extraction du texte intégral
    # ------------------------------------------------------------------ #
    def _extract_texte_integral(self) -> str:
        if self._kind == "section_ta":
            parts: List[str] = [self.signals.get("titre", "")]
            articles = [a.get("num", "") for a in self.root.iter("LIEN_ART") if a.get("num")]
            if articles:
                parts.append("Articles : " + ", ".join(articles))
            return "\n".join(p for p in parts if p).strip()

        if self._kind == "article":
            sections = ("BLOC_TEXTUEL", "NOTA")
        else:
            sections = ("VISAS", "SIGNATAIRES", "TP", "NOTA", "ABRO", "RECT")

        blocs: List[str] = []
        for section in sections:
            contenu = self.root.find(f"{section}/CONTENU")
            if contenu is not None:
                text = self._content_to_text(contenu)
                if text:
                    blocs.append(text)
        return "\n\n".join(blocs).strip()

    @staticmethod
    def _content_to_text(content_el: ET.Element) -> str:
        raw = ET.tostring(content_el, encoding="unicode")
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
        text = _TAG_RE.sub("", raw)
        return html.unescape(text).strip()

    def _extract_liens(self) -> List[Dict[str, str]]:
        liens: List[Dict[str, str]] = []
        for lien in self.root.iter("LIEN"):
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
        id_document = self.signals.get("nor") or self.signals.get("id") or self._safe_basename(self.xml_path)
        statut = DeterministicTagger.statut_from_etat(self.signals.get("etat")) or "inconnu"
        self.metadata = {
            "id_document": id_document,
            "source_donnee": self.detect_source(),
            "signature_extraction": self.signature_extraction,
            "date": self.signals.get("date", ""),
            "date_fin": self.signals.get("date_fin", ""),
            "num": self.signals.get("num", ""),
            "statut": statut,
            "titre": self._build_titre(),
            "categorie": self._categorie(),
        }
        return self.metadata

    def _categorie(self) -> str:
        """Catégorie de contenu : « code » (article de code) ou « finance »
        (texte/article du domaine budget/finances non codifié)."""
        return "finance" if self._in_tnc_folder() else "code"

    def _build_titre(self) -> str:
        """Titre lisible : pour un article, « Article {NUM} du {Code} » afin que
        la numérotation (ancienne comme nouvelle) soit indexée et retrouvable."""
        if self._kind == "article":
            num = (self.signals.get("num") or "").strip()
            code = (self.signals.get("titre") or "").strip()
            if num and code:
                return f"Article {num} du {code}"
            return code or num
        return self.signals.get("titrefull") or self.signals.get("titre", "")

    def generate_tags(self) -> Set[str]:
        self.tags = DeterministicTagger.generate_legi(self.signals, self.texte_integral)
        racine, matiere = SemanticRouter.resolve_legi(self.signals)
        self.tags.add(racine)
        self.tags.add(matiere)
        num = (self.signals.get("num") or "").strip()
        if num:
            self.tags.add(f"article_{re.sub(r'[^a-z0-9]+', '_', num.lower()).strip('_')}")
        return self.tags

    def route_file(self, vault_dir: str | None = None) -> str:
        self.target_dir = SemanticRouter(vault_dir).route("legi", self.signals, self.tags)
        return self.target_dir

    def format_outputs(self) -> Tuple[str, Dict[str, Any]]:
        markdown = outputs.build_markdown(self.metadata, self.tags, self.texte_integral, self.liens)
        jsonl = outputs.build_jsonl(self.metadata, self.tags, markdown)
        return markdown, jsonl
