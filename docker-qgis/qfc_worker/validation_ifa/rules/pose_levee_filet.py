"""
Règles métier : Pose et levée de filet (table ifa_data.pose_levee_filet).

Source : "Règles IFA 2.0/POSE_LEVEE_FILET.groovy".

Règles couvertes :
  - Date de levée assignée automatiquement au lendemain de la date de pose.
  - Date de pose : valeur par défaut = date de début d'inventaire de
    "Informations générales" ; doit être comprise dans la période d'inventaire.
  - Cohérence pose/levée : la pose doit précéder la levée, en départageant
    par l'heure puis par la minute à date (puis heure) égale.
  - Effort de la pêche (IFD_EFFORT) : bornes minimales selon la superficie du
    plan d'eau, pour les pêches de type "PENT" (voir SEUILS_EFFORT).
  - Champs obligatoires : Numéro pose et levée, Numéro de station, Date de
    pose, Latitude, Longitude.

Non couvert ici :
  - Filtre du "Territoire faunique" selon la région administrative du projet
    et désactivation du champ si le plan d'eau est un lac : comportements de
    liste déroulante de l'interface QGIS, sans effet sur la validité d'un
    enregistrement déjà saisi.
"""

from __future__ import annotations

import datetime as _dt

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import date_within_bounds, default_if_empty, required_field

LAYER = "pose_levee_filet"

TYPE_PECHE_FILET_EXPERIMENTAL = "PENT"

# Superficie du plan d'eau (ha) -> (effort minimal, effort maximal ou None).
# Lu comme : « superficie <= borne » applique le seuil correspondant ; la
# dernière entrée (None) couvre toutes les superficies supérieures.
# Le premier palier est STRICTEMENT supérieur à 5 ; les suivants sont des
# minimums inclusifs (voir POSE_LEVEE_FILET.groovy).
SEUILS_EFFORT: list[tuple[float | None, float, float | None, bool]] = [
    # (superficie max, effort min, effort max, minimum strict ?)
    (150, 5, None, True),
    (300, 8, None, False),
    (1000, 10, None, False),
    (5000, 10, 50, False),
    (None, 50, None, False),
]


@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
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


def _date_debut_inventaire(ctx: RuleContext):
    key = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    return ref.get("ing_date_debut_inven") if ref else None


_bornes_date_pose = date_within_bounds(
    "plf_date_pose", "ing_date_debut_inven", "ing_date_fin_inven",
    "La date de pose du filet", code="POSE_LEVEE_DATE_POSE_HORS_BORNES",
    other_layer="infor_gener",
)

# order=5 : la date de pose doit être posée AVANT date_levee_lendemain_pose
# (order=10), qui en dérive la date de levée.
register(LAYER, kind=RuleKind.TRANSFORM, order=5)(
    default_if_empty("plf_date_pose", default_fn=_date_debut_inventaire,
                      also_check=_bornes_date_pose)
)


@register(LAYER, kind=RuleKind.VALIDATION)
def pose_avant_levee(ctx: RuleContext) -> list[ValidationIssue]:
    """La date de pose doit être antérieure à la date de levée. À date
    égale, l'heure de pose doit être inférieure à l'heure de levée ; à heure
    égale, la minute de pose doit être inférieure à la minute de levée."""
    row = ctx.row
    date_pose, date_levee = row.get("plf_date_pose"), row.get("plf_date_levee")
    if date_pose is None or date_levee is None:
        return []

    if date_pose != date_levee:
        if date_pose < date_levee:
            return []
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="POSE_LEVEE_DATES_INCOHERENTES",
            message="La date de pose du filet doit être antérieure à la date de levée.",
            fields=["plf_date_pose", "plf_date_levee"], record=ctx.record_key(),
        )]

    heure_pose, heure_levee = row.get("plf_val_hre_pose"), row.get("plf_val_hre_levee")
    if heure_pose is None or heure_levee is None:
        return []
    if heure_pose != heure_levee:
        if heure_pose < heure_levee:
            return []
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="POSE_LEVEE_HEURES_INCOHERENTES",
            message=(
                "À date de pose et de levée identiques, l'heure de pose doit être inférieure "
                "à l'heure de levée."
            ),
            fields=["plf_val_hre_pose", "plf_val_hre_levee"], record=ctx.record_key(),
        )]

    minute_pose, minute_levee = row.get("plf_val_mi_pose"), row.get("plf_val_mi_levee")
    if minute_pose is None or minute_levee is None:
        return []
    if minute_pose < minute_levee:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="POSE_LEVEE_MINUTES_INCOHERENTES",
        message=(
            "À date et heure de pose et de levée identiques, la minute de pose doit être "
            "inférieure à la minute de levée."
        ),
        fields=["plf_val_mi_pose", "plf_val_mi_levee"], record=ctx.record_key(),
    )]


def _bornes_effort(superficie: float) -> tuple[float, float | None, bool]:
    """(effort minimal, effort maximal ou None, minimum strict ?) applicable
    à une superficie de plan d'eau donnée."""
    for superficie_max, effort_min, effort_max, strict in SEUILS_EFFORT:
        if superficie_max is None or superficie <= superficie_max:
            return effort_min, effort_max, strict
    raise AssertionError("SEUILS_EFFORT doit se terminer par une borne ouverte (None).")


@register(LAYER, kind=RuleKind.VALIDATION)
def effort_peche_coherent(ctx: RuleContext) -> list[ValidationIssue]:
    """Pour une pêche de type "PENT", l'effort de pêche doit respecter un
    minimum (et parfois un maximum) fonction de la superficie du plan d'eau
    de "Informations générales"."""
    row = ctx.row
    effort = row.get("ifd_effort")
    if effort is None:
        return []

    key3 = (row.get("une_code_ident"), row.get("mes_no_seq"), row.get("pex_no_peche"))
    peche = next(
        (p for p in ctx.other_layer("peche_exper")
         if (p.get("une_code_ident"), p.get("mes_no_seq"), p.get("pex_no_peche")) == key3),
        None,
    )
    if peche is None or peche.get("tpc_code") != TYPE_PECHE_FILET_EXPERIMENTAL:
        return []

    key2 = (row.get("une_code_ident"), row.get("mes_no_seq"))
    infos = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key2),
        None,
    )
    superficie = infos.get("ing_suprf_plan_eau_m") if infos else None
    if superficie is None:
        return []

    effort_min, effort_max, strict = _bornes_effort(superficie)
    trop_faible = effort <= effort_min if strict else effort < effort_min
    if trop_faible:
        comparaison = "strictement supérieur" if strict else "supérieur ou égal"
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="POSE_LEVEE_EFFORT_INSUFFISANT",
            message=(
                f"Pour une superficie de plan d'eau de {superficie} ha, l'effort de pêche "
                f"({effort}) doit être {comparaison} à {effort_min}."
            ),
            fields=["ifd_effort"], record=ctx.record_key(),
        )]
    if effort_max is not None and effort > effort_max:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="POSE_LEVEE_EFFORT_EXCESSIF",
            message=(
                f"Pour une superficie de plan d'eau de {superficie} ha, l'effort de pêche "
                f"({effort}) doit être compris entre {effort_min} et {effort_max}."
            ),
            fields=["ifd_effort"], record=ctx.record_key(),
        )]
    return []


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
for _field, _label, _code in [
    ("plf_no_pose_levee", "Numéro pose et levée", "POSE_LEVEE_NO_POSE_LEVEE_REQUIS"),
    ("plf_no_stati", "Numéro de station", "POSE_LEVEE_NO_STATION_REQUIS"),
    ("plf_date_pose", "Date de pose du filet", "POSE_LEVEE_DATE_POSE_REQUISE"),
    ("plf_latit", "Latitude", "POSE_LEVEE_LATITUDE_REQUISE"),
    ("plf_longi", "Longitude", "POSE_LEVEE_LONGITUDE_REQUISE"),
]:
    register(LAYER, kind=RuleKind.VALIDATION)(required_field(_field, _label, code=_code))
