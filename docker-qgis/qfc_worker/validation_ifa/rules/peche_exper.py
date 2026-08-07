"""
Règles métier : Pêche expérimentale (table ifa_data.peche_exper).

Source : "Règles IFA 2.0/PECHE_EXPER.groovy".

Règles couvertes :
  - Subdivision (SUB_CODE) restreinte à "1ÈRE"/"2E"/"COMPLÈTE" quand le
    type de pêche est "PENDJ".
  - Caractéristiques de l'engin (PEX_DESCR_CARAC), Espèce visée (EFA_CODE)
    et Type d'engin (TEG_CODE) assignés automatiquement selon le type de
    pêche (voir CARACTERISTIQUES_PAR_TYPE_PECHE).
  - Caractéristiques de l'engin obligatoires si Type d'engin = "AU".
  - Espèce visée : valeurs interdites "AU", "RIEN", "NI", "POIS".
  - Champs obligatoires : Numéro pêche, Type de pêche, Espèce visée,
    Type d'engin utilisé.

Non couvert ici :
  - "Effort de la pêche (IFD_EFFORT)" : décrit dans PECHE_EXPER.groovy mais
    le champ appartient à la table pose_levee_filet (le document le précise
    lui-même : « table pose levée filet »). La règle est donc implémentée
    dans rules/pose_levee_filet.py, où elle a accès à ifd_effort, et non ici.
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import forbidden_values, required_field

LAYER = "peche_exper"

TYPE_PECHE_AVEC_SUBDIVISION = "PENDJ"
SUBDIVISIONS_AUTORISEES = {"1ÈRE", "2E", "COMPLÈTE"}

ESPECES_VISEES_INTERDITES = {"AU", "RIEN", "NI", "POIS"}

TYPE_ENGIN_AUTRE = "AU"

# Type de pêche -> (caractéristiques de l'engin, espèce visée, type d'engin).
# Ces trois valeurs sont entièrement déterminées par le type de pêche : le
# document source les prescrit comme une assignation, pas comme un simple
# défaut, d'où l'écrasement d'une éventuelle valeur déjà saisie (voir
# caracteristiques_engin_autofill).
CARACTERISTIQUES_PAR_TYPE_PECHE: dict[str, tuple[str, str, str]] = {
    "PENDJ": ("8 panneaux, 7,6m X 1,8m, 25-38-51-64-76-102-127-152mm", "SAVI", "FX"),
    "PENOC": ("6 panneaux, 3,8m X 1,8, 25-32-38-51-64-76mm", "SAAL", "FX"),
    "PENOF": ("6 panneaux, 3,8m X 1,8, 25-32-38-51-64-76mm", "SAFO", "FX"),
    "PENT": ("8 panneaux, 7,6m X 1,8m, 25-38-51-64-76-102-127-152mm", "SANA", "FX"),
    "PECPM": ("2 bandes de filets à petites mailles de 5 panneaux. 2,5 x 1,8. 13-19-25-32-38",
              "MULTI", "FX"),
}


@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def caracteristiques_engin_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Assigne Caractéristiques de l'engin, Espèce visée et Type d'engin
    selon le type de pêche (les trois valeurs en découlent entièrement)."""
    row = ctx.row
    valeurs = CARACTERISTIQUES_PAR_TYPE_PECHE.get(row.get("tpc_code"))
    if valeurs is not None:
        row["pex_descr_carac"], row["efa_code"], row["teg_code"] = valeurs
    return []


@register(LAYER, kind=RuleKind.VALIDATION)
def subdivision_coherente(ctx: RuleContext) -> list[ValidationIssue]:
    """Pour une pêche de type "PENDJ", la subdivision doit être l'une des
    valeurs "1ÈRE" (1re partie de 2), "2E" (2e partie de 2) ou
    "COMPLÈTE" (pêche complétée en une partie)."""
    row = ctx.row
    if row.get("tpc_code") != TYPE_PECHE_AVEC_SUBDIVISION:
        return []
    if row.get("sub_code") in SUBDIVISIONS_AUTORISEES:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="PECHE_EXPER_SUBDIVISION_INVALIDE",
        message=(
            f"Pour une pêche de type « {TYPE_PECHE_AVEC_SUBDIVISION} », la subdivision doit "
            f"valoir l'une des valeurs suivantes : {', '.join(sorted(SUBDIVISIONS_AUTORISEES))}."
        ),
        fields=["sub_code"], record=ctx.record_key(),
    )]


register(LAYER, kind=RuleKind.VALIDATION)(required_field(
    "pex_descr_carac", "Caractéristiques de l'engin",
    code="PECHE_EXPER_CARACTERISTIQUES_REQUISES",
    when=lambda ctx: ctx.row.get("teg_code") == TYPE_ENGIN_AUTRE,
))

register(LAYER, kind=RuleKind.VALIDATION)(forbidden_values(
    "efa_code", "Espèce visée", ESPECES_VISEES_INTERDITES,
    code="PECHE_EXPER_ESPECE_VISEE_INTERDITE",
))


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
for _field, _label, _code in [
    ("pex_no_peche", "Numéro pêche", "PECHE_EXPER_NO_PECHE_REQUIS"),
    ("tpc_code", "Type de pêche", "PECHE_EXPER_TYPE_PECHE_REQUIS"),
    ("efa_code", "Espèce visée", "PECHE_EXPER_ESPECE_VISEE_REQUISE"),
    ("teg_code", "Type d'engin utilisé", "PECHE_EXPER_TYPE_ENGIN_REQUIS"),
]:
    register(LAYER, kind=RuleKind.VALIDATION)(required_field(_field, _label, code=_code))
