# validation_insertion — Validation et insertion des données IPE

Programme qui lit un GeoPackage (export QField/QFieldCloud), valide chaque
enregistrement selon les règles métier IFA + les contraintes PostgreSQL, et
n'insère les données en base **que si tout est valide**. En cas d'échec, un
rapport JSON détaillé est produit (couche, champs, nature et description de
chaque anomalie) pour être affiché à l'utilisateur.

Conçu pour fonctionner d'abord **de façon isolée** (ce README), puis être
intégré au conteneur QFieldCloud sans modification majeure (voir
[Intégration QFieldCloud](#intégration-qfieldcloud)).

## Sommaire

1. [Démarrage rapide](#démarrage-rapide)
2. [Architecture](#architecture)
3. [Ajouter une règle](#ajouter-une-règle)
4. [Règles communes (common.py)](#règles-communes-commonpy)
5. [Ajouter une nouvelle couche](#ajouter-une-nouvelle-couche)
6. [Règles automatiques (schéma PostgreSQL)](#règles-automatiques-schéma-postgresql)
7. [Le rapport JSON](#le-rapport-json)
8. [Tests](#tests)
9. [Règles non implémentées](#règles-non-implémentées)
10. [Intégration QFieldCloud](#intégration-qfieldcloud)

## Démarrage rapide

Toutes les commandes s'exécutent **depuis le dossier `validation_insertion/`** :

```bash
cd validation_insertion
pip install -r requirements.txt

# Valide ET insère si tout est valide :
python cli.py chemin/vers/donnees.gpkg

# Valide sans jamais insérer (essai à blanc) :
python cli.py chemin/vers/donnees.gpkg --dry-run

# Rapport JSON à un emplacement précis :
python cli.py chemin/vers/donnees.gpkg --report rapport.json
```

Code de sortie : `0` = validation réussie, `1` = au moins une erreur
bloquante (rien n'est inséré), `2` = erreur d'exécution (fichier introuvable,
connexion BD impossible).

Un rapport JSON est écrit **dans tous les cas**, y compris lorsque la base de
données est injoignable : voir [Erreurs de base de données](#erreurs-de-base-de-données).

Paramètres de connexion : variables d'environnement `VALIDATION_PG_HOST`,
`VALIDATION_PG_PORT`, `VALIDATION_PG_DB`, `VALIDATION_PG_USER`,
`VALIDATION_PG_PASS`, `VALIDATION_PG_SCHEMA` (valeurs par défaut dans
[config.py](config.py), identiques aux autres scripts du projet).

## Architecture

```
validation_insertion/
├── config.py              # connexion BD, ordre des tables IPE, chemins des fichiers de référence
├── cli.py                 # point d'entrée ligne de commande (mode isolé)
├── generate_column_aliases.py  # table-colonne-allias.xlsx -> column_aliases.json
├── column_aliases.json    # libellés lisibles des colonnes (généré, lu par db_schema)
├── core/
│   ├── models.py           # ValidationIssue, ValidationReport, LayerSchema
│   ├── rule_base.py         # RuleContext, Rule, RuleKind (TRANSFORM/VALIDATION)
│   ├── registry.py          # @register, get_rules, discover_rules (auto-découverte)
│   ├── db_schema.py          # introspection PostgreSQL -> règles automatiques
│   ├── gpkg_reader.py        # lecture GeoPackage -> dict de listes de dict
│   ├── inserter.py           # insertion transactionnelle (parent avant enfant)
│   ├── report.py             # sérialisation JSON + résumé texte
│   └── engine.py             # orchestrateur (run())
├── rules/                  # UNE règle = UNE fonction, groupées par couche
│   ├── common.py             # fabriques génériques réutilisables
│   ├── amenagement.py, analy_physi_chimi.py, autre_obser_fauni.py,
│   │   denom_espec.py, descr_habit.py, detail_speci.py, equipe.py,
│   │   forme_descr_habit.py, forme_eleme_habit.py, habitat.py,
│   │   infor_gener.py, peche_exper.py, perturbation.py,
│   │   pose_levee_filet.py, profi_mesur.py, resul_analy_physi_chimi.py
└── tests/                  # pytest — un fichier de test par module de règles
```

Chaque module de `rules/` correspond à un fichier du dossier
[`Règles IFA 2.0/`](Règles%20IFA%202.0/) (une couche = un fichier de règles
métier = un module Python = un fichier de tests). La docstring en tête de
chaque module cite son fichier source et énumère les règles couvertes ainsi
que celles délibérément non couvertes.

### Principe directeur : séparer les RÈGLES du MOTEUR

- Le **moteur** (`core/`) ne connaît AUCUNE règle métier précise. Il sait
  seulement : lire un GeoPackage, demander au schéma PostgreSQL ses
  contraintes, appeler les règles enregistrées dans l'ordre
  TRANSFORM → VALIDATION, décider d'insérer ou non, produire un rapport.
- Les **règles** (`rules/`) ne connaissent rien du moteur au-delà de
  `RuleContext` (ce qu'elles reçoivent) et `ValidationIssue` (ce qu'elles
  retournent). Chaque règle est une fonction Python indépendante.
- Le **registre** (`core/registry.py`) relie les deux : `@register("layer")`
  inscrit une fonction, `discover_rules()` importe automatiquement tous les
  fichiers de `rules/` au démarrage.

Cette séparation est ce qui permet d'ajouter une règle (ou une couche
entière) **sans toucher au moteur**.

### Trois natures de règles

| Nature | Peut modifier l'enregistrement ? | Exécutée |
|---|---|---|
| `RuleKind.TRANSFORM` | Oui (valeurs par défaut, auto-remplissage) | une fois **par enregistrement**, avant les VALIDATION |
| `RuleKind.VALIDATION` | Non (lecture seule) | une fois **par enregistrement**, après les TRANSFORM |
| `RuleKind.LAYER` | Non (lecture seule) | une seule fois **par couche**, même si elle est vide |

Les deux premières reflètent directement les fichiers de règles métier, qui
mélangent systématiquement des instructions du type "assigner automatiquement
X" (TRANSFORM) et "vérifier que / interdire que" (VALIDATION).

`RuleKind.LAYER` répond à un besoin distinct : une règle qui porte sur la
**couche entière** et non sur une ligne précise — "au plus 15 formes de
description d'habitat", "ce tuple doit être unique". Une telle règle ne peut
pas être une VALIDATION ordinaire : elle produirait une anomalie dupliquée à
chaque ligne, et sur une couche à **zéro** ligne le moteur ne l'appellerait
même jamais (sa boucle `for row in rows` ne s'exécute pas). Une règle LAYER
reçoit un `ctx.row` vide et travaille sur `ctx.all_rows` :

```python
@register("forme_descr_habit", kind=RuleKind.LAYER)
def forme_descr_habit_nombre_max(ctx):
    if len(ctx.all_rows) > 15:
        return [ValidationIssue(...)]
    return []
```

### Vérifier l'absence d'enregistrements liés

Le cas « chaque X doit avoir au moins un Y » ne se traite ni par une règle
LAYER sur `Y`, ni par une VALIDATION sur `Y` : c'est l'**absence** de `Y`
qu'il faut détecter, et parcourir les `Y` ne montrera jamais un `X` qui n'en
a aucun. La règle s'enregistre donc sur la couche **parente** `X` et remonte
vers l'enfant par `ctx.other_layer` — voir
[`rules/equipe.py`](rules/equipe.py), qui vérifie que chaque `mesurage` est
rattaché à au moins une équipe :

```python
@register("mesurage", kind=RuleKind.VALIDATION)
def equipe_validation(ctx):
    cle = (ctx.row.get("une_code_ident"), ctx.row.get("mes_no_seq"))
    if any((e.get("une_code_ident"), e.get("mes_no_seq")) == cle
           for e in ctx.other_layer("equipe")):
        return []
    return [ValidationIssue(severity=Severity.WARNING, ...)]
```

## Ajouter une règle

Exemple : ajouter une règle de validation sur une couche existante
(`rules/detail_speci.py`) :

```python
from core.models import Severity, ValidationIssue
from core.registry import register
from core.rule_base import RuleContext, RuleKind

@register("detail_speci", kind=RuleKind.VALIDATION)
def ma_nouvelle_regle(ctx: RuleContext) -> list[ValidationIssue]:
    if ctx.row.get("mon_champ") and ctx.row.get("mon_champ") > 1000:
        return [ValidationIssue(
            layer=ctx.layer, severity=Severity.ERROR, code="DETAIL_SPECI_MON_CHAMP_TROP_GRAND",
            message="mon_champ ne doit pas dépasser 1000.",
            fields=["mon_champ"], record=ctx.record_key(),
        )]
    return []
```

Pour les motifs courants (champ obligatoire, comparaison entre deux champs,
valeur interdite, date bornée par une autre table...), utiliser une fabrique
de [`rules/common.py`](rules/common.py) plutôt que réécrire la logique :

```python
from rules.common import required_field
register("detail_speci")(required_field("mon_champ", "Mon champ", code="X"))
```

Aucun autre fichier n'a besoin d'être modifié : la fonction décorée
s'enregistre elle-même dès que `rules/detail_speci.py` est importé (ce que
`discover_rules()` fait automatiquement au démarrage du moteur).

### `RuleContext` — ce qu'une règle reçoit

| Attribut | Contenu |
|---|---|
| `ctx.row` | l'enregistrement courant (dict **mutable** — modifiable par une TRANSFORM) |
| `ctx.all_rows` | tous les enregistrements de la même couche dans le lot |
| `ctx.layers` | tous les enregistrements de toutes les couches (`ctx.other_layer("infor_gener")`) |
| `ctx.schemas` | métadonnées PostgreSQL par table (PK, NOT NULL, ENUM, plages) |
| `ctx.record_key()` | clé métier de la ligne, pour identifier l'anomalie dans le rapport |

## Règles communes (common.py)

### Pourquoi des fabriques ?

Le fichier de règles métier répète les mêmes motifs des dizaines de fois :
"tel champ est obligatoire", "tel champ doit être inférieur à tel autre",
"assigner une valeur par défaut si vide". Plutôt que de réécrire ces
logiques à la main dans chaque fichier de couche, [`rules/common.py`](rules/common.py)
fournit des **fabriques** — des fonctions qui *retournent* une fonction-règle
déjà configurée et nommée.

Le résultat est une règle Python normale, utilisable exactement comme une
règle écrite à la main avec `@register` :

```python
# Équivalent : ces deux formes enregistrent la même règle
register("ma_couche")(required_field("mon_champ", "Mon champ", code="X"))

@register("ma_couche")
def required_field_mon_champ(ctx):
    if _is_blank(ctx.row.get("mon_champ")):
        return [ValidationIssue(..., message="Le champ « Mon champ » est obligatoire.", ...)]
    return []
```

### Fabriques disponibles

| Fabrique | Nature | Ce qu'elle vérifie / fait |
|---|---|---|
| `required_field(field, label, code, *, when=None)` | VALIDATION | Le champ doit être renseigné. Paramètre `when` : fonction `ctx → bool` pour une obligation conditionnelle. |
| `at_least_one_of(fields, label, code)` | VALIDATION | Au moins un des champs de la liste doit être renseigné. |
| `forbidden_values(field, label, values, code)` | VALIDATION | Le champ ne doit pas contenir l'une des valeurs listées. |
| `cross_field_lte(field_a, field_b, message, code, *, strict=False)` | VALIDATION | `field_a <= field_b` (ou `<` si `strict=True`). Ignoré si l'un des champs est vide. |
| `default_if_empty(field, default_fn, *, also_check=None)` | TRANSFORM | Si le champ est vide, lui assigne `default_fn(ctx)`. `also_check` : vérification enchaînée après l'assignation. |
| `date_within_bounds(date_field, lower, upper, label, code, *, other_layer=None)` | VALIDATION | La date doit être comprise entre les bornes d'un enregistrement d'une autre couche du même mesurage. |
| `lookup_assign(source_fields, target_field, table, *, contains_match=False)` | TRANSFORM | Assigne `target_field` par recherche dans un dictionnaire `{(clé_1, clé_2, ...): valeur}`. |

> **Remarque sur `_is_blank`** : une valeur est considérée vide si elle est
> `None`, `NaN` (résultat de GeoPandas sur une cellule vide), ou une chaîne
> ne contenant que des espaces. Toutes les fabriques utilisent cette fonction
> interne — vous n'avez pas à la vérifier vous-même.

### Exemples d'utilisation

```python
from core.registry import register
from core.rule_base import RuleKind
from rules.common import (
    required_field, at_least_one_of, forbidden_values,
    cross_field_lte, default_if_empty, date_within_bounds,
)

# Champ obligatoire (sans condition)
register("detail_speci")(required_field(
    "dsp_no_speci", "Numéro de spécimen", code="DETAIL_SPECI_NO_SPECI_REQUIS"))

# Champ conditionnellement obligatoire (requis si l'espèce est un saumon)
register("detail_speci")(required_field(
    "dsp_long_fourc_mm", "Longueur à la fourche", code="DETAIL_SPECI_LONG_FOURC_REQUISE",
    when=lambda ctx: ctx.row.get("efa_code") in {"SAT", "SAL"}))

# Au moins un de ces deux champs doit être renseigné
register("detail_speci")(at_least_one_of(
    ["dsp_long_tot_max_m", "dsp_long_fourc_mm"],
    "Longueur totale max ou Longueur à la fourche",
    code="DETAIL_SPECI_LONGUEUR_REQUISE"))

# Valeurs interdites
register("pose_levee_filet")(forbidden_values(
    "plf_type_pose", "Type de pose", values=["INC", "ERR"],
    code="POSE_LEVEE_TYPE_INTERDIT"))

# Cohérence entre deux champs numériques
register("detail_speci")(cross_field_lte(
    "dsp_long_fourc_mm", "dsp_long_tot_max_m",
    "La longueur à la fourche doit être ≤ à la longueur totale maximale.",
    code="DETAIL_SPECI_COHERENCE_LONGUEURS"))

# Valeur par défaut automatique (TRANSFORM)
register("analy_physi_chimi", kind=RuleKind.TRANSFORM)(default_if_empty(
    "apc_date_visite",
    default_fn=lambda ctx: ctx.row.get("mes_date_debut")))

# Date bornée par les dates d'une autre couche
register("analy_physi_chimi")(date_within_bounds(
    "apc_date_visite", "mes_date_debut", "mes_date_fin",
    "La date de visite", code="ANALY_DATE_VISITE_HORS_INVENTAIRE",
    other_layer="infor_gener"))

# Assignation par table de correspondance (TRANSFORM)
PANNEAU_TABLE = {("FIX", "38"): "A", ("FIX", "50"): "B", ("EXP", "38"): "C"}
register("pose_levee_filet", kind=RuleKind.TRANSFORM)(lookup_assign(
    source_fields=["plf_type_peche", "plf_maille_mm"],
    target_field="plf_panneau",
    table=PANNEAU_TABLE))
```

### Ajouter une fabrique commune

Créer une fabrique dans `rules/common.py` **uniquement si le même motif
apparaît (ou va apparaître) dans au moins deux couches différentes**. Pour
une logique spécifique à une seule couche, écrire la règle directement dans
le fichier de cette couche.

Structure d'une fabrique :

```python
def ma_fabrique(param1: str, param2: str, code: str, **options):
    """Description courte de ce que la règle vérifie.

    Args:
        param1: ...
        param2: ...
        code: code stable affiché dans le rapport JSON.
    """
    def rule(ctx: RuleContext) -> list[ValidationIssue]:
        valeur = ctx.row.get(param1)
        if _is_blank(valeur):
            return []  # déléguer au required_field si la valeur est obligatoire
        # ... logique de vérification ...
        if condition_erreur:
            return [ValidationIssue(
                layer=ctx.layer,
                severity=Severity.ERROR,
                code=code,
                message=f"Message d'erreur lisible par l'utilisateur.",
                fields=[param1],
                record=ctx.record_key(),
            )]
        return []
    rule.__name__ = f"ma_fabrique_{param1}"  # nom unique pour le rapport/tests
    return rule
```

Points importants :
- Toujours assigner `rule.__name__` pour identifier la règle dans les rapports et les tests.
- Retourner `[]` (liste vide) si la règle ne s'applique pas ou ne détecte rien.
- Ne pas vérifier l'obligation de saisie dans une fabrique spécialisée : laisser `required_field` s'en charger séparément.
- Ajouter un test dans `tests/test_rules_common.py` pour chaque nouvelle fabrique.

## Ajouter une nouvelle couche

Déposer un nouveau fichier `rules/ma_table.py` :

```python
from core.registry import register
from core.rule_base import RuleKind
from rules.common import required_field

LAYER = "ma_table"

register(LAYER, kind=RuleKind.VALIDATION)(
    required_field("mon_champ", "Mon champ", code="MA_TABLE_MON_CHAMP_REQUIS")
)
```

**Rien d'autre à modifier** : `core/registry.py::discover_rules()` importe
automatiquement tous les modules de `rules/` via `pkgutil` — aucune liste
centrale à maintenir. Les règles "imposées par la BD" (NOT NULL, plages,
ENUM, clé primaire) sont, elles, automatiquement déduites du schéma
PostgreSQL (voir section suivante) — aucun code à écrire pour celles-ci.

Si la nouvelle table doit être insérée en base APRÈS certaines de ses
tables parentes, ajouter son nom à `INSERT_ORDER` dans
[`core/inserter.py`](core/inserter.py) (sinon elle est insérée après toutes
les tables connues, ce qui suffit si elle n'a pas d'enfants).

## Règles automatiques (schéma PostgreSQL)

[`core/db_schema.py`](core/db_schema.py) introspecte PostgreSQL pour chaque
table traitée et génère automatiquement :

- les colonnes **NOT NULL** sans valeur par défaut serveur,
- les **plages numériques** (`CHECK (col >= a AND col <= b)`, `BETWEEN`...),
- les **valeurs ENUM** autorisées,
- la **clé primaire** (utilisée pour identifier les lignes dans le rapport).

Si un collègue ajoute une contrainte côté base de données, elle est prise en
compte automatiquement, sans modifier ce dépôt.

### Libellés des colonnes dans les messages

Les messages produits par ces règles automatiques désignent les colonnes par
leur **alias métier** plutôt que par leur nom technique :

> Le champ « Date du début de l'inventaire » est obligatoire (contrainte NOT NULL).

et non « Le champ `ing_date_debut_inven` … », illisible pour la personne qui
a rempli le formulaire.

Les alias proviennent de [`column_aliases.json`](column_aliases.json), généré
depuis le classeur `table-colonne-allias.xlsx` :

```bash
python generate_column_aliases.py    # à relancer si le classeur change
```

Le script n'utilise que la bibliothèque standard (`zipfile` + `xml.etree` :
un `.xlsx` est une archive ZIP de XML), et le JSON produit se lit avec
`json` : **aucune dépendance supplémentaire** n'est requise, ni pour générer
le fichier ni pour l'utiliser à l'exécution.

Points de conception :

- La table est indexée par **(table, colonne)** et non par colonne seule :
  13 colonnes portent un libellé différent selon la table (ex. `efa_code`
  = « Espèce » dans `detail_speci` mais « Espèce visée » dans `peche_exper`).
- `core.db_schema.column_label(layer, column)` **retombe sur le nom technique**
  si l'alias est inconnu, et un fichier JSON absent ou illisible ne fait
  jamais échouer une validation.
- Seul le `message` change : le champ `fields` de chaque anomalie continue de
  porter le nom **technique** de la colonne, puisqu'il est lu par QField/QGIS
  pour mettre le bon champ en évidence dans le formulaire.

## Le rapport JSON

Format (voir [`core/models.py::ValidationReport.to_dict`](core/models.py)) :

```json
{
  "source": "donnees.gpkg",
  "layers_processed": ["mesurage", "infor_gener", "..."],
  "record_counts": {"mesurage": 1, "infor_gener": 1},
  "is_valid": false,
  "inserted": false,
  "error_count": 2,
  "warning_count": 1,
  "issues": [
    {
      "layer": "detail_speci",
      "severity": "error",
      "code": "DETAIL_SPECI_ESPECE_REQUISE",
      "message": "Le champ « Espèce » est obligatoire.",
      "fields": ["efa_code"],
      "record": {"une_code_ident": "UE001", "mes_no_seq": 1, "dsp_no_speci": 3},
      "rule_name": "required_field_efa_code"
    }
  ]
}
```

`severity: "warning"` n'empêche PAS l'insertion — ex. coefficient de
condition biologique hors bornes, ou mesurage sans équipe de travail
rattachée : ce sont des saisies à vérifier, pas des incohérences qui
rendraient les données inexploitables. Seul `"error"` bloque le lot entier.

### Erreurs de base de données

Les incidents de communication avec PostgreSQL **figurent dans le rapport**
au lieu de n'exister que dans les journaux du conteneur : ils portent la
pseudo-couche `(base de données)` — un nom qu'aucune vraie table ne peut
porter, donc filtrable de façon fiable :

```json
{
  "layer": "(base de données)",
  "severity": "error",
  "code": "DB_CONNEXION_IMPOSSIBLE",
  "message": "Connexion à PostgreSQL impossible (hôte db:5432, base ifa). Détail technique : OperationalError: could not connect to server: Connection refused",
  "fields": [],
  "record": {},
  "rule_name": "cli.connect"
}
```

| Code | Quand | Conséquence |
|---|---|---|
| `DB_CONNEXION_IMPOSSIBLE` | La connexion n'a pas pu être ouverte (`cli.py`) | Rapport écrit, code de sortie `2` |
| `DB_SCHEMA_INDISPONIBLE` | Échec de `load_schema` (base injoignable, droits, schéma absent) | Les règles métier sont **quand même** appliquées, mais rien n'est inséré |
| `DB_INSERTION_ECHOUEE` | Échec de `insert_all` | Transaction annulée (rollback), nom de la table fautive cité dans le message |

Points de conception :

- **Aucune exception ne remonte** de `engine.run` pour ces cas : un rapport
  est toujours produit, y compris quand la connexion échoue avant même la
  validation (`layers_processed` est alors vide).
- Le message contient le **type et le texte de l'exception du driver**,
  repliés sur une seule ligne (les messages psycopg2 sont multilignes).
- Une erreur de base de données rend le rapport invalide, ce qui **empêche
  l'insertion** : on n'insère jamais des données dont les contraintes de la
  base n'ont pas pu être vérifiées.
- Le résumé console affiche ces erreurs **en entier** et séparément des
  erreurs de saisie (qui, elles, sont comptées par couche).

## Tests

```bash
# Depuis le dossier validation_insertion/
pip install -r requirements.txt   # psycopg2-binary + pytest (aucune bibliothèque GIS)
python -m pytest tests -q
```

369 tests à la rédaction de ce document, organisés en :
- tests du moteur (`core/`) avec des doublures pour la base de données
  (jamais de connexion PostgreSQL réelle requise pour la suite automatisée) ;
- un fichier de test par module de règles, appelant les fonctions
  directement (pas besoin de passer par le registre ni par un GeoPackage) ;
- `tests/test_gpkg_reader.py` utilise un vrai petit GeoPackage généré à la
  volée (fixture `sample_gpkg`) pour valider la lecture réelle, sans fichier
  externe à maintenir.

La fixture `sample_gpkg` construit ce GeoPackage avec **`sqlite3` seul**
(`tests/conftest.py::creer_gpkg`), comme le lecteur qui le relit : tables de
métadonnées `gpkg_contents` / `gpkg_geometry_columns` / `gpkg_spatial_ref_sys`,
identifiant d'application « GPKG » et géométries au format GeoPackageBinary.
La suite de tests s'exécute donc dans le même environnement "nu" que le
conteneur QFieldCloud visé — aucune bibliothèque GIS n'est requise, ni pour
lire un GeoPackage, ni pour en fabriquer un.

Ajouter une règle implique d'ajouter son test dans le fichier
`tests/test_rules_<couche>.py` correspondant (créer le fichier s'il n'existe
pas encore).

## Règles non implémentées

Certaines règles des documents sources (`Règles IFA 2.0/*.groovy`) ne sont pas
actives, pour des raisons documentées directement dans le code source
(docstring de la fonction `TODO_*` ou note en tête de fichier) :

| Règle | Fichier | Raison |
|---|---|---|
| Filtres de listes déroulantes (territoire faunique selon région, espèce visée selon catégorie, filtre de la liste "Zone") | divers | Comportement d'interface utilisateur QGIS, sans effet sur la validité d'un enregistrement déjà saisi |
| Écrans de consultation d'historique (habitats, perturbations, activités d'aménagement) | `rules/perturbation.py`, `rules/amenagement.py` (docstrings de module) | Rapports ouverts par un bouton du formulaire, sans effet sur la validité d'un enregistrement |
| Agrégations Détail des spécimens ↔ Dénombrement par espèce (masse/nombre pesé/capturé) | `rules/detail_speci.py` (docstring de module) | Logique d'agrégation complexe, à valider avec des données réelles avant activation |
| Filtre type de structure selon l'espèce | `rules/detail_speci.py::TODO_filtre_type_structure` | Liste d'espèces du document non confirmée exhaustive |
| `assigner_no_vial` / `assigner_no_specimen_unique` | `rules/detail_speci.py` | Règles de SAISIE (numérotation à l'ajout d'un spécimen dans le formulaire), pas de validation de lot — fournies et testées comme utilitaires, non câblées au moteur |
| `generer_profondeurs` | `rules/profi_mesur.py` | Alimente une liste de choix du formulaire QGIS, pas une validation post-saisie — fournie et testée comme utilitaire |

Activer l'une de ces règles : suivre les instructions de la docstring
correspondante (chaque `TODO_*` explique précisément la marche à suivre).

### Interprétations retenues sur des points ambigus

Trois passages des documents sources se prêtaient à plusieurs lectures. Le
choix retenu est expliqué en commentaire à l'endroit concerné du code :

| Point | Choix retenu | Fichier |
|---|---|---|
| `INFOR_GENER` liste Latitude/Longitude du centre parmi les "variables obligatoires", mais décrit juste avant une règle "au moins une coordonnée" (BD LCE **ou** centre) | Seule la règle "au moins une coordonnée" est appliquée : les rendre inconditionnellement obligatoires contredirait la règle précédente | `rules/infor_gener.py` |
| `PECHE_EXPER` décrit l'effort de pêche (`IFD_EFFORT`) alors que le champ appartient à la table `pose_levee_filet` | Règle implémentée dans `rules/pose_levee_filet.py`, où le champ existe réellement | `rules/peche_exper.py` |
| `RESUL_ANALY_PHYSI_CHIMI` impose "renseigner résultat" pour tout paramètre ≠ TI, mais conditionne ailleurs cette obligation à l'indicateur d'analyse en laboratoire | La règle TI ne vérifie que l'**exclusion mutuelle** ; l'obligation de saisie est portée par la règle conditionnelle, pour éviter deux anomalies contradictoires | `rules/resul_analy_physi_chimi.py` |

## Intégration QFieldCloud

Ce dépôt est **directement déployable** : il contient tout ce dont le worker
QFieldCloud a besoin, y compris les adaptations propres à cet environnement
(exclusion de `rapport_validation`, upsert `ON CONFLICT`). Aucune modification
locale n'est à réappliquer après une copie.

### Ce qu'il faut copier

Le worker attend le programme dans
`docker-qgis/qfc_worker/validation_ifa/`, où le point d'entrée
`validate_ifa.py` l'ajoute à `sys.path` avant d'importer `config` et
`core.engine`.

| À copier | Pourquoi |
|---|---|
| `config.py` | chemins des fichiers de référence + connexion |
| `core/`, `rules/` | le moteur et les règles |
| `column_aliases.json` | libellés lisibles des colonnes |
| `lac_LCE.txt`, `cours_eau_LCE.txt` | référentiel des plans d'eau |

Inutiles en production : `tests/`, `cli.py` (le point d'entrée est
`validate_ifa.py`), `generate_column_aliases.py` et `table-colonne-allias.xlsx`
(outils de génération hors ligne), `Règles IFA 2.0/`.

> **`config.py` et `core/db_schema.py` vont ensemble.** Le repli en cas de
> fichier d'alias manquant ne couvre que les erreurs d'ouverture et de format ;
> un `config.py` dépareillé, sans `COLUMN_ALIASES_PATH`, lève un
> `AttributeError`. Copier `column_aliases.json` en même temps, sinon les
> messages retombent silencieusement sur les noms techniques de colonnes.

### Deux comportements spécifiques au déploiement

- **`rapport_validation` n'est jamais insérée en base.** Le worker écrit cette
  table *dans* le GeoPackage comme restitution pour le technicien, et
  l'enregistre dans `gpkg_contents`. Au passage suivant, le lecteur la voit
  donc comme une couche ordinaire : sans l'exclusion de
  `inserter.NON_INSERTABLE_TABLES`, elle serait réinjectée vers une relation
  PostgreSQL inexistante et **tout le lot serait rejeté à chaque
  synchronisation**.
- **Un second envoi met à jour au lieu d'échouer.** `insert_all` reçoit les
  schémas (donc les clés primaires) et construit un `ON CONFLICT … DO UPDATE` :
  un technicien qui pousse deux fois le même mesurage corrige ses données, il
  ne crée pas un doublon. Sans les schémas, la clause n'est pas émise et un
  doublon lèverait une erreur — d'où le test qui verrouille ce passage.

### Points d'attention

Ce programme a été développé et testé **isolément** (connexion PostgreSQL
directe, exécution manuelle via `cli.py`). Pour l'intégrer au conteneur
QFieldCloud :

1. **Déclenchement** : QFieldCloud expose des hooks/signaux Django à la
   réception d'un paquet de synchronisation. Le point d'intégration naturel
   est d'appeler `core.engine.run(gpkg_path, conn, ...)` depuis ce hook,
   plutôt que `cli.py` (qui reste utile pour les tests manuels/CI).
2. **Connexion BD** : `config.py` lit déjà ses paramètres depuis des
   variables d'environnement (`VALIDATION_PG_*`) — à faire correspondre aux
   variables d'environnement déjà injectées par QFieldCloud pour sa propre
   base, ou à exposer séparément selon que la base IFA est distincte de la
   base QFieldCloud.
3. **Dépendances** : la lecture du GeoPackage n'utilise que `sqlite3` de la
   bibliothèque standard — un GeoPackage EST une base SQLite (voir
   [`core/gpkg_reader.py`](core/gpkg_reader.py)). Ni PyQGIS, ni
   geopandas/fiona/GDAL ne sont requis : `psycopg2-binary` est la seule
   dépendance d'exécution, `pytest` la seule dépendance de test.
4. **Rapport** : le JSON produit par `core/report.py` est déjà conçu pour
   être renvoyé tel quel par une réponse HTTP/API QFieldCloud à l'utilisateur.
5. **Transaction** : `core/inserter.py` insère tout dans une seule
   transaction côté base IFA — à examiner si elle doit être combinée avec la
   transaction QFieldCloud elle-même (selon que la base IFA et la base
   QFieldCloud sont la même instance PostgreSQL ou non).

Aucun changement d'architecture n'est anticipé : `core/engine.py` est déjà
indépendant de tout contexte CLI ou web (il prend une connexion déjà
ouverte en paramètre).
