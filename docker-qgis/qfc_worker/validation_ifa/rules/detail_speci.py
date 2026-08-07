"""
Règles métier pour Détails des spécimens (table ifa_data.detail_speci).

Source : "Règles IFA 2.0/DETAIL_SPECI.groovy".

C'est la couche avec le plus grand nombre de règles du référentiel. Elles
sont regroupées ci-dessous par thème, dans le même ordre que le document
source, pour faciliter la comparaison ligne à ligne lors d'une relecture.

Non couvert ici (et pourquoi) : voir aussi README.md :
  - "Validation des données saisies Masse totale / Nombre pesé / Nombre
    capturé" et "Validation des occurrences entre Détail des spécimens et
    Dénombrement par espèce" : agrégations complexes nécessitant de croiser
    DETAIL_SPECI et DENOM_ESPEC par (No pêche, No pose et levée, Espèce,
    Panneau) : laissées en TODO_* (squelettes documentés en bas de fichier)
    par souci de fiabilité : une implémentation hÃ¢tive de cette logique
    d'agrégation risquerait de produire de faux positifs/négatifs difficiles
    à diagnostiquer sans données réelles pour la valider.
  - Filtre de "Type de structure" selon l'espèce (FILTRE_TYPE_STRUCTURE
    ci-dessous) : fourni comme donnée de référence et utilisable
    immédiatement comme règle de VALIDATION (vérifier que tsa_code_1/2
    appartient à la liste autorisée pour l'espèce), mais désactivé par
    défaut tant que la liste n'a pas été confirmée complète pour toutes
    les espèces du référentiel : voir TODO_filtre_type_structure.
  - assigner_no_vial / assigner_no_specimen_unique : fournies ci-dessous
    comme utilitaires testés unitairement (logique de numérotation
    automatique), mais NON enregistrées comme règles du moteur : ce sont
    des règles de SAISIE (numérotation au moment de l'ajout d'un nouveau
    spécimen dans le formulaire QGIS), pas des règles de validation d'un
    lot déjà complet.
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import (
    at_least_one_of,
    cross_field_lte,
    forbidden_values,
    required_field,
)

LAYER = "detail_speci"

ESPECES_INTERDITES = {"RIEN", "AU", "MULTI", "NI"}

TYPES_MARQUAGE_AVEC_DESCRIPTION = {
    "ABNAG", "AUTRE", "CHIM", "COLOR", "CRYO", "EMETT",
    "MAGN_C", "MAGN_NC", "PIT_TAG", "THERMI", "THERMO",
}
TYPES_MARQUAGE_AVEC_ETIQUETTE = {"CARLIN", "EXT_AUT", "SPAGH"}

# Panneau du filet : table de correspondance (type de pêche, grandeur de
# maille en mm) -> code de panneau. Construite à partir des listes
# énumérées dans le document source. Pour ajouter/corriger une
# correspondance : modifier directement ce dict, aucune autre partie du
# code n'a besoin d'être touchée.
PANNEAU_FILET_PAR_MAILLE: dict[str, dict[float, str]] = {
    "PENDJ_PENT": {25: "PAN1", 38: "PAN2", 51: "PAN3", 64: "PAN4",
                   76: "PAN5", 102: "PAN6", 127: "PAN7", 152: "PAN8"},
    "PENOC_PENOF": {25: "PAN1", 32: "PAN2", 38: "PAN3", 51: "PAN4",
                    64: "PAN5", 76: "PAN6"},
    "PECPM": {32: "PAN1", 19: "PAN2", 38: "PAN3", 13: "PAN4", 25: "PAN5"},
    "PECGM": {76: "PAN1", 114: "PAN2", 51: "PAN3", 89: "PAN4", 38: "PAN5",
              127: "PAN6", 64: "PAN7", 102: "PAN8"},
}
# Regroupements de types de pêche partageant la même grille de panneaux
# (voir le document source : "PENDJ"/"PENT" partagent la même liste, etc.)
GROUPES_TYPE_PECHE = {
    "PENDJ": "PENDJ_PENT", "PENT": "PENDJ_PENT",
    "PENOC": "PENOC_PENOF", "PENOF": "PENOC_PENOF",
    "PECPM": "PECPM",
    "PECGM": "PECGM",
}

# Espèce -> bornes du coefficient de condition K = masse*100000/longueur^3,
# utilisées comme avertissement de plausibilité biologique (pas une
# erreur bloquante : une valeur hors borne peut être une erreur de saisie
# OU un spécimen réellement atypique : à l'appréciation du biologiste).
COEFFICIENT_CONDITION_BORNES = {
    "CACA": (0.8, 1.3),
    "COAR": (0.6, 1.1),
    "COCL": (0.6, 1.4),
    "ESLU": (0.5, 0.9),
    # PEFL / SAFO / CACO partagent les mêmes bornes, de même que SAAL / SAVI.
    "PEFL": (0.8, 1.4),
    "SAFO": (0.8, 1.4),
    "CACO": (0.8, 1.4),
    "SANA": (0.6, 1.2),
    "SASA": (0.7, 1.4),
    "SAAL": (0.5, 0.9),
    "SAVI": (0.5, 0.9),
}


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
for _field, _label, _code in [
    ("dsp_no_speci", "Numéro de spécimen", "DETAIL_SPECI_NO_SPECI_REQUIS"),
    ("efa_code", "Espèce", "DETAIL_SPECI_ESPECE_REQUISE"),
    ("dsp_val_masse_g", "Masse", "DETAIL_SPECI_MASSE_REQUISE"),
    ("sex_code", "Sexe", "DETAIL_SPECI_SEXE_REQUIS"),
    ("mas_code", "Maturité sexuelle", "DETAIL_SPECI_MATURITE_REQUISE"),
]:
    register(LAYER, kind=RuleKind.VALIDATION)(required_field(_field, _label, code=_code))

register(LAYER, kind=RuleKind.VALIDATION)(at_least_one_of(
    ["dsp_long_tot_max_m", "dsp_long_fourc_mm"],
    "Longueur totale maximale, Longueur à la fourche",
    code="DETAIL_SPECI_LONGUEUR_REQUISE",
))

register(LAYER, kind=RuleKind.VALIDATION)(forbidden_values(
    "efa_code", "Espèce", ESPECES_INTERDITES, code="DETAIL_SPECI_ESPECE_INTERDITE",
))

register(LAYER, kind=RuleKind.VALIDATION)(cross_field_lte(
    "dsp_long_fourc_mm", "dsp_long_tot_max_m",
    "La longueur à la fourche doit être inférieure à la longueur totale maximale.",
    code="DETAIL_SPECI_COHERENCE_LONGUEURS", strict=True,
))


# ---------------------------------------------------------------------------
# Cohérence des indicateurs de contenu stomacal
# ---------------------------------------------------------------------------
INDICATEURS_CONTENU_STOMACAL = [
    "dsp_ind_conte_stoma_insec", "dsp_ind_conte_stoma_benth",
    "dsp_ind_conte_stoma_planc", "dsp_ind_conte_stoma_chyme",
    "dsp_ind_conte_stoma_poiss",
]


def _est_vrai(value) -> bool:
    """Les indicateurs booléens IFA sont stockés comme texte ('oui'/'non',
    '1'/'0', 'true'/'false' selon la couche) : normalise en bool Python."""
    return str(value).strip().lower() in {"1", "oui", "true", "vrai", "yes"}


@register(LAYER, kind=RuleKind.VALIDATION)
def contenu_stomacal_coherent(ctx: RuleContext) -> list[ValidationIssue]:
    """Si l'indicateur "contenu stomacal vide" est coché, aucun autre
    indicateur de contenu (insecte/benthos/plancton/chyme/poisson) ne
    devrait être coché."""
    row = ctx.row
    if _est_vrai(row.get("dsp_ind_conte_stoma_vide")):
        actifs = [f for f in INDICATEURS_CONTENU_STOMACAL if _est_vrai(row.get(f))]
        if actifs:
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_CONTENU_STOMACAL_INCOHERENT",
                message="Le contenu stomacal est indiqué Â« vide Â» mais d'autres indicateurs de contenu sont cochés.",
                fields=["dsp_ind_conte_stoma_vide", *actifs], record=ctx.record_key(),
            )]
    return []


@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def contenu_stomacal_poisson_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Si une espèce de poisson de contenu stomacal (1 ou 2) est renseignée,
    l'indicateur "contenu stomacal poisson" doit être activé."""
    row = ctx.row
    if (row.get("epo_code_stoma_1") or row.get("epo_code_stoma_2")) and not _est_vrai(row.get("dsp_ind_conte_stoma_poiss")):
        row["dsp_ind_conte_stoma_poiss"] = "oui"
    return []


@register(LAYER, kind=RuleKind.VALIDATION)
def especes_contenu_stomacal_coherentes(ctx: RuleContext) -> list[ValidationIssue]:
    """Si les deux espèces de contenu stomacal sont saisies, elles doivent
    être différentes. Si une seule est saisie, ce doit être la première
    (la 2 ne peut pas être renseignée seule)."""
    row = ctx.row
    sp1, sp2 = row.get("epo_code_stoma_1"), row.get("epo_code_stoma_2")
    issues = []
    if sp1 and sp2 and sp1 == sp2:
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_ESPECES_STOMACAL_IDENTIQUES",
            message="Les deux espèces de contenu stomacal doivent être différentes.",
            fields=["epo_code_stoma_1", "epo_code_stoma_2"], record=ctx.record_key(),
        ))
    if sp2 and not sp1:
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_ESPECE_STOMACAL_2_SANS_1",
            message="« Contenu stomacal - Espèce de poisson 2 » ne peut pas être renseignée si la 1 est vide.",
            fields=["epo_code_stoma_1", "epo_code_stoma_2"], record=ctx.record_key(),
        ))
    return issues


# ---------------------------------------------------------------------------
# Informations supplémentaires / Emplacement (bidirectionnel)
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.VALIDATION)
def emplacement_coherent(ctx: RuleContext) -> list[ValidationIssue]:
    row = ctx.row
    info_dispo = _est_vrai(row.get("dsp_ind_infor_suppl_dispo"))
    emplacement = row.get("dsp_val_empla")
    if info_dispo and not emplacement:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_EMPLACEMENT_REQUIS",
            message="« Emplacement » doit être renseigné quand des informations supplémentaires sont disponibles.",
            fields=["dsp_ind_infor_suppl_dispo", "dsp_val_empla"], record=ctx.record_key(),
        )]
    if emplacement and not info_dispo:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_INDICATEUR_INFOR_SUPPL_REQUIS",
            message="« Indicateur informations supplémentaires disponibles » doit être « oui » quand un emplacement est saisi.",
            fields=["dsp_ind_infor_suppl_dispo", "dsp_val_empla"], record=ctx.record_key(),
        )]
    return []


# ---------------------------------------------------------------------------
# Types de structure anatomique (âge)
# ---------------------------------------------------------------------------
AUCUNE_STRUCTURE = "AS"


@register(LAYER, kind=RuleKind.VALIDATION)
def types_structure_coherents(ctx: RuleContext) -> list[ValidationIssue]:
    row = ctx.row
    t1, t2 = row.get("tsa_code_1"), row.get("tsa_code_2")
    issues = []
    if t1 and t1 != AUCUNE_STRUCTURE and t2 and t2 != AUCUNE_STRUCTURE and t1 == t2:
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_TYPES_STRUCTURE_IDENTIQUES",
            message="Type de structure 1 et Type de structure 2 doivent être différents.",
            fields=["tsa_code_1", "tsa_code_2"], record=ctx.record_key(),
        ))
    if t2 and not t1:
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_TYPE_STRUCTURE_2_SANS_1",
            message="Type de structure 2 ne peut pas avoir une valeur si Type de structure 1 est vide.",
            fields=["tsa_code_1", "tsa_code_2"], record=ctx.record_key(),
        ))
    for echan_field, age_field, type_field, label in [
        ("dsp_no_echan_labor_1", "dsp_age_1", "tsa_code_1", "1"),
        ("dsp_no_echan_labor_2", "dsp_age_2", "tsa_code_2", "2"),
    ]:
        if row.get(echan_field) and row.get(age_field) is not None:
            type_val = row.get(type_field)
            if not type_val or type_val == AUCUNE_STRUCTURE:
                issues.append(ValidationIssue(
                    layer=ctx.layer, severity=Severity.ERROR, code=f"DETAIL_SPECI_TYPE_STRUCTURE_{label}_REQUIS",
                    message=(
                        f"Type de structure {label} doit être renseigné (et différent de "
                        f"« {AUCUNE_STRUCTURE} ») puisqu'un échantillon et un âge {label} sont saisis."
                    ),
                    fields=[type_field], record=ctx.record_key(),
                ))
    return issues


# ---------------------------------------------------------------------------
# Marquage
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.VALIDATION)
def marquage_coherent(ctx: RuleContext) -> list[ValidationIssue]:
    row = ctx.row
    type_marquage = row.get("tym_code")
    issues = []
    if type_marquage:
        if row.get("sma_code") is None:
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_STATUT_MARQUAGE_REQUIS",
                message="Le statut du marquage est obligatoire dès qu'un type de marquage est saisi.",
                fields=["tym_code", "sma_code"], record=ctx.record_key(),
            ))
        if type_marquage in TYPES_MARQUAGE_AVEC_DESCRIPTION and not row.get("dsp_descr_etiqu_marqu"):
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_DESCRIPTION_ETIQUETTE_REQUISE",
                message=f"La description de l'étiquette de marquage est obligatoire pour le type « {type_marquage} ».",
                fields=["dsp_descr_etiqu_marqu"], record=ctx.record_key(),
            ))
        elif type_marquage in TYPES_MARQUAGE_AVEC_ETIQUETTE:
            if not row.get("cou_code"):
                issues.append(ValidationIssue(
                    layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_COULEUR_ETIQUETTE_REQUISE",
                    message=f"La couleur de l'étiquette est obligatoire pour le type de marquage « {type_marquage} ».",
                    fields=["cou_code"], record=ctx.record_key(),
                ))
            if not row.get("dsp_no_etiqu_marqu"):
                issues.append(ValidationIssue(
                    layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_NO_ETIQUETTE_REQUIS",
                    message=f"Le numéro d'étiquette de marquage est obligatoire pour le type de marquage « {type_marquage} ».",
                    fields=["dsp_no_etiqu_marqu"], record=ctx.record_key(),
                ))
    return issues


@register(LAYER, kind=RuleKind.TRANSFORM)
def etiquettes_genetique_contamination_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Recopie Numéro échantillon laboratoire 1 vers les étiquettes
    génétique/contamination si elles sont vides."""
    row = ctx.row
    valeur = row.get("dsp_no_echan_labor_1")
    if valeur:
        if not row.get("dsp_no_etiqu_genet"):
            row["dsp_no_etiqu_genet"] = valeur
        if not row.get("dsp_no_etiqu_conta"):
            row["dsp_no_etiqu_conta"] = valeur
    return []


# ---------------------------------------------------------------------------
# Panneau du filet (assignation automatique selon type de pêche + maille)
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.TRANSFORM)
def panneau_filet_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Assigne automatiquement le Panneau du filet (cde_code) selon le
    Type de pêche de la pêche expérimentale parente (peche_exper.tpc_code)
    et la Grandeur de maille (dsp_val_grand_maill_mm) du spécimen, en
    utilisant la table de correspondance PANNEAU_FILET_PAR_MAILLE."""
    row = ctx.row
    key = (row.get("une_code_ident"), row.get("mes_no_seq"), row.get("pex_no_peche"))
    peche = next(
        (p for p in ctx.other_layer("peche_exper")
         if (p.get("une_code_ident"), p.get("mes_no_seq"), p.get("pex_no_peche")) == key),
        None,
    )
    if peche is None:
        return []

    groupe = GROUPES_TYPE_PECHE.get(peche.get("tpc_code"))
    maille = row.get("dsp_val_grand_maill_mm")
    if groupe and maille is not None:
        panneau = PANNEAU_FILET_PAR_MAILLE.get(groupe, {}).get(maille)
        if panneau:
            row["cde_code"] = panneau
    return []


# ---------------------------------------------------------------------------
# Coefficient de condition (avertissement de plausibilité biologique)
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.VALIDATION)
def coefficient_condition_plausible(ctx: RuleContext) -> list[ValidationIssue]:
    row = ctx.row
    bornes = COEFFICIENT_CONDITION_BORNES.get(row.get("efa_code"))
    longueur = row.get("dsp_long_tot_max_m")
    masse = row.get("dsp_val_masse_g")
    if not bornes or longueur in (None, 0) or masse is None:
        return []

    coefficient = masse * 100000 / (longueur ** 3)
    low, high = bornes
    if coefficient < low or coefficient > high:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.WARNING, code="DETAIL_SPECI_COEFFICIENT_CONDITION_HORS_BORNES",
            message=(
                f"Coefficient de condition calculé ({coefficient:.3f}) hors de la plage "
                f"attendue [{low}, {high}] pour l'espèce « {row.get('efa_code')} » : "
                "vérifier la masse et la longueur saisies."
            ),
            fields=["dsp_val_masse_g", "dsp_long_tot_max_m"], record=ctx.record_key(),
        )]
    return []


# ---------------------------------------------------------------------------
# Champs obligatoires des couches parentes (pêche expérimentale, pose/levée)
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.VALIDATION)
def peche_parente_complete(ctx: RuleContext) -> list[ValidationIssue]:
    """Aucun spécimen ne peut être créé tant que les caractéristiques de la
    pêche expérimentale parente (type de pêche, espèce visée, type d'engin)
    et de la pose/levée (dates de pose et de levée) ne sont pas saisies."""
    row = ctx.row
    issues: list[ValidationIssue] = []
    key3 = (row.get("une_code_ident"), row.get("mes_no_seq"), row.get("pex_no_peche"))
    peche = next(
        (p for p in ctx.other_layer("peche_exper")
         if (p.get("une_code_ident"), p.get("mes_no_seq"), p.get("pex_no_peche")) == key3),
        None,
    )
    if peche:
        manquants = [f for f in ("tpc_code", "efa_code", "teg_code") if not peche.get(f)]
        if manquants:
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_PECHE_PARENTE_INCOMPLETE",
                message=f"La pêche expérimentale parente est incomplète (champs manquants : {', '.join(manquants)}).",
                fields=manquants, record=ctx.record_key(),
            ))

    key4 = (row.get("une_code_ident"), row.get("mes_no_seq"), row.get("pex_no_peche"), row.get("plf_no_pose_levee"))
    pose = next(
        (p for p in ctx.other_layer("pose_levee_filet")
         if (p.get("une_code_ident"), p.get("mes_no_seq"), p.get("pex_no_peche"), p.get("plf_no_pose_levee")) == key4),
        None,
    )
    if pose:
        manquants = [f for f in ("plf_date_pose", "plf_date_levee") if not pose.get(f)]
        if manquants:
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_POSE_LEVEE_PARENTE_INCOMPLETE",
                message=f"La pose/levée parente est incomplète (champs manquants : {', '.join(manquants)}).",
                fields=manquants, record=ctx.record_key(),
            ))
    return issues


# ---------------------------------------------------------------------------
# Utilitaires de numérotation automatique (SAISIE, pas validation de lot :
# voir la docstring de module). Fournis tels que spécifiés dans le document
# source et couverts par des tests unitaires (tests/test_detail_speci.py).
# ---------------------------------------------------------------------------
def assigner_no_vial(specimens: list[dict], occurrence_courante: dict) -> str | None:
    """Génère un numéro d'échantillon automatique en incrémentant
    le plus grand numéro existant de 1.

    Args:
        specimens: liste de tous les spécimens existants. Chaque dict
            contient : 'echantillon_1', 'echantillon_2',
            'type_structure_1', 'type_structure_2'.
        occurrence_courante: le spécimen pour lequel on génère le numéro.

    Returns:
        Le nouveau numéro d'échantillon (ex: "43" ou "A43"), ou None si
        le spécimen courant n'est pas de type structure "OT" (Otolithe).
    """
    if occurrence_courante.get("type_structure_1") != "OT":
        return None

    max_echantillon_1 = 0.0
    max_echantillon_2 = 0.0
    lettre_debut_1 = " "
    lettre_debut_2 = " "

    def extraire_lettre_et_numero(valeur: str) -> tuple[str, float]:
        if not valeur:
            return " ", 0.0
        if not valeur[0].isdigit():
            return valeur[0], float(valeur[1:])
        return " ", float(valeur)

    for specimen in specimens:
        echantillon_1 = specimen.get("echantillon_1", "")
        echantillon_2 = specimen.get("echantillon_2", "")
        type_structure_1 = specimen.get("type_structure_1", "")
        type_structure_2 = specimen.get("type_structure_2", "")

        if echantillon_1 and type_structure_1 == "OT":
            lettre_temp, no_echant = extraire_lettre_et_numero(echantillon_1)
            if no_echant > max_echantillon_1:
                max_echantillon_1 = no_echant
                lettre_debut_1 = lettre_temp

        if echantillon_2 and type_structure_2 == "OT":
            lettre_temp, no_echant = extraire_lettre_et_numero(echantillon_2)
            if no_echant > max_echantillon_2:
                max_echantillon_2 = no_echant
                lettre_debut_2 = lettre_temp

    if max_echantillon_1 >= max_echantillon_2:
        max_no_seq = max_echantillon_1
        lettre_finale = lettre_debut_1
    else:
        max_no_seq = max_echantillon_2
        lettre_finale = lettre_debut_2

    max_no_seq += 1
    return f"{lettre_finale.strip()}{int(max_no_seq)}"


def assigner_no_specimen_unique(specimens: list[dict]) -> list[dict]:
    """Génère un numéro unique pour le dernier spécimen ajouté et copie
    l'espèce de l'avant-dernier spécimen.

    Args:
        specimens: liste de tous les spécimens. Le dernier est le nouveau
            (no_seq et espece à remplir). Chaque dict contient :
            'no_seq' (float), 'espece' (str).

    Returns:
        La liste mise à jour (inchangée si `specimens` est vide).
    """
    if not specimens:
        return specimens

    max_no_seq = 0.0
    espece_precedente = ""

    for i, specimen in enumerate(specimens):
        no_seq = specimen.get("no_seq", 0.0)
        if no_seq > max_no_seq:
            max_no_seq = no_seq
        if i == len(specimens) - 2:
            espece_precedente = specimen.get("espece", "")

    nouveau = specimens[-1]
    max_no_seq += 1
    nouveau["no_seq"] = max_no_seq
    nouveau["espece"] = espece_precedente

    return specimens


# Filtre de type de structure selon l'espèce : donnée de référence prête à
# l'emploi (voir TODO_filtre_type_structure ci-dessous pour l'activer comme
# règle de validation une fois confirmée).
FILTRE_TYPE_STRUCTURE_PAR_ESPECE: dict[str, set[str]] = {
    "ACFU": {"AU", "AS", "NP"}, "ACOX": {"AU", "AS", "NP"}, "ACSP": {"AU", "AS", "NP"},
    "ESLU": {"AU", "AS", "CL", "EC"}, "ESMA": {"AU", "AS", "CL", "EC"},
    "MIDO": {"AU", "AS", "OP"}, "MISA": {"AU", "AS", "OP"},
    "PEFL": {"AU", "AS", "ND", "OP", "OT"}, "SACA": {"AU", "AS", "ND", "OP", "OT"},
    "SANA": {"AU", "AS", "OT"}, "SAVI": {"AU", "AS", "OT"},
    "SAAL": {"AU", "AS", "OT", "EC"}, "SAFO": {"AU", "AS", "OT", "EC"},
}


def TODO_filtre_type_structure(ctx: RuleContext) -> list[ValidationIssue]:  # pragma: no cover
    """Point d'extension PRÉVU mais NON ACTIF.

    Vérifierait que tsa_code_1/tsa_code_2 appartient à
    FILTRE_TYPE_STRUCTURE_PAR_ESPECE.get(row["efa_code"]) quand l'espèce
    est l'une des espèces listées. Laissé inactif tant que la liste
    d'espèces n'a pas été confirmée exhaustive avec un expert métier
    (le document source ne couvre que 13 espèces sur l'ensemble du
    référentiel "espece_poisson").

    Pour activer : décorer avec ``@register(LAYER, kind=RuleKind.VALIDATION)``
    et renommer (retirer le préfixe TODO_).
    """
    raise NotImplementedError("Liste espèce -> type de structure non confirmée exhaustive.")
