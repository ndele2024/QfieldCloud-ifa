"""
Règles métier : Autres observations fauniques (table ifa_data.autre_obser_fauni).

Source : "Règles IFA 2.0/AUTRE_OBSER_FAUNI.groovy".

Non couvert ici (filtre de listes déroulantes UI, sans effet sur la
validité d'un enregistrement déjà saisi) :
  - Filtre du "Territoire faunique" selon la région administrative du projet.
  - Filtre de "Espèce visée" selon la catégorie d'espèce sélectionnée.
"""

from __future__ import annotations

from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import date_within_bounds, default_if_empty, required_field

LAYER = "autre_obser_fauni"


def _date_debut_inventaire(ctx: RuleContext):
    key = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    return ref.get("ing_date_debut_inven") if ref else None


_bornes_date_observation = date_within_bounds(
    "aof_date_obser", "ing_date_debut_inven", "ing_date_fin_inven",
    "La date de l'observation", code="AUTRE_OBSER_DATE_HORS_BORNES",
    other_layer="infor_gener",
)

register(LAYER, kind=RuleKind.TRANSFORM, order=20)(
    default_if_empty("aof_date_obser", default_fn=_date_debut_inventaire, also_check=_bornes_date_observation)
)

register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("aof_date_obser", "Date de l'observation", code="AUTRE_OBSER_DATE_REQUISE")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("efa_code", "Espèce visée", code="AUTRE_OBSER_ESPECE_REQUISE")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("cef_code", "Catégorie d'espèce", code="AUTRE_OBSER_CATEGORIE_REQUISE")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("aof_latit", "Latitude", code="AUTRE_OBSER_LATITUDE_REQUISE")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("aof_longit", "Longitude", code="AUTRE_OBSER_LONGITUDE_REQUISE")
)
