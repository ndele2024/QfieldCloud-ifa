"""
Règles métier : Informations générales (table ifa_data.infor_gener).

Source : "Règles IFA 2.0/INFOR_GENER.groovy".

Règles couvertes :
  - Territoire : si le territoire faunique vaut "LIBRE" (Territoire Libre),
    le champ texte "Territoire" (ing_nom_terri) doit valoir "Territoire Libre".
  - No du plan d'eau officiel (ing_no_plan_eau_offic) : vérifié contre les
    fichiers de référence lac_LCE.txt (numéros à 5 caractères) et
    cours_eau_LCE.txt (8 caractères) ; recopie Superficie/Profondeur
    max/Altitude/Périmètre depuis le fichier trouvé, uniquement si le champ
    correspondant est encore vide (voir no_plan_eau_officiel_verifie_et_recopie).
  - Nom du plan d'eau (affichage) (ing_nom_plan_eau_affic) : rempli
    automatiquement depuis le nom officiel, sinon depuis le nom régional.
  - Au moins une coordonnée du plan d'eau doit être saisie (BD LCE ou
    centre du plan d'eau).
  - Indicateur allopatrie ('oui') implique indicateur lac/cours d'eau sans
    poisson = 'non'.
  - Date de début d'inventaire <= date de fin d'inventaire.
  - Champs obligatoires : date de début/fin d'inventaire, type de plan
    d'eau (tpl_code), No du plan d'eau officiel OU régional.

Remarque de conception : la liste "variables obligatoires" du document
source inclut aussi Latitude/Longitude du centre du plan d'eau
(ing_latit_centr / ing_longi_centr). On ne les enregistre PAS séparément
comme required_field inconditionnel : le document décrit juste avant une
règle plus nuancée ("au moins une coordonnées saisie" ci-dessus) qui les
rend obligatoires seulement en l'absence de coordonnées BD LCE — les
traiter aussi comme inconditionnellement obligatoires contredirait cette
règle. C'est donc uniquement la règle "au moins une coordonnée" qui les
couvre ici.

Non couvert ici (filtre de liste déroulante UI, sans effet sur la validité
d'un enregistrement déjà saisi) :
  - Filtre du "Territoire faunique" selon la région administrative du projet.
  - Désactivation du champ "Territoire faunique" de la couche Habitat si le
    type de plan d'eau vaut "L" (lac) — décrit ici mais concerne le
    formulaire de la couche Habitat, pas la validité d'un enregistrement
    infor_gener (voir aussi rules/habitat.py).
"""

from __future__ import annotations

import csv
from functools import lru_cache

import config
from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import at_least_one_of, cross_field_lte, required_field

LAYER = "infor_gener"

TERRITOIRE_LIBRE_CODE = "LIBRE"
TERRITOIRE_LIBRE_LIBELLE = "Territoire Libre"


@register(LAYER, kind=RuleKind.VALIDATION)
def territoire_libre_coherent(ctx: RuleContext) -> list[ValidationIssue]:
    """Si le territoire faunique est "LIBRE", le champ libre "Territoire"
    doit explicitement valoir "Territoire Libre"."""
    row = ctx.row
    if row.get("ing_nom_terri_fauni") == TERRITOIRE_LIBRE_CODE and row.get("ing_nom_terri") != TERRITOIRE_LIBRE_LIBELLE:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="INFOR_GENER_TERRITOIRE_LIBRE_INCOHERENT",
            message=(
                f"Le territoire faunique est « {TERRITOIRE_LIBRE_CODE} » : "
                f"le champ « Territoire » doit valoir « {TERRITOIRE_LIBRE_LIBELLE} »."
            ),
            fields=["ing_nom_terri_fauni", "ing_nom_terri"], record=ctx.record_key(),
        )]
    return []


# ---------------------------------------------------------------------------
# No du plan d'eau officiel : vérification + recopie depuis lac_LCE.txt /
# cours_eau_LCE.txt.
# ---------------------------------------------------------------------------

# { champ source du fichier LCE : champ cible dans infor_gener }
# (Superficie, Profondeur max, Altitude, Périmètre : les seuls champs que le
# document source décrit explicitement comme "recopiés".)
_CHAMPS_LCE_A_RECOPIER = [
    ("SUPER_HA", "ing_suprf_plan_eau_m"),
    ("PROF_MAX_M", "ing_profd_max_m"),
    ("ALTITUDE_M", "ing_altit_plan_m"),
    ("PERIM_KM", "ing_val_perim_plan_km"),
]

# Valeurs sentinelles du fichier LCE signifiant "donnée absente" : le champ
# cible correspondant doit rester vide plutôt que de recevoir -99/-999.
_VALEURS_LCE_VIDES = {"", "-99", "-999"}


@lru_cache(maxsize=None)
def _load_lce_index(path: str) -> dict[str, dict[str, str]]:
    """Charge un fichier de référence LCE (TSV, encodage UTF-8 avec BOM) en
    un index { numéro : ligne }. Mis en cache par chemin de fichier : le
    fichier ne change pas pendant l'exécution du programme, pas besoin de le
    relire à chaque enregistrement."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            key_field = reader.fieldnames[0]  # NO_L_LCE ou NO_CE_LCE selon le fichier
            return {
                row[key_field].strip(): row
                for row in reader
                if row.get(key_field, "").strip()
            }
    except FileNotFoundError:
        return {}


def _lce_reference(numero: str) -> dict[str, str] | None:
    """Cherche `numero` dans le fichier LCE approprié selon sa longueur
    (5 caractères -> lac, 8 caractères -> cours d'eau). Retourne None si la
    longueur ne correspond à aucun des deux formats, ou si le numéro est
    introuvable dans le fichier concerné."""
    if len(numero) == 5:
        return _load_lce_index(config.LAC_LCE_PATH).get(numero)
    if len(numero) == 8:
        return _load_lce_index(config.COURS_EAU_LCE_PATH).get(numero)
    return None


@register(LAYER, kind=RuleKind.TRANSFORM)
def no_plan_eau_officiel_verifie_et_recopie(ctx: RuleContext) -> list[ValidationIssue]:
    """À la saisie du "No du plan d'eau officiel" (ing_no_plan_eau_offic),
    vérifie son existence dans lac_LCE.txt ou cours_eau_LCE.txt (selon la
    longueur du numéro), puis recopie Superficie/Profondeur max/Altitude/
    Périmètre depuis le fichier trouvé — uniquement pour les champs encore
    vides (une valeur déjà saisie n'est jamais écrasée), et en laissant vide
    tout champ dont la valeur LCE est -99 ou -999 (donnée absente)."""
    row = ctx.row
    numero = row.get("ing_no_plan_eau_offic")
    if numero is None or not str(numero).strip():
        return []  # champ vide : couvert séparément par at_least_one_of
    numero = str(numero).strip()

    ref = _lce_reference(numero)
    if ref is None:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="INFOR_GENER_NO_PLAN_EAU_OFFICIEL_INTROUVABLE",
            message=(
                f"Le « No du plan d'eau officiel » « {numero} » est introuvable dans les fichiers "
                "de référence lac_LCE.txt / cours_eau_LCE.txt."
            ),
            fields=["ing_no_plan_eau_offic"], record=ctx.record_key(),
        )]

    for champ_source, champ_cible in _CHAMPS_LCE_A_RECOPIER:
        if row.get(champ_cible) not in (None, ""):
            continue  # déjà saisi : ne pas écraser
        valeur = ref.get(champ_source, "").strip()
        if valeur in _VALEURS_LCE_VIDES:
            continue  # donnée absente dans le fichier LCE : laisser vide
        try:
            row[champ_cible] = float(valeur)
        except ValueError:
            continue
    return []


# ---------------------------------------------------------------------------
# Nom du plan d'eau (affichage)
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.TRANSFORM)
def nom_plan_eau_affichage(ctx: RuleContext) -> list:
    """Si le nom officiel du plan d'eau est saisi, l'utiliser comme nom
    d'affichage ; sinon, utiliser le nom régional s'il est saisi."""
    row = ctx.row
    if row.get("ing_nom_plan_eau_offic"):
        row["ing_nom_plan_eau_affic"] = row["ing_nom_plan_eau_offic"]
    elif row.get("ing_nom_plan_eau"):
        row["ing_nom_plan_eau_affic"] = row["ing_nom_plan_eau"]
    return []


# ---------------------------------------------------------------------------
# Au moins une coordonnée saisie (BD LCE ou centre du plan d'eau)
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(at_least_one_of(
    ["ing_latit_bd_lce", "ing_longi_bd_lce", "ing_latit_centr", "ing_longi_centr"],
    "Latitude/Longitude BD LCE ou Latitude/Longitude du centre du plan d'eau",
    code="INFOR_GENER_COORDONNEES_REQUISES",
))


# ---------------------------------------------------------------------------
# Indicateur allopatrie vs indicateur lac/cours d'eau sans poisson
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.VALIDATION)
def allopatrie_coherent_sans_poisson(ctx: RuleContext) -> list[ValidationIssue]:
    """Si l'indicateur d'allopatrie vaut 'oui', l'indicateur de lac/cours
    d'eau sans poisson doit valoir 'non'."""
    row = ctx.row
    if row.get("ing_ind_allop") == "oui" and row.get("ing_ind_lac_sans_poiss") != "non":
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="INFOR_GENER_ALLOPATRIE_INCOHERENTE",
            message=(
                "Lorsque l'indicateur d'allopatrie vaut « oui », l'indicateur de lac ou cours "
                "d'eau sans poisson doit valoir « non »."
            ),
            fields=["ing_ind_allop", "ing_ind_lac_sans_poiss"], record=ctx.record_key(),
        )]
    return []


# ---------------------------------------------------------------------------
# Date de début d'inventaire <= date de fin d'inventaire
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(cross_field_lte(
    "ing_date_debut_inven", "ing_date_fin_inven",
    "La date de début de l'inventaire doit être inférieure ou égale à la date de fin de l'inventaire.",
    code="INFOR_GENER_DATES_INVENTAIRE_INCOHERENTES",
))


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("ing_date_debut_inven", "Date de début de l'inventaire",
                    code="INFOR_GENER_DATE_DEBUT_INVEN_REQUISE")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("ing_date_fin_inven", "Date de fin de l'inventaire",
                    code="INFOR_GENER_DATE_FIN_INVEN_REQUISE")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("tpl_code", "Type de plan d'eau", code="INFOR_GENER_TYPE_PLAN_EAU_REQUIS")
)
register(LAYER, kind=RuleKind.VALIDATION)(at_least_one_of(
    ["ing_no_plan_eau_offic", "ing_no_plan_eau"],
    "No du plan d'eau officiel ou No du plan d'eau régional",
    code="INFOR_GENER_NO_PLAN_EAU_REQUIS",
))
