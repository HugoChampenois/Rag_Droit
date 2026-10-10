"""Routeur sémantique : détermine le chemin Obsidian à partir des balises/tags.

Le chemin cible est construit sous la forme :
    {racine}/{matiere}/{type}
avec `racine` ∈ {Droit_Prive, Droit_Public, Droit_Penal, Autres},
`matiere` issu de la nomenclature juridique et `type` ∈ {Normatif, Jurisprudence}.
"""
from __future__ import annotations

import posixpath
from typing import Dict, List, Optional, Set, Tuple

from . import config
from .tagging import DeterministicTagger, fold_accents

# --------------------------------------------------------------------------- #
# Correspondances racine / matière -> nom de dossier
# --------------------------------------------------------------------------- #
RACINE_FOLDER: Dict[str, str] = {
    "droit_prive": "Droit_Prive",
    "droit_public": "Droit_Public",
    "droit_penal": "Droit_Penal",
}

MATIERE_FOLDER: Dict[str, str] = {
    "droit_general": "General",
    "droit_civil": "Civil",
    "droit_social": "Social",
    "droit_des_societes": "Societes",
    "droit_commercial": "Commercial",
    "droit_des_affaires": "Affaires",
    "droit_des_biens": "Biens",
    "droit_immobilier": "Immobilier",
    "droit_de_la_construction": "Immobilier",
    "droit_penal": "Penal",
    "procedure_penale": "Procedure_Penale",
    "procedure_civile": "Procedure_Civile",
    "droit_administratif": "Administratif",
    "droit_constitutionnel": "Constitutionnel",
    "droit_fiscal": "Fiscal",
    "droit_de_l_environnement": "Environnement",
    "droit_de_l_urbanisme": "Urbanisme",
    "droit_de_la_sante": "Sante",
    "droit_de_la_securite_sociale": "Securite_Sociale",
    "droit_de_la_consommation": "Consommation",
    "droit_bancaire_et_financier": "Bancaire_Financier",
    "droit_des_assurances": "Assurances",
    "droit_rural": "Rural",
    "droit_des_transports": "Transports",
    "droit_de_l_energie": "Energie",
    "droit_de_la_propriete_intellectuelle": "Propriete_Intellectuelle",
    "droit_de_l_education": "Education",
    "droit_de_la_fonction_publique": "Fonction_Publique",
    "droit_de_la_defense": "Defense",
    "droit_des_etrangers": "Etrangers",
    "droit_de_la_commande_publique": "Commande_Publique",
    "droit_du_sport": "Sport",
    "droit_du_tourisme": "Tourisme",
    "droit_de_l_artisanat": "Artisanat",
    "droit_minier": "Energie",
    "droit_forestier": "Environnement",
    "droit_des_douanes": "Douanes",
    "droit_de_la_securite_interieure": "Securite_Interieure",
    "droit_de_l_organisation_judiciaire": "Judiciaire",
    "droit_de_l_expropriation": "Expropriation",
    "droit_de_la_voirie": "Voirie",
    "droit_des_telecoms": "Telecoms",
    "droit_de_l_action_sociale": "Social_Administratif",
    "droit_de_la_famille": "Famille",
    "droit_des_personnes": "Personnes",
    "droit_des_obligations": "Obligations",
    "droit_des_successions": "Successions",
    "droit_de_la_responsabilite": "Responsabilite",
}

# --------------------------------------------------------------------------- #
# Correspondance type de source -> type de document
# --------------------------------------------------------------------------- #
TYPE_FOLDER: Dict[str, str] = {
    "legi": "Normatif",
    "cass": "Jurisprudence",
    "capp": "Jurisprudence",
    "constit": "Jurisprudence",
    "jade": "Jurisprudence",
    "inca": "Jurisprudence",
}

# --------------------------------------------------------------------------- #
# Mapping des codes (LEGI) vers (racine, matière)
# --------------------------------------------------------------------------- #
CODE_MAPPING: Dict[str, Tuple[str, str]] = {
    "code civil": ("droit_prive", "droit_civil"),
    "code de procedure civile": ("droit_prive", "procedure_civile"),
    "code de commerce": ("droit_prive", "droit_des_societes"),
    "code des societes": ("droit_prive", "droit_des_societes"),
    "code du travail": ("droit_prive", "droit_social"),
    "code de la securite sociale": ("droit_prive", "droit_de_la_securite_sociale"),
    "code de la consommation": ("droit_prive", "droit_de_la_consommation"),
    "code des assurances": ("droit_prive", "droit_des_assurances"),
    "code monetaire et financier": ("droit_prive", "droit_bancaire_et_financier"),
    "code de la propriete intellectuelle": ("droit_prive", "droit_de_la_propriete_intellectuelle"),
    "code rural et de la peche maritime": ("droit_prive", "droit_rural"),
    "code de la construction et de l'habitation": ("droit_prive", "droit_de_la_construction"),
    "code de la famille et de l'aide sociale": ("droit_prive", "droit_de_la_famille"),
    "code de l'artisanat": ("droit_prive", "droit_de_l_artisanat"),
    "code du tourisme": ("droit_prive", "droit_du_tourisme"),
    "code penal": ("droit_penal", "droit_penal"),
    "code de procedure penale": ("droit_penal", "procedure_penale"),
    "code de la justice penale des mineurs": ("droit_penal", "droit_penal"),
    "code general des impots": ("droit_public", "droit_fiscal"),
    "code de l'environnement": ("droit_public", "droit_de_l_environnement"),
    "code de l'urbanisme": ("droit_public", "droit_de_l_urbanisme"),
    "code de la sante publique": ("droit_public", "droit_de_la_sante"),
    "code de la route": ("droit_public", "droit_de_la_voirie"),
    "code de la voirie routiere": ("droit_public", "droit_de_la_voirie"),
    "code des transports": ("droit_public", "droit_des_transports"),
    "code de l'energie": ("droit_public", "droit_de_l_energie"),
    "code minier": ("droit_public", "droit_minier"),
    "code forestier": ("droit_public", "droit_forestier"),
    "code de l'education": ("droit_public", "droit_de_l_education"),
    "code general de la fonction publique": ("droit_public", "droit_de_la_fonction_publique"),
    "code de la defense": ("droit_public", "droit_de_la_defense"),
    "code de la securite interieure": ("droit_public", "droit_de_la_securite_interieure"),
    "code de justice administrative": ("droit_public", "droit_administratif"),
    "code des relations entre le public et l'administration": ("droit_public", "droit_administratif"),
    "code general de la propriete des personnes publiques": ("droit_public", "droit_administratif"),
    "code de la commande publique": ("droit_public", "droit_de_la_commande_publique"),
    "code des marches publics": ("droit_public", "droit_de_la_commande_publique"),
    "code de l'entree et du sejour des etrangers et du droit d'asile": ("droit_public", "droit_des_etrangers"),
    "code de l'organisation judiciaire": ("droit_public", "droit_de_l_organisation_judiciaire"),
    "code de l'expropriation pour cause d'utilite publique": ("droit_public", "droit_de_l_expropriation"),
    "code des postes et des communications electroniques": ("droit_public", "droit_des_telecoms"),
    "code de l'action sociale et des familles": ("droit_public", "droit_de_l_action_sociale"),
    "code des douanes": ("droit_public", "droit_des_douanes"),
    "code du sport": ("droit_public", "droit_du_sport"),
}

# --------------------------------------------------------------------------- #
# Routage par mots-clés pour les TNC (lois, décrets, arrêtés, ordonnances...)
# --------------------------------------------------------------------------- #
KEYWORD_ROUTING: List[Tuple[str, Tuple[str, str]]] = [
    ("genetiquement modifie", ("droit_public", "droit_de_l_environnement")),
    ("environnement", ("droit_public", "droit_de_l_environnement")),
    ("urbanisme", ("droit_public", "droit_de_l_urbanisme")),
    ("amenagement du territoire", ("droit_public", "droit_de_l_urbanisme")),
    ("impot", ("droit_public", "droit_fiscal")),
    ("fiscal", ("droit_public", "droit_fiscal")),
    ("taxe", ("droit_public", "droit_fiscal")),
    ("douane", ("droit_public", "droit_des_douanes")),
    ("sante publique", ("droit_public", "droit_de_la_sante")),
    ("securite sociale", ("droit_prive", "droit_de_la_securite_sociale")),
    ("travail", ("droit_prive", "droit_social")),
    ("emploi", ("droit_prive", "droit_social")),
    ("formation professionnelle", ("droit_prive", "droit_social")),
    ("education", ("droit_public", "droit_de_l_education")),
    ("enseignement", ("droit_public", "droit_de_l_education")),
    ("fonction publique", ("droit_public", "droit_de_la_fonction_publique")),
    ("societe", ("droit_prive", "droit_des_societes")),
    ("commercial", ("droit_prive", "droit_commercial")),
    ("consommation", ("droit_prive", "droit_de_la_consommation")),
    ("assurance", ("droit_prive", "droit_des_assurances")),
    ("banque", ("droit_prive", "droit_bancaire_et_financier")),
    ("finance", ("droit_prive", "droit_bancaire_et_financier")),
    ("commande publique", ("droit_public", "droit_de_la_commande_publique")),
    ("marche public", ("droit_public", "droit_de_la_commande_publique")),
    ("defense nationale", ("droit_public", "droit_de_la_defense")),
    ("securite interieure", ("droit_public", "droit_de_la_securite_interieure")),
    ("justice", ("droit_public", "droit_de_l_organisation_judiciaire")),
    ("expropriation", ("droit_public", "droit_de_l_expropriation")),
    ("energie", ("droit_public", "droit_de_l_energie")),
    ("transport", ("droit_public", "droit_des_transports")),
    ("sport", ("droit_public", "droit_du_sport")),
    ("propriete intellectuelle", ("droit_prive", "droit_de_la_propriete_intellectuelle")),
    ("construction", ("droit_prive", "droit_de_la_construction")),
    ("logement", ("droit_prive", "droit_de_la_construction")),
    ("agriculture", ("droit_prive", "droit_rural")),
    ("peche maritime", ("droit_prive", "droit_rural")),
]


class SemanticRouter:
    """Calcule le chemin cible d'un document à partir de ses signaux."""

    def __init__(self, vault_dir: Optional[str] = None) -> None:
        self.vault_dir = vault_dir or config.VAULT_OBSIDIAN_DIR

    def route(self, source_archive: str, signals: Dict[str, str], tags: Set[str]) -> str:
        type_folder = TYPE_FOLDER.get(source_archive, "Normatif")
        if source_archive == "legi":
            racine_tag, matiere_tag = self.resolve_legi(signals)
        else:
            racine_tag, matiere_tag = self._resolve_jurisprudence(signals)

        racine = RACINE_FOLDER.get(racine_tag, "Autres")
        matiere = MATIERE_FOLDER.get(matiere_tag, "Autres")
        return posixpath.join(self.vault_dir, racine, matiere, type_folder)

    @staticmethod
    def _resolve_jurisprudence(signals: Dict[str, str]) -> Tuple[str, str]:
        entete = DeterministicTagger.resolve_entete(
            signals.get("chambre"), signals.get("juridiction")
        )
        return entete["racine"], entete["matiere"]

    @staticmethod
    def resolve_legi(signals: Dict[str, str]) -> Tuple[str, str]:
        titre = fold_accents(" ".join(filter(None, [signals.get("titre", ""), signals.get("titrefull", "")])))
        nature = (signals.get("nature", "") or "").strip().upper()

        if nature == "CODE" or "code" in titre:
            for code_name, mapping in CODE_MAPPING.items():
                if fold_accents(code_name) in titre:
                    return mapping
            return "droit_prive", "droit_general"

        for keyword, mapping in KEYWORD_ROUTING:
            if fold_accents(keyword) in titre:
                return mapping
        return "droit_prive", "droit_general"
