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

from .models import ValidationReport


def save_report(report: ValidationReport, path: str | Path) -> None:
    """Écrit le rapport au format JSON (UTF-8, indenté pour la lisibilité
    humaine en cas de consultation directe du fichier)."""
    Path(path).write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


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

    lines = [f"✗ Validation échouée : {len(report.errors)} erreur(s). Aucune donnée insérée."]
    by_layer: dict[str, int] = {}
    for issue in report.errors:
        by_layer[issue.layer] = by_layer.get(issue.layer, 0) + 1
    for layer, count in sorted(by_layer.items()):
        lines.append(f"  - {layer} : {count} erreur(s)")
    return "\n".join(lines)
