"""
Règles métier : Forme de la description d'habitat (table ifa_data.forme_descr_habit).

Règle couverte :
  - Le nombre d'enregistrements de cette couche, pour un même lot, ne doit
    pas dépasser 15.

Non couvert ici :
    - RAS
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind

LAYER = "forme_descr_habit"

NOMBRE_MAX_ENREGISTREMENTS = 15


@register(LAYER, kind=RuleKind.LAYER)
def forme_descr_habit_nombre_max(ctx: RuleContext) -> list[ValidationIssue]:
    """RuleKind.LAYER : évaluée une seule fois pour toute la couche (voir
    core.engine.run), donc pas de risque d'anomalie dupliquée par ligne."""
    all_rows = ctx.all_rows
    if len(all_rows) <= NOMBRE_MAX_ENREGISTREMENTS:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="FORME_DESCR_HABIT_NOMBRE_MAX_ENREGISTREMENTS",
        message=(
            f"La couche/table « {LAYER} » ne doit pas contenir plus de "
            f"{NOMBRE_MAX_ENREGISTREMENTS} enregistrements (actuellement {len(all_rows)})."
        ),
        fields=[], record=ctx.record_key(),
    )]
