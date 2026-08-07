"""
Règles métier : Analyse physico-chimique (table ifa_data.analy_physi_chimi).

Source : "Règles IFA 2.0/ANALY_PHYSI_CHIMI.groovy".

Règles couvertes ici :
  - Numéro de station obligatoire.
  - Auto-remplissage de l'Appareil quand seul "Autre appareil" est saisi.
  - Appareil obligatoire dès qu'au moins un profil de mesures existe.
  - Date de visite : valeur par défaut + bornée par la période d'inventaire
    de infor_gener.

Non couvert ici (filtrage de listes déroulantes dans le formulaire QGIS,
sans effet sur la validité d'un enregistrement déjà saisi) :
  - Filtre du "Territoire faunique" selon la région administrative du projet.
  - Désactivation du champ "Territoire faunique" si le plan d'eau est un lac.
  Voir README.md, section "Règles non implémentées" pour le détail des
  raisons et la marche à suivre si elles doivent être ajoutées plus tard.
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import (
    date_within_bounds,
    default_if_empty,
    required_field,
)

LAYER = "analy_physi_chimi"


# ---------------------------------------------------------------------------
# Numéro de station : valeur obligatoire
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("phc_no_stati", "Numéro de station", code="ANALY_PHC_NO_STATI_REQUIS")
)


# ---------------------------------------------------------------------------
# Appareil / Autre appareil
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def appareil_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Si Appareil (app_code) est vide ET Autre appareil (phc_nom_autre_appar)
    est renseigné, assigne automatiquement Appareil = "AUTRE" et, si la
    description de l'autre appareil est restée vide, la remplace par
    "inconnu" (le champ ne doit jamais être vide une fois "AUTRE" choisi)."""
    row = ctx.row
    appareil_vide = row.get("app_code") in (None, "")
    autre_renseigne = bool(row.get("phc_nom_autre_appar"))

    if appareil_vide and autre_renseigne:
        row["app_code"] = "AUTRE"
        if not str(row.get("phc_nom_autre_appar") or "").strip():
            row["phc_nom_autre_appar"] = "inconnu"
    return []


@register(LAYER, kind=RuleKind.VALIDATION)
def appareil_requis_si_profil(ctx: RuleContext) -> list[ValidationIssue]:
    """Si au moins un profil de mesures (profi_mesur) est rattaché à cette
    analyse physico-chimique (même une_code_ident/mes_no_seq/phc_no_stati),
    alors Appareil (app_code) doit être renseigné."""
    row = ctx.row
    key = (row.get("une_code_ident"), row.get("mes_no_seq"), row.get("phc_no_stati"))
    has_profile = any(
        (p.get("une_code_ident"), p.get("mes_no_seq"), p.get("phc_no_stati")) == key
        for p in ctx.other_layer("profi_mesur")
    )
    if has_profile and not row.get("app_code"):
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="ANALY_APPAREIL_REQUIS_SI_PROFIL",
            message="L'appareil doit être renseigné dès qu'un profil de mesures existe pour cette station.",
            fields=["app_code"], record=ctx.record_key(),
        )]
    return []


# ---------------------------------------------------------------------------
# Date de visite de la station
# ---------------------------------------------------------------------------
def _bornes_date_visite(ctx: RuleContext) -> list[ValidationIssue]:
    rule = date_within_bounds(
        "phc_date", "ing_date_debut_inven", "ing_date_fin_inven",
        "La date de visite de la station", code="ANALY_DATE_VISITE_HORS_BORNES",
        other_layer="infor_gener",
    )
    return rule(ctx)


register(LAYER, kind=RuleKind.TRANSFORM, order=20)(
    default_if_empty(
        "phc_date",
        default_fn=lambda ctx: _date_debut_inventaire(ctx),
        also_check=_bornes_date_visite,
    )
)

register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("phc_date", "Date de visite de la station", code="ANALY_DATE_VISITE_REQUISE")
)


def _date_debut_inventaire(ctx: RuleContext):
    """Retourne ing_date_debut_inven de l'enregistrement infor_gener
    partageant la même unité d'échantillonnage/mesurage, ou None si
    introuvable (la règle "required_field" séparée signalera alors l'absence)."""
    key = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    return ref.get("ing_date_debut_inven") if ref else None
