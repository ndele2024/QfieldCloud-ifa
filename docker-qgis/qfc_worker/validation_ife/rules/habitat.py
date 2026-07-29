"""
Règles métier : Habitat (table ifa_data.habitat).

Source : "Règles IFA 2.0/Habitat.groovy".

Règles couvertes :
  - Profondeur de la prise de données de vitesse du courant (HAB_PRFD_VITES_COURA) :
    valeur par défaut 0 si la vitesse du courant (HAB_VAL_VITES_COURA) est
    mesurée sans que la profondeur associée le soit.
  - Date d'observation (HAB_DATE_OBSER) : valeur par défaut = date de début
    d'inventaire de "Informations générales" ; doit être comprise dans la
    période d'inventaire (bornée par date de début/fin).
  - Superficie (HAB_SUPRF_M2) : calculée automatiquement = longueur x largeur
    (HAB_LONG_M x HAB_LARG_M) ; doit rester inférieure ou égale à la
    superficie du plan d'eau, en ha, de "Informations générales"
    (ING_SUPRF_PLAN_EAU_M).
  - Commentaires (HAB_COM) obligatoires si Type d'habitat (TYH_CODE) = "AU" (Autre).
  - Champs obligatoires : No (HAB_NO), Date d'observation (HAB_DATE_OBSER),
    Type d'habitat (TYH_CODE), Latitude (HAB_LATIT), Longitude (HAB_LONGI).
  - Cohérence des coordonnées selon le Type de coordonnées projetées (TCP_CODE) :
      * projection plane (MTM_NAD27/83, UTM_ABREGE, UTM_NAD27/83) : Zone
        (ZON_CODE), Coordonnées X et Y (HAB_VAL_COORD_X/Y) requises, bornées
        selon le système de projection (MTM ou UTM) ;
      * projection géographique (GEO_NAD27/83) : Latitude/Longitude DDMMSS.déc
        (HAB_LATIT_DMS/HAB_LONGI_DMS) requises, et Zone/Coordonnées X/Y ne
        doivent PAS être renseignées.

Non couvert ici (filtre de liste déroulante UI, sans effet sur la validité
d'un enregistrement déjà saisi) :
  - Filtre du "Territoire faunique" selon la région administrative du projet.
  - Désactivation du champ "Territoire faunique" si le plan d'eau est un lac.
  - Filtre de la liste "Zone" (MTM / UTM / UTM abrégé) selon le type de
    coordonnées projetées choisi.
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import date_within_bounds, default_if_empty, required_field

LAYER = "habitat"

PROJECTIONS_MTM = {"MTM_NAD27", "MTM_NAD83"}
PROJECTIONS_UTM = {"UTM_ABREGE", "UTM_NAD27", "UTM_NAD83"}
PROJECTIONS_PLANES = PROJECTIONS_MTM | PROJECTIONS_UTM
PROJECTIONS_GEO = {"GEO_NAD27", "GEO_NAD83"}


# ---------------------------------------------------------------------------
# Profondeur de la prise de données de vitesse du courant
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.TRANSFORM)
def profondeur_donnee_courant_defaut(ctx: RuleContext) -> list:
    """Si la vitesse du courant est saisie mais pas la profondeur à
    laquelle elle a été mesurée, assigne 0 à cette dernière."""
    row = ctx.row
    if row.get("hab_val_vites_coura") is not None and row.get("hab_prfd_vites_coura") is None:
        row["hab_prfd_vites_coura"] = 0
    return []


# ---------------------------------------------------------------------------
# Date d'observation : valeur par défaut + cohérence avec la période d'inventaire
# ---------------------------------------------------------------------------
def _date_debut_inventaire(ctx: RuleContext):
    key = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    return ref.get("ing_date_debut_inven") if ref else None


_bornes_date_observation = date_within_bounds(
    "hab_date_obser", "ing_date_debut_inven", "ing_date_fin_inven",
    "La date d'observation", code="HABITAT_DATE_OBSER_HORS_BORNES",
    other_layer="infor_gener",
)

register(LAYER, kind=RuleKind.TRANSFORM, order=20)(
    default_if_empty("hab_date_obser", default_fn=_date_debut_inventaire,
                      also_check=_bornes_date_observation)
)

register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("hab_date_obser", "Date d'observation", code="HABITAT_DATE_OBSER_REQUISE")
)


# ---------------------------------------------------------------------------
# Superficie : calcul automatique + cohérence avec la superficie du plan d'eau
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.TRANSFORM)
def superficie_calculee(ctx: RuleContext) -> list:
    """Si longueur et largeur sont saisies, calcule automatiquement la
    superficie (longueur x largeur)."""
    row = ctx.row
    longueur, largeur = row.get("hab_long_m"), row.get("hab_larg_m")
    if longueur is not None and largeur is not None:
        row["hab_suprf_m2"] = longueur * largeur
    return []


@register(LAYER, kind=RuleKind.VALIDATION)
def superficie_inferieure_ou_egale_plan_eau(ctx: RuleContext) -> list[ValidationIssue]:
    """La superficie de l'habitat (HAB_SUPRF_M2, convertie en ha) doit être
    inférieure ou égale à la superficie du plan d'eau, en ha, de
    "Informations générales" (ING_SUPRF_PLAN_EAU_M)."""
    row = ctx.row
    suprf_m2 = row.get("hab_suprf_m2")
    if suprf_m2 is None:
        return []

    key = (row.get("une_code_ident"), row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    suprf_plan_eau_ha = ref.get("ing_suprf_plan_eau_m") if ref else None
    if suprf_plan_eau_ha is None:
        return []

    if suprf_m2 / 10000 > suprf_plan_eau_ha:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="HABITAT_SUPERFICIE_SUPERIEURE_PLAN_EAU",
            message=(
                f"La superficie de l'habitat ({suprf_m2} m², soit {suprf_m2 / 10000} ha) doit être "
                f"inférieure ou égale à la superficie du plan d'eau ({suprf_plan_eau_ha} ha)."
            ),
            fields=["hab_suprf_m2"], record=ctx.record_key(),
        )]
    return []


# ---------------------------------------------------------------------------
# Commentaires obligatoires si Type d'habitat = "Autre"
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field(
        "hab_com", "Commentaires", code="HABITAT_COMMENTAIRES_REQUIS_SI_AUTRE",
        when=lambda ctx: ctx.row.get("tyh_code") == "AU",
    )
)


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(required_field("hab_no", "No", code="HABITAT_NO_REQUIS"))
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("tyh_code", "Type d'habitat", code="HABITAT_TYPE_HABITAT_REQUIS")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("hab_latit", "Latitude", code="HABITAT_LATITUDE_REQUISE")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("hab_longi", "Longitude", code="HABITAT_LONGITUDE_REQUISE")
)


# ---------------------------------------------------------------------------
# Cohérence des coordonnées selon le Type de coordonnées projetées (TCP_CODE)
# ---------------------------------------------------------------------------
def _bornes_xy(tcp_code: str) -> tuple[float, float, float, float]:
    """(x_min, x_max, y_min, y_max) selon le système de projection plane."""
    if tcp_code in PROJECTIONS_MTM:
        return (185000, 425000, 4800000, 6900000)
    if tcp_code in PROJECTIONS_UTM:
        return (260000, 740000, 4960000, 7000000)
    return (0, 9999, 0, 9999)


@register(LAYER, kind=RuleKind.VALIDATION)
def coordonnees_projetees_coherence(ctx: RuleContext) -> list[ValidationIssue]:
    row = ctx.row
    tcp_code = row.get("tcp_code")
    issues: list[ValidationIssue] = []

    if tcp_code in PROJECTIONS_PLANES:
        for field, label in (
            ("zon_code", "Zone"),
            ("hab_val_coord_x", "Coordonnée X"),
            ("hab_val_coord_y", "Coordonnée Y"),
        ):
            if row.get(field) in (None, ""):
                issues.append(ValidationIssue(
                    layer=ctx.layer, severity=Severity.ERROR, code="HABITAT_COORD_PROJETEE_REQUISE",
                    message=(
                        f"Le champ « {label} » est obligatoire lorsque le type de coordonnées "
                        f"projetées est « {tcp_code} »."
                    ),
                    fields=[field], record=ctx.record_key(),
                ))

        x_min, x_max, y_min, y_max = _bornes_xy(tcp_code)
        x, y = row.get("hab_val_coord_x"), row.get("hab_val_coord_y")
        if x is not None and not (x_min <= x <= x_max):
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="HABITAT_COORD_X_HORS_BORNES",
                message=(
                    f"La coordonnée X doit être comprise entre {x_min} et {x_max} pour le type de "
                    f"coordonnées projetées « {tcp_code} »."
                ),
                fields=["hab_val_coord_x"], record=ctx.record_key(),
            ))
        if y is not None and not (y_min <= y <= y_max):
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="HABITAT_COORD_Y_HORS_BORNES",
                message=(
                    f"La coordonnée Y doit être comprise entre {y_min} et {y_max} pour le type de "
                    f"coordonnées projetées « {tcp_code} »."
                ),
                fields=["hab_val_coord_y"], record=ctx.record_key(),
            ))

    elif tcp_code in PROJECTIONS_GEO:
        for field, label in (
            ("hab_latit_dms", "Latitude (DDMMSS.déc)"),
            ("hab_longi_dms", "Longitude (DDMMSS.déc)"),
        ):
            if row.get(field) in (None, ""):
                issues.append(ValidationIssue(
                    layer=ctx.layer, severity=Severity.ERROR, code="HABITAT_COORD_DMS_REQUISE",
                    message=(
                        f"Le champ « {label} » est obligatoire lorsque le type de coordonnées "
                        f"projetées est « {tcp_code} »."
                    ),
                    fields=[field], record=ctx.record_key(),
                ))
        for field, label in (
            ("zon_code", "Zone"),
            ("hab_val_coord_x", "Coordonnée X"),
            ("hab_val_coord_y", "Coordonnée Y"),
        ):
            if row.get(field) not in (None, ""):
                issues.append(ValidationIssue(
                    layer=ctx.layer, severity=Severity.ERROR, code="HABITAT_COORD_PROJETEE_INTERDITE",
                    message=(
                        f"Le champ « {label} » ne doit pas être renseigné lorsque le type de "
                        f"coordonnées projetées est « {tcp_code} »."
                    ),
                    fields=[field], record=ctx.record_key(),
                ))

    return issues
