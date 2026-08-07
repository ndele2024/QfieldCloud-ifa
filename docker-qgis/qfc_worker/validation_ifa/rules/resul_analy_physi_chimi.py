"""
Règles métier : Résultat d'analyse physico-chimique
(table ifa_data.resul_analy_physi_chimi).

Source : "Règles IFA 2.0/RESUL_ANALY_PHYSI_CHIMI.groovy".

Règles couvertes :
  - Appareil / Autre appareil et Laboratoire / Autre laboratoire :
    auto-remplissage de la valeur générique "AUTRE" et exigence de
    description associée.
  - Indicateur d'analyse en laboratoire mis à "OUI" dès qu'un numéro
    d'échantillon laboratoire est saisi.
  - Commentaires obligatoires si le paramètre physico-chimique vaut "AU".
  - Paramètre "TR" (transparence) : la profondeur de prise de l'échantillon
    est reportée dans le résultat, puis vidée ; le résultat doit rester
    inférieur ou égal à la profondeur maximale du plan d'eau.
  - Profondeur 2 : valeurs par défaut selon le paramètre (voir
    profondeurs_defaut).
  - Paramètre "TI" (teinte) : résultat et teinte de l'eau mutuellement
    exclusifs.
  - Unicité du tuple (station, date, profondeur, paramètre) et unicité du
    numéro d'échantillon laboratoire.
  - Date de prise de l'échantillon comprise dans la période d'inventaire.
  - Cohérence du pH (entre 5 et 8) et des profondeurs (profondeur <= profondeur 2).
  - Champs obligatoires, dont ceux conditionnés par l'indicateur d'analyse
    en laboratoire.
"""

from __future__ import annotations

from collections import defaultdict

from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind
from rules.common import cross_field_lte, date_within_bounds, required_field

LAYER = "resul_analy_physi_chimi"

VALEUR_AUTRE = "AUTRE"
PARAMETRE_AUTRE = "AU"
PARAMETRE_TRANSPARENCE = "TR"
PARAMETRE_TEINTE = "TI"
PARAMETRE_COULEUR_DISSOUTE = "CD"
PARAMETRE_PH = "PH"

PH_MIN, PH_MAX = 5, 8

# Valeurs par défaut de profondeur pour le paramètre "CD" lorsque ni la
# profondeur de prise ni la profondeur 2 ne sont renseignées.
PROFONDEUR_CD_DEFAUT = 0
PROFONDEUR_2_CD_DEFAUT = 5


# ---------------------------------------------------------------------------
# Appareil / laboratoire : auto-remplissage de la valeur générique "AUTRE"
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def appareil_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Si Appareil est vide et qu'un "Autre appareil" est saisi, assigne
    Appareil = "AUTRE" ; si la description reste vide, y inscrire "inconnu"
    (la marque, le modèle et la précision devraient y figurer)."""
    row = ctx.row
    if row.get("app_code") in (None, "") and row.get("rpc_nom_autre_appar"):
        row["app_code"] = VALEUR_AUTRE
        if not str(row.get("rpc_nom_autre_appar") or "").strip():
            row["rpc_nom_autre_appar"] = "inconnu"
    return []


@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def laboratoire_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Si Nom du laboratoire est vide et qu'un "Nom autre laboratoire" est
    saisi, assigne Nom du laboratoire = "AUTRE"."""
    row = ctx.row
    if row.get("lab_code") in (None, "") and row.get("rpc_nom_autre_labor"):
        row["lab_code"] = VALEUR_AUTRE
    return []


register(LAYER, kind=RuleKind.VALIDATION)(required_field(
    "rpc_nom_autre_labor", "Nom autre laboratoire",
    code="RESUL_ANALY_NOM_AUTRE_LABORATOIRE_REQUIS",
    when=lambda ctx: ctx.row.get("lab_code") == VALEUR_AUTRE,
))


@register(LAYER, kind=RuleKind.TRANSFORM, order=10)
def indicateur_analyse_laboratoire_autofill(ctx: RuleContext) -> list[ValidationIssue]:
    """Si un numéro d'échantillon laboratoire est saisi, l'indicateur
    d'analyse en laboratoire vaut "OUI"."""
    row = ctx.row
    if row.get("rpc_no_echan_labor"):
        row["rpc_ind_analy_labor"] = "OUI"
    return []


register(LAYER, kind=RuleKind.VALIDATION)(required_field(
    "rpc_com", "Commentaires", code="RESUL_ANALY_COMMENTAIRES_REQUIS_SI_AUTRE",
    when=lambda ctx: ctx.row.get("ppc_code") == PARAMETRE_AUTRE,
))


# ---------------------------------------------------------------------------
# Profondeurs
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.TRANSFORM, order=20)
def transparence_profondeur_vers_resultat(ctx: RuleContext) -> list[ValidationIssue]:
    """Paramètre "TR" (transparence) : la profondeur de prise de l'échantillon
    ne doit pas rester renseignée ; si elle l'est, sa valeur est reportée dans
    le résultat puis le champ profondeur est vidé."""
    row = ctx.row
    if row.get("ppc_code") == PARAMETRE_TRANSPARENCE and row.get("rpc_profd_echan_m") is not None:
        row["rpc_val_resul"] = row["rpc_profd_echan_m"]
        row["rpc_profd_echan_m"] = None
    return []


@register(LAYER, kind=RuleKind.TRANSFORM, order=30)
def profondeurs_defaut(ctx: RuleContext) -> list[ValidationIssue]:
    """Paramètre "CD" : si aucune des deux profondeurs n'est renseignée,
    assigne 0 à la profondeur de prise et 5 à la profondeur 2.
    Pour tout autre paramètre : si la profondeur de prise est renseignée et
    que la profondeur 2 ne l'est pas, recopie la première dans la seconde
    (la mesure porte alors sur une profondeur ponctuelle et non sur une
    tranche d'eau)."""
    row = ctx.row
    profd, profd_2 = row.get("rpc_profd_echan_m"), row.get("rpc_val_profd_2_m")

    if row.get("ppc_code") == PARAMETRE_COULEUR_DISSOUTE:
        if profd is None and profd_2 is None:
            row["rpc_profd_echan_m"] = PROFONDEUR_CD_DEFAUT
            row["rpc_val_profd_2_m"] = PROFONDEUR_2_CD_DEFAUT
    elif profd is not None and profd_2 is None:
        row["rpc_val_profd_2_m"] = profd
    return []


register(LAYER, kind=RuleKind.VALIDATION)(cross_field_lte(
    "rpc_profd_echan_m", "rpc_val_profd_2_m",
    "La profondeur de la prise de l'échantillon doit être inférieure ou égale à la profondeur 2.",
    code="RESUL_ANALY_PROFONDEURS_INCOHERENTES",
))


# ---------------------------------------------------------------------------
# Résultat / teinte de l'eau
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.VALIDATION)
def resultat_teinte_exclusifs(ctx: RuleContext) -> list[ValidationIssue]:
    """Paramètre "TI" (teinte) : le résultat ne doit pas être renseigné (c'est
    la teinte de l'eau qui porte la mesure). Pour tout autre paramètre, c'est
    l'inverse : la teinte de l'eau ne doit pas être renseignée.

    Seule l'exclusion mutuelle est vérifiée ici ; l'obligation de saisir l'un
    des deux dépend de l'indicateur d'analyse en laboratoire et est couverte
    par champs_obligatoires_conditionnels (la traiter aussi ici produirait
    deux anomalies contradictoires pour un même enregistrement)."""
    row = ctx.row
    if row.get("ppc_code") == PARAMETRE_TEINTE:
        if row.get("rpc_val_resul") is not None:
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_RESULTAT_INTERDIT_SI_TEINTE",
                message=(
                    f"Le résultat ne doit pas être renseigné pour le paramètre "
                    f"« {PARAMETRE_TEINTE} » : la mesure est portée par la teinte de l'eau."
                ),
                fields=["rpc_val_resul"], record=ctx.record_key(),
            )]
    elif row.get("res_code") not in (None, ""):
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_TEINTE_INTERDITE",
            message=(
                f"La teinte de l'eau ne doit être renseignée que pour le paramètre "
                f"« {PARAMETRE_TEINTE} »."
            ),
            fields=["res_code"], record=ctx.record_key(),
        )]
    return []


@register(LAYER, kind=RuleKind.VALIDATION)
def transparence_inferieure_profondeur_max(ctx: RuleContext) -> list[ValidationIssue]:
    """Paramètre "TR" : le résultat (transparence mesurée) doit rester
    inférieur ou égal à la profondeur maximale du plan d'eau de
    "Informations générales"."""
    row = ctx.row
    resultat = row.get("rpc_val_resul")
    if row.get("ppc_code") != PARAMETRE_TRANSPARENCE or resultat is None:
        return []

    key = (row.get("une_code_ident"), row.get("mes_no_seq"))
    ref = next(
        (r for r in ctx.other_layer("infor_gener")
         if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
        None,
    )
    profd_max = ref.get("ing_profd_max_m") if ref else None
    if profd_max is None or resultat <= profd_max:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_TRANSPARENCE_SUPERIEURE_PROFONDEUR_MAX",
        message=(
            f"La transparence mesurée ({resultat}) doit être inférieure ou égale à la "
            f"profondeur maximale du plan d'eau ({profd_max})."
        ),
        fields=["rpc_val_resul"], record=ctx.record_key(),
    )]


@register(LAYER, kind=RuleKind.VALIDATION)
def ph_dans_bornes(ctx: RuleContext) -> list[ValidationIssue]:
    """Paramètre "PH" : le résultat doit être compris entre 5 et 8."""
    row = ctx.row
    resultat = row.get("rpc_val_resul")
    if row.get("ppc_code") != PARAMETRE_PH or resultat is None:
        return []
    if PH_MIN <= resultat <= PH_MAX:
        return []
    return [ValidationIssue(
        layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_PH_HORS_BORNES",
        message=f"Le pH mesuré ({resultat}) doit être compris entre {PH_MIN} et {PH_MAX}.",
        fields=["rpc_val_resul"], record=ctx.record_key(),
    )]


# ---------------------------------------------------------------------------
# Date de prise de l'échantillon
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(date_within_bounds(
    "rpc_date_echan", "ing_date_debut_inven", "ing_date_fin_inven",
    "La date de prise de l'échantillon", code="RESUL_ANALY_DATE_ECHAN_HORS_BORNES",
    other_layer="infor_gener",
))


# ---------------------------------------------------------------------------
# Unicité (règles portant sur la couche entière : RuleKind.LAYER)
# ---------------------------------------------------------------------------
@register(LAYER, kind=RuleKind.LAYER)
def unicite_parametre_par_station_date_profondeur(ctx: RuleContext) -> list[ValidationIssue]:
    """Le tuple (No station, Date d'échantillon, Profondeur, Paramètre) doit
    être unique : un même paramètre ne peut pas être mesuré deux fois au même
    endroit, à la même date et à la même profondeur."""
    groupes: dict[tuple, int] = defaultdict(int)
    for row in ctx.all_rows:
        cle = (row.get("phc_no_stati"), row.get("rpc_date_echan"),
               row.get("rpc_profd_echan_m"), row.get("ppc_code"))
        groupes[cle] += 1

    return [
        ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_PARAMETRE_DUPLIQUE",
            message=(
                f"Le paramètre « {cle[3]} » est mesuré {nb} fois pour la station « {cle[0]} », "
                f"la date « {cle[1]} » et la profondeur « {cle[2]} » : cette combinaison doit être unique."
            ),
            fields=["phc_no_stati", "rpc_date_echan", "rpc_profd_echan_m", "ppc_code"],
            record={"phc_no_stati": cle[0], "rpc_date_echan": cle[1],
                    "rpc_profd_echan_m": cle[2], "ppc_code": cle[3]},
        )
        for cle, nb in groupes.items() if nb > 1
    ]


@register(LAYER, kind=RuleKind.LAYER)
def unicite_no_echantillon_laboratoire(ctx: RuleContext) -> list[ValidationIssue]:
    """Le numéro d'échantillon laboratoire doit être unique dans le lot."""
    groupes: dict[object, int] = defaultdict(int)
    for row in ctx.all_rows:
        numero = row.get("rpc_no_echan_labor")
        if numero not in (None, ""):
            groupes[numero] += 1

    return [
        ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_NO_ECHAN_LABOR_DUPLIQUE",
            message=f"Le numéro d'échantillon laboratoire « {numero} » apparaît {nb} fois : il doit être unique.",
            fields=["rpc_no_echan_labor"], record={"rpc_no_echan_labor": numero},
        )
        for numero, nb in groupes.items() if nb > 1
    ]


# ---------------------------------------------------------------------------
# Champs obligatoires
# ---------------------------------------------------------------------------
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("rpc_no", "Numéro", code="RESUL_ANALY_NO_REQUIS")
)
register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("ppc_code", "Paramètre physico-chimique", code="RESUL_ANALY_PARAMETRE_REQUIS")
)


def _est_vide(valeur) -> bool:
    return valeur is None or (isinstance(valeur, str) and not valeur.strip())


@register(LAYER, kind=RuleKind.VALIDATION)
def champs_obligatoires_conditionnels(ctx: RuleContext) -> list[ValidationIssue]:
    """Champs obligatoires dépendant de l'indicateur d'analyse en laboratoire :

      - Appareil OU Autre appareil, dans tous les cas ;
      - si l'indicateur vaut "NON" : Résultat OU Teinte de l'eau ;
      - si l'indicateur vaut "OUI" : Numéro d'échantillon laboratoire ET
        (Nom du laboratoire OU Nom autre laboratoire).
    """
    row = ctx.row
    issues: list[ValidationIssue] = []

    if _est_vide(row.get("app_code")) and _est_vide(row.get("rpc_nom_autre_appar")):
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_APPAREIL_REQUIS",
            message="L'appareil ou le nom d'un autre appareil est obligatoire.",
            fields=["app_code", "rpc_nom_autre_appar"], record=ctx.record_key(),
        ))

    indicateur = str(row.get("rpc_ind_analy_labor") or "").strip().upper()

    if indicateur == "NON" and _est_vide(row.get("rpc_val_resul")) and _est_vide(row.get("res_code")):
        issues.append(ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_RESULTAT_OU_TEINTE_REQUIS",
            message=(
                "Le résultat ou la teinte de l'eau est obligatoire lorsque l'analyse n'est pas "
                "réalisée en laboratoire."
            ),
            fields=["rpc_val_resul", "res_code"], record=ctx.record_key(),
        ))

    if indicateur == "OUI":
        if _est_vide(row.get("rpc_no_echan_labor")):
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_NO_ECHAN_LABOR_REQUIS",
                message="Le numéro d'échantillon laboratoire est obligatoire pour une analyse en laboratoire.",
                fields=["rpc_no_echan_labor"], record=ctx.record_key(),
            ))
        if _est_vide(row.get("lab_code")) and _est_vide(row.get("rpc_nom_autre_labor")):
            issues.append(ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code="RESUL_ANALY_LABORATOIRE_REQUIS",
                message=(
                    "Le nom du laboratoire ou le nom d'un autre laboratoire est obligatoire pour "
                    "une analyse en laboratoire."
                ),
                fields=["lab_code", "rpc_nom_autre_labor"], record=ctx.record_key(),
            ))
    return issues
