"""
rules.common : Fabriques de règles génériques, réutilisables sur n'importe
quelle couche.

Plutôt que de réécrire "ce champ est obligatoire" ou "ce champ doit être
inférieur à cet autre" à la main pour chaque cas (le fichier de règles
métier contient des dizaines d'occurrences de ces mêmes motifs), ce module
fournit des fonctions qui RETOURNENT une fonction-règle déjà configurée.

Exemple d'utilisation dans un fichier de règles de couche :

    from core.registry import register
    from rules.common import required_field, cross_field_lte

    register("detail_speci")(required_field(
        "dsp_no_speci", "Numéro de spécimen", code="DETAIL_SPECI_NO_SPECI_REQUIS"))

    register("detail_speci")(cross_field_lte(
        "dsp_long_fourc_mm", "dsp_long_tot_max_m",
        "La longueur à la fourche doit être inférieure à la longueur totale maximale.",
        code="DETAIL_SPECI_COHERENCE_LONGUEURS"))

Ces fabriques ne couvrent QUE les motifs qui se répètent. Une règle propre
à une seule couche et trop spécifique pour être généralisée doit être
écrite directement comme une fonction normale dans le fichier de la couche
(voir rules/analy_physi_chimi.py pour des exemples).
"""

from __future__ import annotations

from typing import Any, Iterable

from core.models import Severity, ValidationIssue
from core.rule_base import RuleContext


def _is_blank(value: Any) -> bool:
    """Une valeur est "vide" si elle est None, NaN ou une chaîne ne
    contenant que des espaces : les trois représentations possibles d'une
    cellule non renseignée selon la façon dont GeoPandas/SQLite l'a lue."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def required_field(field_name: str, label: str, code: str, *, when=None):
    """Le champ `field_name` doit être renseigné.

    Args:
        field_name: nom de la colonne.
        label: libellé humain utilisé dans le message d'erreur.
        code: code stable de la règle (apparaît dans le rapport JSON).
        when: fonction optionnelle ``ctx -> bool`` ; si fournie, la règle
            ne s'applique que lorsque `when(ctx)` est vrai (champ
            conditionnellement obligatoire).
    """
    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        if when is not None and not when(ctx):
            return []
        if _is_blank(ctx.row.get(field_name)):
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code=code,
                message=f"Le champ « {label} » est obligatoire.",
                fields=[field_name], record=ctx.record_key(),
            )]
        return []
    rule.__name__ = f"required_field_{field_name}"
    return rule


def at_least_one_of(field_names: list[str], label: str, code: str):
    """Au moins un des champs listés doit être renseigné."""
    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        if all(_is_blank(ctx.row.get(f)) for f in field_names):
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code=code,
                message=f"Au moins un des champs suivants est obligatoire : {label}.",
                fields=list(field_names), record=ctx.record_key(),
            )]
        return []
    rule.__name__ = f"at_least_one_of_{'_'.join(field_names)}"
    return rule


def forbidden_values(field_name: str, label: str, values: Iterable[str], code: str):
    """Le champ `field_name` ne doit pas contenir l'une des valeurs listées."""
    forbidden = set(values)

    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        value = ctx.row.get(field_name)
        if value in forbidden:
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code=code,
                message=f"« {label} » ne peut pas avoir la valeur Â« {value} Â».",
                fields=[field_name], record=ctx.record_key(),
            )]
        return []
    rule.__name__ = f"forbidden_values_{field_name}"
    return rule


def cross_field_lte(field_a: str, field_b: str, message: str, code: str, *, strict: bool = False):
    """Vérifie que ``row[field_a] <= row[field_b]`` (ou ``<`` si strict=True).
    Ignoré si l'un des deux champs est vide (la règle "valeur obligatoire"
    est une règle séparée : voir required_field)."""
    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        a, b = ctx.row.get(field_a), ctx.row.get(field_b)
        if _is_blank(a) or _is_blank(b):
            return []
        ok = (a < b) if strict else (a <= b)
        if not ok:
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code=code,
                message=message, fields=[field_a, field_b], record=ctx.record_key(),
            )]
        return []
    rule.__name__ = f"cross_field_lte_{field_a}_{field_b}"
    return rule


def default_if_empty(field_name: str, default_fn, *, also_check=None):
    """TRANSFORM : si `field_name` est vide, lui assigne ``default_fn(ctx)``.

    Args:
        default_fn: fonction ``ctx -> valeur``, appelée uniquement si le
            champ est vide (évite de calculer une valeur par défaut coûteuse
            inutilement).
        also_check: fonction optionnelle ``ctx -> list[ValidationIssue]``
            appelée APRÈS l'assignation (utile pour enchaîner une vérification
            de bornes une fois la valeur par défaut posée : voir
            rules/analy_physi_chimi.py, date de visite).
    """
    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        if _is_blank(ctx.row.get(field_name)):
            ctx.row[field_name] = default_fn(ctx)
        if also_check is not None:
            return also_check(ctx) or []
        return []
    rule.__name__ = f"default_if_empty_{field_name}"
    return rule


def date_within_bounds(date_field: str, lower_field: str, upper_field: str, label: str, code: str,
                        *, other_layer: str | None = None):
    """Vérifie que ``row[date_field]`` est compris entre les dates
    `lower_field`/`upper_field` d'un enregistrement d'une autre couche du
    même mesurage (ex. date de visite vs date début/fin d'inventaire de
    infor_gener). Recherche le premier enregistrement de `other_layer`
    partageant (une_code_ident, mes_no_seq) avec l'enregistrement courant.

    Si `other_layer` n'est pas fourni ou introuvable dans le lot, la règle
    ne produit aucune anomalie (on ne peut pas valider sans référence :
    une règle "required_field" séparée doit couvrir l'obligation de saisie
    de la table de référence elle-même)."""
    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        value = ctx.row.get(date_field)
        if _is_blank(value) or not other_layer:
            return []
        key = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
        ref = next(
            (r for r in ctx.other_layer(other_layer)
             if (r.get("une_code_ident"), r.get("mes_no_seq")) == key),
            None,
        )
        if ref is None:
            return []
        lower, upper = ref.get(lower_field), ref.get(upper_field)
        if not _is_blank(lower) and value < lower:
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code=code,
                message=f"{label} doit être supérieure ou égale à la date de début d'inventaire ({lower}).",
                fields=[date_field], record=ctx.record_key(),
            )]
        if not _is_blank(upper) and value > upper:
            return [ValidationIssue(
                layer=ctx.layer, severity=Severity.ERROR, code=code,
                message=f"{label} doit être inférieure ou égale à la date de fin d'inventaire ({upper}).",
                fields=[date_field], record=ctx.record_key(),
            )]
        return []
    rule.__name__ = f"date_within_bounds_{date_field}"
    return rule


def lookup_assign(source_fields: list[str], target_field: str, table: dict[tuple, str],
                   *, contains_match: bool = False):
    """TRANSFORM générique pour les règles « selon les valeurs de X et Y,
    assigner Z » (ex. Panneau du filet selon type de pêche + maille).

    Args:
        source_fields: champs formant la clé de recherche, dans l'ordre.
        target_field: champ à assigner.
        table: dict { (valeur_source_1, valeur_source_2, ...): valeur_cible }.
        contains_match: si True, la 2e clé (typiquement une maille/longueur)
            est comparée par appartenance (utile quand la donnée source est
            une liste de tailles possibles plutôt qu'une valeur unique) :
            non utilisé par défaut, prévu pour extension future.
    """
    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        key = tuple(ctx.row.get(f) for f in source_fields)
        if key in table:
            ctx.row[target_field] = table[key]
        return []
    rule.__name__ = f"lookup_assign_{target_field}"
    return rule
