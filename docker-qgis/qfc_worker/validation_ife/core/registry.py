"""
core.registry : Enregistrement et découverte automatique des règles.

POURQUOI un registre global :
  Pour ajouter une règle, un développeur ne doit modifier qu'UN SEUL
  fichier (celui de la couche concernée, dans validation_insertion/rules/),
  jamais une liste centrale à tenir à jour. C'est le décorateur @register
  qui s'inscrit lui-même dans le registre au moment de l'import du module.

POURQUOI la découverte automatique (discover_rules) :
  Pour qu'un module de règles soit pris en compte, il doit être importé au
  moins une fois (sinon le décorateur @register ne s'exécute jamais).
  discover_rules() importe automatiquement TOUS les modules du paquet
  validation_insertion.rules : donc ajouter une nouvelle couche revient à
  simplement déposer un nouveau fichier `rules/ma_nouvelle_couche.py`,
  sans toucher à aucun autre fichier.

Exemple d'ajout d'une règle pour une couche existante (dans
rules/detail_speci.py) :

    from core.registry import register
    from core.rule_base import RuleKind

    @register("detail_speci", kind=RuleKind.VALIDATION)
    def ma_nouvelle_regle(ctx):
        if ctx.row.get("mon_champ") is None:
            return [...]

Exemple d'ajout d'une règle pour une NOUVELLE couche (créer
rules/ma_table.py, rien d'autre à modifier) :

    from core.registry import register
    from core.rule_base import RuleKind

    @register("ma_table", kind=RuleKind.VALIDATION)
    def champ_obligatoire(ctx):
        ...
"""

from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict

from .rule_base import Rule, RuleFunc, RuleKind

_REGISTRY: dict[str, list[Rule]] = defaultdict(list)
_DISCOVERED = False


def register(layer: str, kind: RuleKind = RuleKind.VALIDATION, order: int = 100, name: str | None = None):
    """Décorateur enregistrant une fonction comme règle pour `layer`.

    Args:
        layer: nom de la table/couche PostgreSQL (en minuscules).
        kind: RuleKind.TRANSFORM (peut modifier ctx.row) ou
            RuleKind.VALIDATION (lecture seule, défaut).
        order: ordre d'exécution relatif (croissant) parmi les règles de
            même kind pour la même couche. Laisser la valeur par défaut
            sauf dépendance explicite entre deux règles.
        name: nom affiché dans les rapports/tests ; par défaut le nom de
            la fonction Python décorée.
    """
    def decorator(fn: RuleFunc) -> RuleFunc:
        rule = Rule(layer=layer, name=name or fn.__name__, kind=kind, fn=fn, order=order)
        _REGISTRY[layer].append(rule)
        return fn
    return decorator


def get_rules(layer: str, kind: RuleKind | None = None) -> list[Rule]:
    """Retourne les règles enregistrées pour `layer`, triées par `order`,
    optionnellement filtrées par `kind` (TRANSFORM ou VALIDATION)."""
    rules = _REGISTRY.get(layer, [])
    if kind is not None:
        rules = [r for r in rules if r.kind == kind]
    return sorted(rules, key=lambda r: r.order)


def registered_layers() -> list[str]:
    """Liste des couches pour lesquelles au moins une règle personnalisée
    est enregistrée (utile pour les tests et le diagnostic)."""
    return sorted(_REGISTRY.keys())


def clear_registry(layer: str | None = None) -> None:
    """Vide le registre : utilisé uniquement par les tests unitaires, jamais
    par le code de production.

    Args:
        layer: si fourni, ne vide QUE les règles de cette couche (permet à
            un test d'isoler une couche factice sans détruire les règles
            métier réelles déjà enregistrées par d'autres modules importés
            durant la collecte des tests par pytest : un clear() global
            les effacerait définitivement pour le reste de la session, car
            re-importer un module déjà chargé ne réexécute pas ses
            décorateurs @register). Si omis, vide tout le registre (reset
            complet, à réserver à un script qui n'a pas encore importé les
            règles métier réelles).
    """
    global _DISCOVERED
    if layer is None:
        _REGISTRY.clear()
        _DISCOVERED = False
    else:
        _REGISTRY.pop(layer, None)


def discover_rules(force: bool = False) -> None:
    """Importe tous les modules de validation_insertion.rules, ce qui
    déclenche l'exécution de tous les décorateurs @register qu'ils
    contiennent. Idempotent : n'importe les modules qu'une seule fois,
    sauf si force=True (utile dans les tests après clear_registry())."""
    global _DISCOVERED
    if _DISCOVERED and not force:
        return

    import rules as rules_package

    for module_info in pkgutil.iter_modules(rules_package.__path__):
        importlib.import_module(f"rules.{module_info.name}")

    _DISCOVERED = True
