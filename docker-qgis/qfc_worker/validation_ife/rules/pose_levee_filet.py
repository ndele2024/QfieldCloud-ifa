"""
Règles métier : Pose et levée de filet (table ifa_data.pose_levee_filet).

Source : "UE IFE LISTE DES REGLES.instructions.md", section
"Table / Couche : Pêche expérimentale (PECH_EXPERI)" : la règle concerne
les champs "Date de pose du filet" (PLF_DATE_POSE) et "Date de levée du
filet" (PLF_DATE_LEVEE), qui appartiennent en réalité à la table
pose_levee_filet (enfant de peche_exper), pas à peche_exper elle-même ;
elle est donc implémentée ici plutôt que dans rules/peche_exper.py.
"""

from __future__ import annotations

import datetime as _dt

from core.models import ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind

LAYER = "pose_levee_filet"


@register(LAYER, kind=RuleKind.TRANSFORM)
def date_levee_lendemain_pose(ctx: RuleContext) -> list[ValidationIssue]:
    """Lors de la saisie de la date de pose du filet, assigne
    automatiquement la date du lendemain à la date de levée si elle est
    encore vide."""
    row = ctx.row
    date_pose = row.get("plf_date_pose")
    if date_pose and not row.get("plf_date_levee"):
        if isinstance(date_pose, str):
            date_pose = _dt.date.fromisoformat(date_pose)
        row["plf_date_levee"] = date_pose + _dt.timedelta(days=1)
    return []
