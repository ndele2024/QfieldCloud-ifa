"""
Règles métier : Equipe de travail (table ifa_data.equipe).

Source : "Règles IFA 2.0/EQUIPE.groovy".

Règle couverte :
  - champs obligatoires : responsable de l'équipe (EQR_CODE_RESPO) ou le nom d'un intervenant externe (TIE_CODE)
  - Un responsable de l'équipe (EQR_CODE_RESPO) ou le nom d'un intervenant externe (TIE_CODE) est requis pour un inventaire.
  donc il faut au moins un enregistrement de EQUIPE avec les valeurs de EQR_CODE_RESPO ou de TIE_CODE

Non couvert ici :
    - RAS
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import at_least_one_of

LAYER = "equipe"

register(LAYER, kind=RuleKind.VALIDATION)(at_least_one_of(
    ["eqr_code_respo", "tie_code"],
    "responsable de l'équipe, nom de l'intervenant externe",
    code="NOM_RESPONSABLE_EQUIPE_REQUIS",
))

@register(LAYER, kind=RuleKind.LAYER)
def equipe_validation(ctx: RuleContext) -> list[ValidationIssue]:
    """RuleKind.LAYER : évaluée une seule fois par couche, y compris quand
    elle est vide."""
    all_rows = ctx.all_rows
    if len(all_rows) < 1:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="EQUIPE_AU_MOINS_UN_ENREGISTEMENT",
            message=f"Un inventaire doit avoir au moins un enregistrement pour la couche/table « {LAYER} ».",
            fields=[], record=ctx.record_key(),
        )]
    return []