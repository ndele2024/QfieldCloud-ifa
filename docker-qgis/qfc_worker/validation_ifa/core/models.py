"""
core.models — Structures de données partagées par tout le moteur de validation.

Ce module ne contient AUCUNE logique métier : seulement les "formes" de
données échangées entre les autres modules (gpkg_reader, rules, engine,
report). Le garder minimal et stable évite de casser les règles existantes
quand on étend le moteur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Gravité d'une anomalie détectée par une règle.

    ERROR   : bloque l'insertion de TOUT le lot (voir engine.run).
    WARNING : signalée dans le rapport mais n'empêche pas l'insertion.
    """
    ERROR = "error"
    WARNING = "warning"


# Pseudo-couche portée par les anomalies qui ne concernent AUCUN
# enregistrement en particulier mais la communication avec PostgreSQL
# (connexion impossible, lecture du schéma, échec d'insertion).
#
# Les parenthèses garantissent qu'aucune vraie table ne peut porter ce nom :
# un client peut donc filtrer ces anomalies de façon fiable, et le résumé
# texte les distingue des erreurs de saisie.
LAYER_BASE_DE_DONNEES = "(base de données)"


@dataclass
class ValidationIssue:
    """Une anomalie détectée sur un enregistrement par une règle.

    Attributes:
        layer: nom de la table/couche concernée (ex. "detail_speci").
        severity: Severity.ERROR ou Severity.WARNING.
        code: identifiant court et stable de la règle (ex. "required_field",
            "ANALY_PHYSI_CHIMI_APPAREIL_AUTOFILL"). Utilisé par les tests et
            par l'UI pour grouper/filtrer les anomalies sans dépendre du texte.
        message: phrase lisible destinée à l'utilisateur final (français).
        fields: liste des champs concernés (pour mettre en évidence dans le
            formulaire QField/QGIS qui affichera le rapport).
        record: clé métier de l'enregistrement concerné, ex.
            {"une_code_ident": "...", "mes_no_seq": 1, "phc_no_stati": 2}.
            Ne PAS utiliser l'index de ligne brut : il n'a aucun sens pour
            l'utilisateur et change selon l'ordre de lecture du GeoPackage.
        rule_name: nom de la fonction Python qui a généré l'anomalie
            (utile pour déboguer une règle précise).
    """
    layer: str
    severity: Severity
    code: str
    message: str
    fields: list[str] = field(default_factory=list)
    record: dict[str, Any] = field(default_factory=dict)
    rule_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Représentation JSON-sérialisable (Severity -> str)."""
        return {
            "layer": self.layer,
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "fields": self.fields,
            "record": self.record,
            "rule_name": self.rule_name,
        }


@dataclass
class LayerSchema:
    """Métadonnées PostgreSQL d'une table, utilisées par les règles
    automatiques (core.db_schema) ET disponibles aux règles personnalisées
    via RuleContext.db_meta pour éviter de redéfinir des constantes
    (ex. valeurs ENUM, colonnes obligatoires) qui existent déjà en base.

    Attributes:
        table: nom de la table PostgreSQL.
        primary_key: colonnes formant la clé primaire (ordre des colonnes).
        not_null_columns: colonnes NOT NULL sans valeur par défaut serveur
            (les colonnes à séquence/valeur par défaut sont exclues : elles
            seront renseignées par le serveur, pas par l'utilisateur).
        numeric_ranges: { colonne: (min, max) } extrait des contraintes CHECK
            "col >= a AND col <= b" (None pour une borne non contrainte).
        enum_values: { colonne: {valeurs autorisées} } pour les colonnes de
            type ENUM PostgreSQL.
    """
    table: str
    primary_key: list[str] = field(default_factory=list)
    not_null_columns: list[str] = field(default_factory=list)
    numeric_ranges: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    enum_values: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Rapport final produit par le moteur pour un lot (un GeoPackage).

    Attributes:
        source: chemin du GeoPackage validé.
        layers_processed: liste des couches effectivement présentes et traitées.
        record_counts: { couche: nombre d'enregistrements lus }.
        issues: toutes les anomalies (erreurs + avertissements), tous calques confondus.
        inserted: True si les données ont été insérées en base (donc aucune
            erreur bloquante n'a été trouvée — des avertissements peuvent
            néanmoins être présents).
    """
    source: str
    layers_processed: list[str] = field(default_factory=list)
    record_counts: dict[str, int] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)
    inserted: bool = False

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        """Aucune erreur bloquante (des avertissements peuvent subsister)."""
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "layers_processed": self.layers_processed,
            "record_counts": self.record_counts,
            "is_valid": self.is_valid,
            "inserted": self.inserted,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
        }
