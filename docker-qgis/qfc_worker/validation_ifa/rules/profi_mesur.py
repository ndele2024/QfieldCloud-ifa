"""
Règles métier : Profil de mesures physico-chimie (table ifa_data.profi_mesur).

Source : "Règles IFA 2.0/PROFI_MESUR.groovy".

La génération de la liste de profondeurs (generer_profondeurs) est une
règle de SAISIE (elle alimente la liste de choix proposée à l'utilisateur
dans le formulaire QGIS, avant tout enregistrement) : elle n'a donc pas sa
place comme règle de VALIDATION d'un lot déjà rempli, et n'est pas
enregistrée dans le moteur. Elle est néanmoins fournie ici, telle que
spécifiée, pour :
  1. rester disponible si le formulaire QGIS a besoin de la rappeler
     (ex. expression par défaut, action de couche) ;
  2. être couverte par des tests unitaires (voir tests/test_profi_mesur.py),
     comme demandé pour l'ensemble du programme.

Règles de validation effectivement appliquées par le moteur :
  - Profondeur (pme_profd_m) obligatoire et strictement positive.
  - pH (pme_val_ph), s'il est renseigné, compris entre 5 et 8.
  - Au moins une des trois mesures Oxygène / pH / Température renseignée.
"""

from __future__ import annotations

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import at_least_one_of

LAYER = "profi_mesur"

PH_MIN, PH_MAX = 5, 8


def generer_profondeurs(profondeur_max: float | None = None) -> list[float]:
    """Génère la liste des profondeurs de mesure pour un profil
    physico-chimique selon les règles du MRNF.

    Règles :
        - 0.5 m (toujours)
        - tous les 1 m de 1 à 14 m inclusivement
        - tous les 2 m de 16 à 20 m inclusivement (pairs seulement)
        - tous les 4 m à partir de 24 m (multiples de 4)
        - jusqu'à profondeur_max inclusivement

    Args:
        profondeur_max: profondeur maximale du plan d'eau en mètres.
            Défaut : 20 m si None ou invalide.

    Returns:
        Liste ordonnée des profondeurs à mesurer.
    """
    if profondeur_max is None:
        profondeur_max = 20.0

    profondeurs = [0.5]  # Premier point fixe

    for i in range(1, int(profondeur_max) + 1):
        if i <= 14:
            profondeurs.append(float(i))
        elif i <= 20:
            if i % 2 == 0:
                profondeurs.append(float(i))
        else:
            if i % 4 == 0:
                profondeurs.append(float(i))

    return profondeurs


@register(LAYER, kind=RuleKind.VALIDATION)
def profondeur_obligatoire_positive(ctx: RuleContext) -> list[ValidationIssue]:
    """La profondeur de mesure doit être renseignée et strictement positive."""
    value = ctx.row.get("pme_profd_m")
    if value is None:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="PROFI_MESUR_PROFD_REQUISE",
            message="La profondeur (pme_profd_m) est obligatoire.",
            fields=["pme_profd_m"], record=ctx.record_key(),
        )]
    if value <= 0:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="PROFI_MESUR_PROFD_INVALIDE",
            message="La profondeur (pme_profd_m) doit être strictement positive.",
            fields=["pme_profd_m"], record=ctx.record_key(),
        )]
    return []


@register(LAYER, kind=RuleKind.VALIDATION)
def ph_dans_bornes(ctx: RuleContext) -> list[ValidationIssue]:
    """Si le pH est renseigné, sa valeur doit être comprise entre 5 et 8."""
    value = ctx.row.get("pme_val_ph")
    if value is None or PH_MIN <= value <= PH_MAX:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="PROFI_MESUR_PH_HORS_BORNES",
        message=f"Le pH mesuré ({value}) doit être compris entre {PH_MIN} et {PH_MAX}.",
        fields=["pme_val_ph"], record=ctx.record_key(),
    )]


register(LAYER, kind=RuleKind.VALIDATION)(at_least_one_of(
    ["pme_val_oxyge", "pme_val_ph", "pme_val_tempe_cel"],
    "Oxygène, pH, Température",
    code="PROFI_MESUR_AU_MOINS_UNE_MESURE_REQUISE",
))
