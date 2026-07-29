"""
Règles métier : Dénombrement par espèce (table ifa_data.denom_espec).

Source : "Règles IFA 2.0/DENOM_ESPEC.groovy".

Règles couvertes :
  - Nombre capturé forcé à 0 si Espèce visée = "RIEN" (aucune espèce de poisson).
  - Longueur minimale <= longueur maximale.
  - Nombre pesé <= nombre capturé.
  - Nombre capturé obligatoire dès qu'une espèce visée est renseignée
    (différente de "RIEN") ; Nombre pesé et Masse totale s'imposent
    mutuellement (l'un saisi implique l'autre obligatoire).
  - Catégorie de dénombrement (cde_code) : valeur par défaut '-' (Aucune
    catégorie) si non saisie.
  - Nombre capturé doit être strictement supérieur à 0 pour toute espèce
    visée autre que RIEN, NILAB1, NILAB2 ou NILAB3.
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import cross_field_lte

LAYER = "denom_espec"

ESPECE_AUCUNE = "RIEN"
ESPECES_SANS_MINIMUM_CAPTURE = {"RIEN", "NILAB1", "NILAB2", "NILAB3"}


@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def nombre_capture_zero_si_aucune_espece(ctx: RuleContext) -> list[ValidationIssue]:
    """Si Espèce visée = "RIEN" (aucune espèce de poisson), force
    Nombre capturé à 0."""
    if ctx.row.get("efa_code") == ESPECE_AUCUNE:
        ctx.row["des_nb_captu"] = 0
    return []


@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def categorie_denombrement_defaut(ctx: RuleContext) -> list[ValidationIssue]:
    """Si la catégorie de dénombrement n'est pas saisie, lui assigne la
    valeur '-' (Aucune catégorie)."""
    if not ctx.row.get("cde_code"):
        ctx.row["cde_code"] = "-"
    return []


register(LAYER, kind=RuleKind.VALIDATION)(cross_field_lte(
    "des_long_min_mm", "des_long_max_mm",
    "La longueur minimale ne peut pas être supérieure à la longueur maximale.",
    code="DENOM_ESPEC_LONGUEURS_INCOHERENTES",
))

register(LAYER, kind=RuleKind.VALIDATION)(cross_field_lte(
    "des_nb_pese", "des_nb_captu",
    "Le nombre pesé ne peut pas être supérieur au nombre capturé.",
    code="DENOM_ESPEC_NB_PESE_SUPERIEUR",
))


@register(LAYER, kind=RuleKind.VALIDATION)
def champs_obligatoires_conditionnels(ctx: RuleContext) -> list[ValidationIssue]:
    row = ctx.row
    issues: list[ValidationIssue] = []

    if row.get("efa_code") and row.get("efa_code") != ESPECE_AUCUNE and row.get("des_nb_captu") is None:
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DENOM_ESPEC_NB_CAPTU_REQUIS",
            message="Le nombre capturé est obligatoire dès qu'une espèce visée est renseignée.",
            fields=["des_nb_captu"], record=ctx.record_key(),
        ))

    masse = row.get("des_val_masse_total_g")
    pese = row.get("des_nb_pese")
    if masse is not None and pese is None:
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DENOM_ESPEC_NB_PESE_REQUIS",
            message="Le nombre pesé est obligatoire dès que la masse totale est saisie.",
            fields=["des_nb_pese"], record=ctx.record_key(),
        ))
    if pese is not None and masse is None:
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DENOM_ESPEC_MASSE_REQUISE",
            message="La masse totale est obligatoire dès que le nombre pesé est saisi.",
            fields=["des_val_masse_total_g"], record=ctx.record_key(),
        ))
    return issues


@register(LAYER, kind=RuleKind.VALIDATION)
def nombre_capture_positif_si_espece_comptee(ctx: RuleContext) -> list[ValidationIssue]:
    """Pour toute espèce visée autre que RIEN/NILAB1/NILAB2/NILAB3, le
    nombre capturé doit être strictement supérieur à 0 (l'obligation de
    simple présence du champ est couverte séparément par
    champs_obligatoires_conditionnels)."""
    row = ctx.row
    efa_code = row.get("efa_code")
    if not efa_code or efa_code in ESPECES_SANS_MINIMUM_CAPTURE:
        return []

    nb_captu = row.get("des_nb_captu")
    if nb_captu is None or nb_captu > 0:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="DENOM_ESPEC_NB_CAPTU_DOIT_ETRE_POSITIF",
        message="Le nombre capturé doit être supérieur à 0 pour cette espèce.",
        fields=["des_nb_captu"], record=ctx.record_key(),
    )]
