"""Formatage des sorties : Markdown (Obsidian) et dictionnaire JSONL."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Set

# Détection RegEx des visas de type « Vu l'article X du code Y ».
VISA_ARTICLE_RE = re.compile(
    r"(?i)\b(?:Vu\s+l['’]article|Vu\s+les\s+articles|L['’]article)\s+"
    r"(?P<art>[A-Za-z0-9][A-Za-z0-9.\-]*(?:\s+[A-Za-z0-9.\-]+)*?)\s+"
    r"(?:du|des)\s+(?P<code>code(?:\s+[A-Za-zÀ-ÿ'’]+){1,12})"
)

# Connecteurs marquant la reprise de la phrase après le nom du code :
# on tronque le nom du code à ces mots pour éviter d'inclure la suite du texte
# dans le wikilink (ex. « code de la sécurité sociale dans la mesure où ... »).
_CODE_STOP = re.compile(
    r"\s+(?:dans\b|aux\s+termes\b|selon\b|lesquels\b|lesquelles\b|qui\b|que\b|"
    r"dispose\b|disposent\b|prévoit\b|prévoient\b|énonce\b|notamment\b|"
    r"s['’]agissant\b|en\s+vertu\b|conformément\b|\bà\s+|\bau\s+|\baux\s+)",
    re.IGNORECASE,
)


def _code_name_from_texte(texte: str) -> str:
    """Extrait le nom du code depuis un libellé de lien (ex. « Code de commerce - art. 632 »)."""
    match = re.search(r"^(.*?)\s*[-.]\s*art\.", texte, re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(".")
    return texte.strip().rstrip(".")


def build_wikilink_from_lien(lien: Dict[str, str]) -> str:
    """Construit un wikilink Obsidian strict à partir d'un LIEN (LEGI/JURITEXT)."""
    num = (lien.get("num") or "").strip()
    texte = (lien.get("texte") or "").strip()
    nature = (lien.get("naturetexte", "") or "").upper()
    if nature == "CODE" and num:
        code_title = _code_name_from_texte(texte)
        if code_title:
            return f"[[Article {num} du {code_title}]]"
        return f"[[Article {num}]]"
    if texte:
        return f"[[{texte}]]"
    return ""


def replace_visa_mentions(texte: str) -> str:
    """Remplace les visas « Vu l'article X du code Y » par des wikilinks."""
    def _repl(match: "re.Match[str]") -> str:
        article = match.group("art").strip()
        code = _CODE_STOP.split(match.group("code"))[0].strip()
        return f"[[Article {article} du {code.capitalize()}]]"

    return VISA_ARTICLE_RE.sub(_repl, texte)


def build_frontmatter(metadata: Dict[str, Any], tags: Set[str]) -> str:
    """Génère le frontmatter YAML Obsidian."""
    lines = [
        "---",
        f"id: {metadata['id_document']}",
        f"source: {metadata['source_donnee']}",
        f"signature: {metadata['signature_extraction']}",
        f"date: {metadata['date']}",
        f"statut: {metadata['statut']}",
    ]
    if metadata.get("date_fin"):
        lines.append(f"date_fin: {metadata['date_fin']}")
    if metadata.get("num"):
        lines.append(f"num: {metadata['num']}")
    lines.append(f"tags: {json.dumps(sorted(tags), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def build_markdown(
    metadata: Dict[str, Any],
    tags: Set[str],
    texte_integral: str,
    liens: List[Dict[str, str]],
) -> str:
    """Assemble le corps Markdown complet (frontmatter + texte + wikilinks)."""
    frontmatter = build_frontmatter(metadata, tags)
    titre = metadata.get("titre", "").strip()
    body = replace_visa_mentions(texte_integral).strip()

    parts: List[str] = [frontmatter]
    if titre:
        parts.append(f"# {titre}")
    if body:
        parts.append(body)

    wikilinks = [w for w in (build_wikilink_from_lien(l) for l in liens) if w]
    if wikilinks:
        parts.append("")
        parts.append("## Références")
        parts.extend(f"- {w}" for w in wikilinks)

    return "\n\n".join(parts).strip() + "\n"


def build_jsonl(
    metadata: Dict[str, Any],
    tags: Set[str],
    markdown_text: str,
) -> Dict[str, Any]:
    """Construit l'objet JSONL agrégé pour la base vectorielle / RAG."""
    return {
        "id": metadata["id_document"],
        "source": metadata.get("source_donnee", ""),
        "statut": metadata.get("statut", ""),
        "date": metadata.get("date", ""),
        "date_fin": metadata.get("date_fin", ""),
        "num": metadata.get("num", ""),
        "titre": metadata.get("titre", ""),
        "categorie": metadata.get("categorie", ""),
        "tags": sorted(tags),
        "markdown": markdown_text,
    }
