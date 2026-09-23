"""Préparation du projet de saisie d'une nouvelle unité d'échantillonnage.

La fenêtre « Créer une UE » du plugin décrit l'unité à créer (région, projet,
type, plan d'eau, identifiant) puis choisit, dans son bloc « Données à
embarquer », le sous-ensemble du fonds que le technicien veut emporter. À la
validation, le serveur prépare sous son compte le projet `formulaire_UE_IFA` :

1. les unités visées par le filtre sont **résolues une fois** en une liste de
   `une_code_ident`. Le technicien peut croiser plusieurs critères — région,
   n° de plan d'eau, nom de bassin, emprise tracée — et une unité doit alors
   les satisfaire tous ;
2. la **nouvelle unité est inscrite dans `unite_echan` et verrouillée**
   (`unite.py`) — c'est ce qui réserve son code ;
3. elle est ajoutée aux unités à embarquer. Sans cela elle manquerait au
   projet livré : `unite_echan` est l'une des trente-sept tables du
   GeoPackage, et une unité qui vient de naître n'a encore ni mesurage ni
   `infor_gener` — donc rien qui puisse répondre au filtre du technicien ;
4. `projets.preparer()` recopie le dernier paquet du projet modèle, remplit son
   GeoPackage des inventaires de ces unités, et pose les variables de projet
   qui alimentent les valeurs par défaut du formulaire ;
5. le projet est packagé ; QField n'a plus qu'à le télécharger et l'ouvrir.

L'ordre compte. L'unité est créée **avant** la préparation, comme le verrou de
`ouverture.py` est posé avant elle : il vaut mieux échouer sans avoir rien
packagé que de livrer un projet pour une unité dont le code était déjà pris. En
contrepartie, une préparation qui échoue laisse la ligne derrière elle — c'est
voulu, et `unite.creer()` explique comment la tentative suivante la reprend.

---------------------------------------------------------------------------
POURQUOI RÉSOUDRE LES UNITÉS D'ABORD
---------------------------------------------------------------------------
Le filtre du client est le même que celui de la recherche (`filtres.py`) : un
`EXISTS` qui joint `mesurage` et `proje_sonda` pour la région, `infor_gener`
pour le plan d'eau, le bassin et l'emprise — autant d'`EXISTS` que de critères
cochés. Le glisser tel quel dans le `WHERE` de chacune
des trente-sept tables copiées rejouerait cette jointure trente-sept fois — un
quart de seconde par table pour un filtre par région, et près d'une seconde
pour un filtre par plan d'eau. Résolue une fois, la liste sert ensuite de
simple `= ANY(%s)`.

Elle donne du même coup le décompte qu'on rend au client, et le garde-fou :
une région porte plus de douze mille unités, et tout embarquer ferait un
GeoPackage qu'aucun appareil de terrain ne téléchargerait. Au-delà de
`IFA_FORMULAIRE_UNITES_MAX`, la demande est refusée avec un message qui invite
à resserrer le filtre — ce que le croisement de critères permet justement de
faire sans changer de critère principal : une région *et* un bassin plutôt
qu'une région seule.

---------------------------------------------------------------------------
UNE SÉLECTION VIDE N'EST PAS UNE ERREUR
---------------------------------------------------------------------------
Créer une unité là où il n'y en a jamais eu est le cas normal d'un nouveau
plan d'eau ou d'une emprise vierge. Le projet est alors livré avec ses seuls
référentiels — de quoi remplir les listes déroulantes du formulaire — et c'est
exactement ce qu'il faut.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from qfieldcloud.core.models import PackageJob, Person, Project
from qfieldcloud.ifa import db, filtres, inventaires, projets, unite
from qfieldcloud.ifa.exceptions import FiltreInvalideError

logger = logging.getLogger(__name__)

# Les quatre critères du bloc « Données à embarquer », combinables entre eux.
# Le mode `code` de la recherche n'y figure pas : on ne crée pas une unité à
# partir d'un fragment de code d'unité existante.
MODE_REGION = filtres.MODE_REGION
MODE_LCE = filtres.MODE_LCE
MODE_BASSIN = filtres.MODE_BASSIN
MODE_EMPRISE = filtres.MODE_EMPRISE

MODES = (MODE_REGION, MODE_LCE, MODE_BASSIN, MODE_EMPRISE)

# Variables de projet acceptées du client. La liste est fermée : ce qui part
# dans le `.qgs` livré ne doit pas dépendre de ce qu'un client envoie, et ces
# noms sont ceux que lisent les valeurs par défaut du formulaire QGIS.
VARIABLES_ATTENDUES = (
    "code_region",
    "code_projet",
    "code_formulaire",
    "type_formulaire",
    "code_lce",
    "une_code_ident",
)

# Longueur maximale d'une valeur de variable. Les variables de projet portent
# des codes, pas des textes libres.
LONGUEUR_VARIABLE = 200


@dataclass
class Resultat:
    """Ce que le plugin reçoit une fois le projet de saisie préparé."""

    preparation: projets.Preparation
    criteres: list[dict[str, Any]]
    libelle: str
    unites: int
    unite_creee: dict[str, Any]

    @property
    def mode(self) -> str:
        """Le premier critère retenu — lu par les clients antérieurs."""
        return str(self.criteres[0]["mode"])

    @property
    def projet(self) -> Project:
        return self.preparation.projet

    @property
    def travail(self) -> PackageJob:
        return self.preparation.travail

    def en_dictionnaire(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "criteres": filtres.resume(self.criteres),
            "filtre": self.libelle,
            "unites": self.unites,
            **self.preparation.en_dictionnaire(),
        }


def preparer(
    utilisateur: Person,
    criteres: Sequence[Mapping[str, Any]],
    une_code_ident: str,
    type_ue: str,
    variables: dict[str, str] | None = None,
) -> Resultat:
    """Crée l'unité, prépare le projet de saisie, et en constitue le paquet."""
    retenus = [dict(critere) for critere in criteres]

    assert retenus
    assert all(critere["mode"] in MODES for critere in retenus)

    # Le filtre d'abord : une demande trop large est refusée avant qu'une ligne
    # n'ait été écrite dans la base métier.
    codes = unites_du_filtre(retenus)
    libelle = libelle_filtre(retenus, len(codes))

    # Puis l'unité : son code est réservé, et elle est tenue au nom de celui qui
    # la crée. Voir `unite.py` pour la reprise d'une création interrompue.
    unite_creee = unite.creer(une_code_ident, type_ue, utilisateur.username)
    code = unite_creee["une_code_ident"]

    embarquees = codes if code in codes else [*codes, code]

    preparation = projets.preparer(
        utilisateur=utilisateur,
        nom=settings.IFA_PROJET_FORMULAIRE,
        description=description_projet(code, libelle),
        selection=inventaires.Selection.pour_unites(
            embarquees, libelle, settings.IFA_FORMULAIRE_LIGNES_MAX
        ),
        variables=_variables_retenues(variables),
    )

    logger.info(
        "[IFA] projet de saisie prepare pour %s (unite %s, %s, %s unites, projet %s)",
        utilisateur.username,
        code,
        libelle,
        len(embarquees),
        preparation.projet.id,
    )

    return Resultat(
        preparation=preparation,
        criteres=retenus,
        libelle=libelle,
        unites=len(embarquees),
        unite_creee=unite_creee,
    )


def unites_du_filtre(criteres: Sequence[Mapping[str, Any]]) -> list[str]:
    """Codes des unités visées par le filtre, une requête et une seule.

    Les critères sont croisés : une unité doit les satisfaire tous.

    La borne est demandée à PostgreSQL (`LIMIT max + 1`) plutôt que comptée
    après coup : dépasser le plafond doit coûter une ligne de plus, pas la
    lecture des douze mille unités d'une région.
    """
    schema = db.schema()
    fragment, parametres = filtres.predicats(
        criteres=criteres,
        schema=schema,
        srid_metier=settings.IFA_DB_SRID,
    )

    plafond = int(settings.IFA_FORMULAIRE_UNITES_MAX)

    requete = f"""
        SELECT u.une_code_ident
        FROM {schema}.unite_echan u
        WHERE {fragment}
        ORDER BY u.une_code_ident
        LIMIT %s
    """

    with db.curseur() as cur:
        cur.execute(requete, [*parametres, plafond + 1])
        codes = [ligne[0] for ligne in cur.fetchall()]

    if len(codes) > plafond:
        raise FiltreInvalideError(
            f"Le filtre choisi porte sur plus de {plafond} unités "
            "d'échantillonnage : le projet serait trop lourd pour un appareil "
            "de terrain. Restreignez les données à embarquer — un n° de plan "
            "d'eau, un nom de bassin ou une emprise tracée sur la carte, "
            "seuls ou croisés avec la région.",
        )

    return codes


def libelle_filtre(criteres: Sequence[Mapping[str, Any]], unites: int) -> str:
    """Le filtre en une ligne, pour les messages, le journal et la description."""
    return f"{filtres.libelle_criteres(criteres)} — {unites} unité(s)"


def description_projet(une_code_ident: str, libelle: str) -> str:
    return (
        f"Projet de saisie IFA 2.0 — création de l'unité {une_code_ident} "
        f"({libelle}). Son contenu est remplacé à chaque préparation."
    )


def _variables_retenues(variables: dict[str, str] | None) -> dict[str, str]:
    """Ne garde que les variables attendues, tronquées, sans les vides.

    Une variable vide n'est pas posée : la valeur par défaut du formulaire vaut
    mieux qu'une chaîne vide, qui masquerait l'expression de repli.
    """
    if not variables:
        return {}

    retenues: dict[str, str] = {}

    for nom in VARIABLES_ATTENDUES:
        valeur = str(variables.get(nom, "") or "").strip()

        if valeur:
            retenues[nom] = valeur[:LONGUEUR_VARIABLE]

    return retenues
