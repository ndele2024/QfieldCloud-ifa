"""
core.rule_base — Définit ce qu'EST une règle et le contexte qu'elle reçoit.

Une règle est une simple fonction Python :

    def ma_regle(ctx: RuleContext) -> list[ValidationIssue]:
        ...

décorée avec @register("nom_de_la_table", kind=RuleKind.VALIDATION).
Voir core.registry pour le mécanisme d'enregistrement/découverte, et
rules/common.py pour des fabriques de règles génériques réutilisables.

Trois natures de règles (RuleKind) :
  - TRANSFORM  : peut MODIFIER ctx.row en place (valeurs par défaut,
                 auto-remplissage). Exécutée avant les règles VALIDATION.
                 Peut aussi retourner des avertissements (ex. "valeur
                 recalculée automatiquement").
  - VALIDATION : ne modifie rien, retourne uniquement des ValidationIssue.
                 Exécutée UNE FOIS PAR ENREGISTREMENT (voir core.engine.run) :
                 ne convient donc PAS à une vérification portant sur la
                 couche entière (ex. "au moins un enregistrement"), qui ne
                 s'exécuterait jamais pour une couche à zéro ligne. Pour ce
                 cas, utiliser RuleKind.LAYER.
  - LAYER      : ne modifie rien, retourne uniquement des ValidationIssue.
                 Exécutée UNE SEULE FOIS par couche présente dans le lot,
                 quel que soit le nombre de lignes (y compris zéro).
                 ctx.row est un dict vide (aucun enregistrement précis à
                 désigner) ; utiliser ctx.all_rows pour la vérification.

Cette séparation reflète fidèlement le fichier de règles métier
("UE IFE LISTE DES REGLES"), qui mélange systématiquement deux types de
prescriptions : "assigner automatiquement la valeur X" (transform) et
"vérifier que / interdire que" (validation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .models import LayerSchema, ValidationIssue


class RuleKind(str, Enum):
    TRANSFORM = "transform"
    VALIDATION = "validation"
    LAYER = "layer"


@dataclass
class RuleContext:
    """Tout ce dont une règle a besoin pour examiner/corriger UN enregistrement.

    Attributes:
        layer: nom de la couche/table en cours de traitement.
        row: l'enregistrement courant (dict mutable — une TRANSFORM peut
            le modifier directement, ex. ``ctx.row["phc_code_appar"] = "AUTRE"``).
        all_rows: tous les enregistrements de LA MÊME couche dans le lot
            (utile pour les règles inter-enregistrements, ex. numérotation
            automatique, détection de doublons).
        layers: tous les enregistrements de TOUTES les couches du lot,
            sous la forme { nom_couche: [rows...] } — utile pour les règles
            inter-tables (ex. comparer une date à infor_gener).
        schemas: métadonnées PostgreSQL par table ({ nom_table: LayerSchema }),
            pour éviter de dupliquer en Python des informations qui
            existent déjà côté base (listes ENUM, colonnes obligatoires...).
    """
    layer: str
    row: dict[str, Any]
    all_rows: list[dict[str, Any]]
    layers: dict[str, list[dict[str, Any]]]
    schemas: dict[str, LayerSchema] = field(default_factory=dict)

    def other_layer(self, name: str) -> list[dict[str, Any]]:
        """Retourne les enregistrements d'une autre couche du même lot
        (liste vide si la couche est absente du GeoPackage traité)."""
        return self.layers.get(name, [])

    def record_key(self, key_fields: list[str] | None = None) -> dict[str, Any]:
        """Construit la clé métier de ctx.row pour l'identifier dans le
        rapport d'erreurs. Si key_fields n'est pas fourni, utilise la clé
        primaire connue du schéma (si disponible), sinon les deux champs
        communs à toute la hiérarchie IPE (une_code_ident, mes_no_seq)."""
        schema = self.schemas.get(self.layer)
        fields_to_use = key_fields or (schema.primary_key if schema else None) \
            or ["une_code_ident", "mes_no_seq"]
        return {f: self.row.get(f) for f in fields_to_use if f in self.row}


RuleFunc = Callable[[RuleContext], "list[ValidationIssue] | None"]


@dataclass
class Rule:
    """Une règle enregistrée : la fonction + ses métadonnées de tri/affichage."""
    layer: str
    name: str
    kind: RuleKind
    fn: RuleFunc
    order: int = 100
    """Ordre d'exécution relatif parmi les règles de même kind/couche
    (croissant). À utiliser uniquement si une règle dépend du résultat
    d'une autre (ex. un transform qui doit s'exécuter avant un autre)."""

    def run(self, ctx: RuleContext) -> list[ValidationIssue]:
        result = self.fn(ctx)
        return list(result) if result else []
