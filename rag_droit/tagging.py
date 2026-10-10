"""Moteur de tagging déterministe.

Aucune inférence générative : uniquement des dictionnaires d'en-têtes et des
expressions régulières strictes. Produit un `set` de tags qualifiés (dédoublonnés
par construction).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def fold_accents(text: str) -> str:
    """Supprime les accents et met en minuscules (pour la recherche)."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def _norm(text: str) -> str:
    """Normalise un libellé libre : minuscules, sans accent, espaces unifiés."""
    return " ".join(fold_accents(text or "").split())


# --------------------------------------------------------------------------- #
# Dictionnaires d'en-têtes
# --------------------------------------------------------------------------- #
# Les clés correspondent aux codes de <FORMATION> de la donnée DILA (ex. CASS)
# ainsi qu'à quelques libellés lisibles (rétro-compatibilité).
CHAMBRE_MAPPING: Dict[str, Dict[str, str]] = {
    "chambre_sociale": {"juridiction": "cass_soc", "racine": "droit_prive", "matiere": "droit_social"},
    "chambre_commerciale": {"juridiction": "cass_com", "racine": "droit_prive", "matiere": "droit_des_societes"},
    "chambre_criminelle": {"juridiction": "cass_crim", "racine": "droit_penal", "matiere": "droit_penal"},
    "chambre_civile_1": {"juridiction": "cass_civ1", "racine": "droit_prive", "matiere": "droit_civil"},
    "chambre_civile_2": {"juridiction": "cass_civ2", "racine": "droit_prive", "matiere": "droit_civil"},
    "chambre_civile_3": {"juridiction": "cass_civ3", "racine": "droit_prive", "matiere": "droit_des_biens"},
    "chambre_civile": {"juridiction": "cass_civ", "racine": "droit_prive", "matiere": "droit_civil"},
    "assemblee_pleniere": {"juridiction": "cass_ap", "racine": "droit_prive", "matiere": "droit_civil"},
    "chambre_mixte": {"juridiction": "cass_mixte", "racine": "droit_prive", "matiere": "droit_civil"},
    "chambres_reunies": {"juridiction": "cass_chambres_reunies", "racine": "droit_prive", "matiere": "droit_general"},
    "avis": {"juridiction": "cass_avis", "racine": "droit_prive", "matiere": "droit_general"},
    "commission_reparation_detention": {"juridiction": "cass_crd", "racine": "droit_penal", "matiere": "procedure_penale"},
    # libellés lisibles (données anciennes ou autres fournisseurs)
    "sociale": {"juridiction": "cass_soc", "racine": "droit_prive", "matiere": "droit_social"},
    "commerciale": {"juridiction": "cass_com", "racine": "droit_prive", "matiere": "droit_des_societes"},
    "criminelle": {"juridiction": "cass_crim", "racine": "droit_penal", "matiere": "droit_penal"},
    "premiere chambre civile": {"juridiction": "cass_civ1", "racine": "droit_prive", "matiere": "droit_civil"},
    "deuxieme chambre civile": {"juridiction": "cass_civ2", "racine": "droit_prive", "matiere": "droit_civil"},
    "troisieme chambre civile": {"juridiction": "cass_civ3", "racine": "droit_prive", "matiere": "droit_des_biens"},
    "chambre civile": {"juridiction": "cass_civ", "racine": "droit_prive", "matiere": "droit_civil"},
    "assemblee pleniere": {"juridiction": "cass_ap", "racine": "droit_prive", "matiere": "droit_civil"},
    "chambre mixte": {"juridiction": "cass_mixte", "racine": "droit_prive", "matiere": "droit_civil"},
}

JURIDICTION_MAPPING: Dict[str, Dict[str, str]] = {
    "cour de cassation": {"juridiction": "cass", "racine": "droit_prive", "matiere": "droit_general"},
    "cour d'appel": {"juridiction": "cour_appel", "racine": "droit_prive", "matiere": "droit_general"},
    "cour administrative d'appel": {"juridiction": "cour_admin_appel", "racine": "droit_public", "matiere": "droit_administratif"},
    "caa": {"juridiction": "cour_admin_appel", "racine": "droit_public", "matiere": "droit_administratif"},
    "conseil constitutionnel": {"juridiction": "conseil_constitutionnel", "racine": "droit_public", "matiere": "droit_constitutionnel"},
    "conseil d'etat": {"juridiction": "conseil_etat", "racine": "droit_public", "matiere": "droit_administratif"},
    "tribunal des conflits": {"juridiction": "tribunal_conflits", "racine": "droit_public", "matiere": "droit_administratif"},
    "tribunal administratif": {"juridiction": "tribunal_administratif", "racine": "droit_public", "matiere": "droit_administratif"},
    "conseil de prud'hommes": {"juridiction": "conseil_prudhommes", "racine": "droit_prive", "matiere": "droit_social"},
    "tribunal de commerce": {"juridiction": "tribunal_commerce", "racine": "droit_prive", "matiere": "droit_des_societes"},
    "tribunal judiciaire": {"juridiction": "tribunal_judiciaire", "racine": "droit_prive", "matiere": "droit_general"},
}

# Règles de statut issues de <SOLUTION> (jurisprudence), dans l'ordre de priorité.
SOLUTION_RULES: List[Tuple[str, str]] = [
    ("cassation partielle sans renvoi", "cassation_partielle_sans_renvoi"),
    ("cassation partielle", "cassation_partielle"),
    ("cassation sans renvoi", "cassation_sans_renvoi"),
    ("cassation", "cassation"),
    ("irrecevabilite", "irrecevabilite"),
    ("irrecevable", "irrecevabilite"),
    ("desistement", "desistement"),
    ("satisfaction totale", "satisfaction_totale"),
    ("satisfaction partielle", "satisfaction_partielle"),
    ("annulation partielle", "annulation_partielle"),
    ("annulation totale", "annulation_totale"),
    ("reformation", "reformation"),
    ("decharge", "decharge"),
    ("annulation", "annulation"),
    ("non conformite totale", "non_conformite_totale"),
    ("non conformite partielle", "non_conformite_partielle"),
    ("non conformite", "non_conformite"),
    ("conformite reserve", "conformite_reserve"),
    ("conformite", "conformite"),
    ("ineligibilite", "ineligibilite"),
    ("non lieu", "non_lieu"),
    ("decheance", "decheance"),
    ("qpc", "qpc"),
    ("avis", "avis"),
    ("confirme", "confirme"),
    ("infirme", "infirme"),
    ("rejet", "rejet"),
    ("annule", "annulation"),
]

ETAT_MAPPING: Dict[str, str] = {
    "VIGUEUR": "vigueur",
    "ABROGE": "abroge",
    "ABROGE_DIFF": "abroge_differe",
    "MODIFIE": "modifie",
    "PERIME": "perime",
    "REMIS_EN_VIGUEUR": "remis_en_vigueur",
}

# --------------------------------------------------------------------------- #
# Dictionnaires RegEx (formes sociales et termes administratifs)
# --------------------------------------------------------------------------- #
# Le terme générique « entreprise » est volontairement proscrit.
FORMES_SOCIALES_PHRASES: List[Tuple[str, str]] = [
    ("societe a responsabilite limitee", "SARL"),
    ("societe par actions simplifiee", "SAS"),
    ("societe anonyme", "SA"),
    ("societe en nom collectif", "SNC"),
    ("societe en commandite", "SCS"),
    ("societe par actions", "SA"),
    ("societe civile", "SC"),
    ("societe cooperative", "SCOP"),
]

# Acronymes : ordre du plus spécifique au plus générique.
ACRONYMES_SOCIAUX: List[Tuple[str, str]] = [
    ("SASU", "SASU"),
    ("EURL", "EURL"),
    ("SARL", "SARL"),
    ("SCOP", "SCOP"),
    ("SAS", "SAS"),
    ("SNC", "SNC"),
    ("SCI", "SCI"),
    ("SCA", "SCA"),
    ("GIE", "GIE"),
    ("SA", "SA"),
]

TERMES_ADMINISTRATIFS: List[Tuple[str, str]] = [
    ("etablissement public de cooperation intercommunale", "EPCI"),
    ("etablissement public", "etablissement_public"),
    ("collectivite territoriale", "collectivite_territoriale"),
    ("epci", "EPCI"),
    ("syndicat mixte", "syndicat_mixte"),
    ("commune", "commune"),
    ("departement", "departement"),
    ("prefet", "prefet"),
    ("prefecture", "prefecture"),
]

# --------------------------------------------------------------------------- #
# Moteur
# --------------------------------------------------------------------------- #
class DeterministicTagger:
    """Applique les règles strictes d'en-têtes et de RegEx pour produire les tags."""

    @staticmethod
    def _lookup(folded: str, mapping: Dict[str, Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Recherche d'abord une correspondance exacte, puis une inclusion."""
        if not folded:
            return None
        exact = mapping.get(folded)
        if exact is not None:
            return exact
        for key, value in mapping.items():
            if key in folded:
                return value
        return None

    @staticmethod
    def resolve_entete(chambre: Optional[str], juridiction: Optional[str]) -> Dict[str, str]:
        """Résout la juridiction, la racine et la matière à partir des en-têtes.

        - Cour de cassation : la chambre/formation prime (juridiction spécialisée ex. cass_soc).
        - Autre juridiction (cour d'appel, conseil d'État, conseil constitutionnel...) :
          la juridiction prime, la formation n'affine que la matière.
        """
        chambre_map = DeterministicTagger._lookup(_norm(chambre), CHAMBRE_MAPPING) if chambre else None
        juridiction_map = DeterministicTagger._lookup(_norm(juridiction), JURIDICTION_MAPPING) if juridiction else None

        if juridiction_map and juridiction_map["juridiction"] == "cass":
            return dict(chambre_map) if chambre_map else dict(juridiction_map)
        if juridiction_map:
            result = dict(juridiction_map)
            if chambre_map:
                result["matiere"] = chambre_map["matiere"]
                result["racine"] = chambre_map["racine"]
            return result
        if chambre_map:
            return dict(chambre_map)
        return {"juridiction": "juridiction_inconnue", "racine": "droit_prive", "matiere": "droit_general"}

    @staticmethod
    def statut_from_solution(solution: Optional[str]) -> Optional[str]:
        if not solution:
            return None
        normalized = _norm(solution).replace(".", " ").replace("-", " ")
        normalized = " ".join(normalized.split())
        for keyword, tag in SOLUTION_RULES:
            if keyword in normalized:
                return tag
        return None

    @staticmethod
    def statut_from_etat(etat: Optional[str]) -> Optional[str]:
        if not etat:
            return None
        return ETAT_MAPPING.get(etat.strip().upper())

    @staticmethod
    def publication_tag(publication: Optional[str]) -> Optional[str]:
        if not publication:
            return None
        folded = fold_accents(publication)
        if "publie" in folded and "non publie" not in folded:
            return "arret_de_principe"
        return None

    @staticmethod
    def analyse_texte(texte: str) -> Set[str]:
        """Détection RegEx des personnes morales dans le texte intégral."""
        folded = fold_accents(texte)
        formes: Set[str] = set()
        types_publics: Set[str] = set()

        for phrase, label in FORMES_SOCIALES_PHRASES:
            if re.search(re.escape(phrase), folded):
                formes.add(label)
        for acronym, label in ACRONYMES_SOCIAUX:
            if re.search(r"\b" + re.escape(acronym) + r"\b", texte):
                formes.add(label)

        for phrase, label in TERMES_ADMINISTRATIFS:
            if re.search(re.escape(phrase), folded):
                types_publics.add(label)

        has_societe = re.search(r"\bsociete", folded) is not None

        if formes and types_publics:
            return {"personne_morale_a_qualifier"}
        if formes:
            result = {"personne_morale_droit_prive", "societe"}
            result.update(formes)
            return result
        if types_publics:
            result = {"personne_morale_droit_public"}
            result.update(types_publics)
            return result
        if has_societe:
            return {"personne_morale_a_qualifier"}
        return set()

    @staticmethod
    def generate(signals: Dict[str, str], texte: str) -> Set[str]:
        """Agrège les tags d'une décision (en-têtes + analyse textuelle)."""
        tags: Set[str] = set()

        entete = DeterministicTagger.resolve_entete(
            signals.get("chambre"), signals.get("juridiction")
        )
        if entete.get("juridiction"):
            tags.add(entete["juridiction"])
        if entete.get("racine"):
            tags.add(entete["racine"])
        if entete.get("matiere"):
            tags.add(entete["matiere"])

        statut = DeterministicTagger.statut_from_solution(signals.get("solution"))
        if statut:
            tags.add(statut)

        publication = DeterministicTagger.publication_tag(signals.get("publication"))
        if publication:
            tags.add(publication)

        tags.update(DeterministicTagger.analyse_texte(texte))
        return tags

    @staticmethod
    def generate_legi(signals: Dict[str, str], texte: str) -> Set[str]:
        """Agrège les tags d'un texte normatif LEGI (état + analyse textuelle).

        La racine et la matière sont ajoutées par l'appelant via le routeur
        (mapping des codes / mots-clés), et non via les en-têtes de jurisprudence.
        """
        tags: Set[str] = set()

        statut = DeterministicTagger.statut_from_etat(signals.get("etat"))
        if statut:
            tags.add(statut)

        tags.update(DeterministicTagger.analyse_texte(texte))
        return tags
