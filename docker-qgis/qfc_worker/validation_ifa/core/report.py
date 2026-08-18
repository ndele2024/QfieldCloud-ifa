"""
core.report — Construction et sérialisation du rapport JSON destiné à
l'utilisateur final (affiché dans QField/QFieldCloud après une tentative
d'envoi de données).

Le format est volontairement simple et plat (voir ValidationReport.to_dict
dans core.models) pour être facile à consommer par n'importe quel client
(JavaScript, QML/QField, etc.) sans bibliothèque de désérialisation complexe.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import LAYER_BASE_DE_DONNEES, ValidationReport


def save_report(report: ValidationReport, path: str | Path) -> None:
    """Écrit le rapport au format JSON (UTF-8, indenté pour la lisibilité
    humaine en cas de consultation directe du fichier)."""
    Path(path).write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def erreurs_base_de_donnees(report: ValidationReport) -> list:
    """Anomalies portant sur la communication avec PostgreSQL (connexion,
    lecture du schéma, insertion) plutôt que sur la saisie de l'utilisateur."""
    return [i for i in report.errors if i.layer == LAYER_BASE_DE_DONNEES]


def report_summary(report: ValidationReport) -> str:
    """Résumé texte court (une ligne par couche en erreur), utilisé par le
    CLI pour l'affichage console — le détail complet reste dans le JSON."""
    if report.is_valid:
        lines = [f"✓ Validation réussie ({sum(report.record_counts.values())} enregistrements)."]
        if report.inserted:
            lines.append("  Données insérées en base.")
        if report.warnings:
            lines.append(f"  {len(report.warnings)} avertissement(s) — voir le rapport JSON.")
        return "\n".join(lines)

    erreurs_bd = erreurs_base_de_donnees(report)
    erreurs_saisie = [i for i in report.errors if i.layer != LAYER_BASE_DE_DONNEES]

    lines: list[str] = []

    # Les problèmes de base de données sont affichés en premier et en entier :
    # ils n'ont rien à voir avec la saisie de l'utilisateur, et ce sont eux
    # qu'on cherche à voir sans ouvrir les journaux du conteneur.
    if erreurs_bd:
        lines.append(f"✗ Problème de base de données ({len(erreurs_bd)}) :")
        for issue in erreurs_bd:
            lines.append(f"  - [{issue.code}] {issue.message}")

    if erreurs_saisie:
        lines.append(
            f"✗ Validation échouée : {len(erreurs_saisie)} erreur(s). Aucune donnée insérée."
        )
        by_layer: dict[str, int] = {}
        for issue in erreurs_saisie:
            by_layer[issue.layer] = by_layer.get(issue.layer, 0) + 1
        for layer, count in sorted(by_layer.items()):
            lines.append(f"  - {layer} : {count} erreur(s)")
    elif erreurs_bd:
        lines.append("  Aucune donnée insérée.")

    return "\n".join(lines)
