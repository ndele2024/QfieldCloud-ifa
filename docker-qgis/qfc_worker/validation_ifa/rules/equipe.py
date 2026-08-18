"""
Règles métier : Equipe de travail (table ifa_data.equipe).

Source : "Règles IFA 2.0/EQUIPE.groovy".

Règles couvertes :
  - Un responsable de l'équipe (EQR_CODE_RESPO) ou le nom d'un intervenant
    externe (TIE_CODE) est requis sur chaque enregistrement d'équipe.
  - Chaque mesurage doit être rattaché à au moins une équipe de travail
    (avertissement : voir equipe_validation).

Non couvert ici :
  - Filtre des intervenants et équipiers selon la région administrative du
    projet : comportement de liste déroulante de l'interface QGIS, sans effet
    sur la validité d'un enregistrement déjà saisi.
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import at_least_one_of

LAYER = "equipe"

# La règle « chaque mesurage a une équipe » est enregistrée sur la couche
# PARENTE : voir equipe_validation pour la raison.
LAYER_MESURAGE = "mesurage"

register(LAYER, kind=RuleKind.VALIDATION)(at_least_one_of(
    ["eqr_code_respo", "tie_code"],
    "responsable de l'équipe, nom de l'intervenant externe",
    code="NOM_RESPONSABLE_EQUIPE_REQUIS",
))


@register(LAYER_MESURAGE, kind=RuleKind.VALIDATION)
def equipe_validation(ctx: RuleContext) -> list[ValidationIssue]:
    """Chaque mesurage doit être rattaché à au moins une équipe de travail.

    La table equipe a pour clé (une_code_ident, mes_no_seq) : l'exigence porte
    donc sur CHAQUE mesurage, et non sur le GeoPackage pris dans son ensemble.

    Enregistrée sur la couche « mesurage » et non « equipe » : une règle
    VALIDATION est évaluée une fois par enregistrement de SA propre couche, or
    c'est précisément l'ABSENCE d'équipe qu'il faut détecter. Parcourir les
    équipes ne montrerait jamais un mesurage qui n'en a aucune ; parcourir les
    mesurages le montre toujours.

    Severity.WARNING : l'absence d'équipe est une saisie incomplète à signaler
    au technicien, pas une incohérence qui rendrait les données inexploitables.
    Elle n'empêche donc pas l'insertion du lot.
    """
    cle = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    a_une_equipe = any(
        (e.get("une_code_ident"), e.get("mes_no_seq")) == cle
        for e in ctx.other_layer(LAYER)
    )
    if a_une_equipe:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.WARNING, code="EQUIPE_AU_MOINS_UN_ENREGISTEMENT",
        message=(
            "Ce mesurage n'est rattaché à aucune équipe de travail : au moins un "
            f"enregistrement de la couche/table « {LAYER} » est attendu."
        ),
        fields=[], record=ctx.record_key(),
    )]
