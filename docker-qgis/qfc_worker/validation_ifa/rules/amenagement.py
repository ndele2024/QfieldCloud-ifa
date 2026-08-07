"""
Règles métier : Aménagement (table ifa_data.amenagement).

Source : "Règles IFA 2.0/AMENAGEMENT.groovy".

Règles couvertes :
  - Superficie (AME_SUPRF_M2) calculée = longueur x largeur.
  - Type d'activité (AAM_CODE) restreint selon le type d'aménagement
    (TAM_CODE) : voir ACTIVITES_PAR_TYPE_AMENAGEMENT.
  - Champs obligatoires : Type d'aménagement, Type d'activité, Date d'activité.
  - L'année de la date d'activité doit correspondre à l'année de la date de
    début d'inventaire de "Informations générales".

Non couvert ici :
  - "Consultation de l'historique des activités" : fenêtre de consultation
    ouverte par un bouton du formulaire QGIS, sans effet sur la validité
    d'un enregistrement déjà saisi.
"""

from __future__ import annotations

import datetime as _dt

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import required_field

LAYER = "amenagement"

TYPE_AMENAGEMENT_IP = "IP"

# Type d'aménagement -> types d'activité autorisés. Le document source
# décrit ce couple de listes comme un filtre de liste déroulante, mais la
# bipartition est explicite et exhaustive (« si IP ... sinon ... »), ce qui
# permet de la valider aussi côté données et pas seulement côté formulaire.
ACTIVITES_PAR_TYPE_AMENAGEMENT: dict[str, set[str]] = {
    TYPE_AMENAGEMENT_IP: {"C", "CC", "CNC", "CP", "CV", "DBC", "EC", "N", "NG", "RR"},
}
ACTIVITES_AUTRES_AMENAGEMENTS = {"CO", "EN", "N", "R", "V"}


def _activites_autorisees(tam_code) -> set[str]:
    return ACTIVITES_PAR_TYPE_AMENAGEMENT.get(tam_code, ACTIVITES_AUTRES_AMENAGEMENTS)


@register(LAYER, kind=RuleKind.TRANSFORM)
def superficie_calculee(ctx: RuleContext) -> list[ValidationIssue]:
    """Si longueur et largeur sont renseignées, calcule automatiquement la
    superficie (longueur x largeur)."""
    row = ctx.row
    longueur, largeur = row.get("ame_long_m"), row.get("ame_larg_m")
    if longueur is not None and largeur is not None:
        row["ame_suprf_m2"] = longueur * largeur
    return []


@register(LAYER, kind=RuleKind.VALIDATION)
def type_activite_coherent(ctx: RuleContext) -> list[ValidationIssue]:
    """Le type d'activité doit appartenir à la liste autorisée pour le type
    d'aménagement de l'enregistrement."""
    row = ctx.row
    aam_code = row.get("aam_code")
    if aam_code in (None, ""):
        return []  # obligation de saisie couverte séparément par required_field

    autorisees = _activites_autorisees(row.get("tam_code"))
    if aam_code in autorisees:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="AMENAGEMENT_TYPE_ACTIVITE_INVALIDE",
        message=(
            f"Le type d'activité « {aam_code} » n'est pas autorisé pour le type d'aménagement "
            f"« {row.get('tam_code')} » (valeurs attendues : {', '.join(sorted(autorisees))})."
        ),
        fields=["aam_code", "tam_code"], record=ctx.record_key(),
    )]


def _annee(valeur) -> int | None:
    """Extrait l'année d'une date, qu'elle soit un objet date/datetime ou une
    chaîne ISO ("2024-06-01") telle que lue depuis le GeoPackage."""
    if valeur is None:
        return None
    if isinstance(valeur, (_dt.date, _dt.datetime)):
        return valeur.year
    try:
        return _dt.date.fromisoformat(str(valeur)[:10]).year
    except ValueError:
        return None


@register(LAYER, kind=RuleKind.VALIDATION)
def annee_activite_coherente_avec_inventaire(ctx: RuleContext) -> list[ValidationIssue]:
    """L'année de la date d'activité doit être la même que celle de la date
    de début d'inventaire de "Informations générales" pour cet inventaire."""
    row = ctx.row
    annee_activite = _annee(row.get("ame_date_activ"))
    if annee_activite is None:
        return []  # date absente/illisible : couvert par required_field

    key = (row.get("une_code_ident"), row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    if ref is None:
        return []  # pas de référence dans le lot : rien à comparer

    annee_inventaire = _annee(ref.get("ing_date_debut_inven"))
    if annee_inventaire is None or annee_activite == annee_inventaire:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="AMENAGEMENT_ANNEE_ACTIVITE_INCOHERENTE",
        message=(
            f"L'année de la date d'activité ({annee_activite}) doit correspondre à l'année de "
            f"la date de début d'inventaire ({annee_inventaire})."
        ),
        fields=["ame_date_activ"], record=ctx.record_key(),
    )]


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
for _field, _label, _code in [
    ("tam_code", "Type d'aménagement", "AMENAGEMENT_TYPE_AMENAGEMENT_REQUIS"),
    ("aam_code", "Type d'activité", "AMENAGEMENT_TYPE_ACTIVITE_REQUIS"),
    ("ame_date_activ", "Date d'activité", "AMENAGEMENT_DATE_ACTIVITE_REQUISE"),
]:
    register(LAYER, kind=RuleKind.VALIDATION)(required_field(_field, _label, code=_code))
