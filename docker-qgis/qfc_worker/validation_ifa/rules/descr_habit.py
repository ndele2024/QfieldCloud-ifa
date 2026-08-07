"""
Règles métier : Description de l'habitat (table ifa_data.descr_habit).

Source : "Règles IFA 2.0/DESCR_HABIT.groovy".

Non couvert ici (filtre de liste déroulante UI, désactivation conditionnelle
d'un champ : sans effet sur la validité d'un enregistrement déjà saisi) :
  - Filtre du "Territoire faunique" selon la région administrative du projet.
  - Désactivation du champ "Territoire faunique" si le plan d'eau est un lac.
"""

from __future__ import annotations

from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import default_if_empty, required_field

LAYER = "descr_habit"


def _date_debut_inventaire(ctx: RuleContext):
    key = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    return ref.get("ing_date_debut_inven") if ref else None


register(LAYER, kind=RuleKind.TRANSFORM, order=20)(
    default_if_empty("dha_date", default_fn=_date_debut_inventaire)
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("dha_date", "Date", code="DESCR_HABIT_DATE_REQUISE")
)


@register(LAYER, kind=RuleKind.TRANSFORM)
def profondeur_donnee_courant_defaut(ctx: RuleContext) -> list:
    """Si la vitesse du courant est saisie mais pas la profondeur à
    laquelle elle a été mesurée, assigne 0 à cette dernière."""
    row = ctx.row
    if row.get("dha_val_vites_coura") is not None and row.get("dha_prfd_vites_coura") is None:
        row["dha_prfd_vites_coura"] = 0
    return []


@register(LAYER, kind=RuleKind.TRANSFORM)
def superficie_calculee(ctx: RuleContext) -> list:
    """Si longueur et largeur sont saisies, calcule automatiquement la
    superficie (longueur x largeur)."""
    row = ctx.row
    longueur, largeur = row.get("dha_long"), row.get("dha_larg")
    if longueur is not None and largeur is not None:
        row["dha_suprf"] = longueur * largeur
    return []
