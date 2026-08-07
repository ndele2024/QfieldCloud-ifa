"""
Règles métier : Perturbation (table ifa_data.perturbation).

Source : "Règles IFA 2.0/PERTUBATION.groovy" (le document source écrit
"PERTUBATION" ; la table et la couche du GeoPackage s'appellent bien
"perturbation", orthographe retenue ici).

Règles couvertes :
  - Date d'observation (PER_DATE_OBSER) : valeur par défaut = date de début
    d'inventaire de "Informations générales" ; doit être comprise dans la
    période d'inventaire.
  - Superficie (PER_SUPRF_M) : calculée = longueur x largeur si elle n'est
    pas renseignée.
  - Commentaire (PER_COM) obligatoire si Type de perturbation = "AU" (Autre).
  - Champs obligatoires : No perturbation, Date d'observation, Type de
    perturbation, Latitude, Longitude.

Non couvert ici :
  - "Historique des perturbations" : rapport de consultation déclenché par un
    bouton du formulaire QGIS, sans effet sur la validité d'un enregistrement.
  - Filtre du "Territoire faunique" selon la région administrative du projet
    et désactivation du champ si le plan d'eau est un lac : comportements de
    liste déroulante de l'interface QGIS.
"""

from __future__ import annotations

from core.models import ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import date_within_bounds, default_if_empty, required_field

LAYER = "perturbation"

TYPE_PERTURBATION_AUTRE = "AU"


def _date_debut_inventaire(ctx: RuleContext):
    key = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    return ref.get("ing_date_debut_inven") if ref else None


_bornes_date_observation = date_within_bounds(
    "per_date_obser", "ing_date_debut_inven", "ing_date_fin_inven",
    "La date d'observation", code="PERTURBATION_DATE_OBSER_HORS_BORNES",
    other_layer="infor_gener",
)

register(LAYER, kind=RuleKind.TRANSFORM, order=20)(
    default_if_empty("per_date_obser", default_fn=_date_debut_inventaire,
                      also_check=_bornes_date_observation)
)


@register(LAYER, kind=RuleKind.TRANSFORM)
def superficie_calculee(ctx: RuleContext) -> list[ValidationIssue]:
    """Si la superficie n'est pas renseignée et que longueur et largeur le
    sont, assigne à la superficie la valeur longueur x largeur."""
    row = ctx.row
    longueur, largeur = row.get("per_long_m"), row.get("per_larg_m")
    if row.get("per_suprf_m") is None and longueur is not None and largeur is not None:
        row["per_suprf_m"] = longueur * largeur
    return []


register(LAYER, kind=RuleKind.VALIDATION)(required_field(
    "per_com", "Commentaire", code="PERTURBATION_COMMENTAIRE_REQUIS_SI_AUTRE",
    when=lambda ctx: ctx.row.get("tpe_code") == TYPE_PERTURBATION_AUTRE,
))


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
for _field, _label, _code in [
    ("per_no_stati", "No perturbation", "PERTURBATION_NO_STATI_REQUIS"),
    ("per_date_obser", "Date d'observation", "PERTURBATION_DATE_OBSER_REQUISE"),
    ("tpe_code", "Type de perturbation", "PERTURBATION_TYPE_REQUIS"),
    ("per_latit", "Latitude", "PERTURBATION_LATITUDE_REQUISE"),
    ("per_longi", "Longitude", "PERTURBATION_LONGITUDE_REQUISE"),
]:
    register(LAYER, kind=RuleKind.VALIDATION)(required_field(_field, _label, code=_code))
