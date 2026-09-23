"""Verrouillage d'une unité d'échantillonnage dans la base métier.

Avec la création d'une unité (`unite.py`), c'est l'une des deux écritures que
QFieldCloud pratique sur la base du ministère. Elle porte sur quatre colonnes
de `unite_echan` :

    une_ind_verro        'O' tant que l'unité est tenue
    une_nom_propr_verro  qui la tient
    une_date_verro       depuis quand
    une_raiso_verro      pourquoi — saisi par le technicien avant l'ouverture

et deux colonnes de traçabilité (`une_date_maj`, `une_code_utili_maj`).

Le verrou est **coopératif** : rien dans la base n'empêche une autre
application d'écrire dans une unité tenue. Il sert à ce que deux techniciens ne
partent pas sur le terrain avec la même unité, et le message d'erreur nomme
donc son détenteur — c'est la seule information qui permette de savoir à qui
s'adresser.

Trois portes : `poser()` à l'ouverture ou à la création d'une unité, `lever()`
pour le rattrapage interne d'une préparation qui a échoué, et `relacher()` que
le point d'accès de déverrouillage expose au technicien une fois ses
modifications synchronisées.
"""

from __future__ import annotations

import logging
from typing import Any

from qfieldcloud.ifa import db
from qfieldcloud.ifa.exceptions import UniteIntrouvableError, UniteVerrouilleeError

logger = logging.getLogger(__name__)

# Longueurs déclarées dans le schéma hérité. PostgreSQL rejetterait une valeur
# trop longue ; un nom d'utilisateur QFieldCloud peut dépasser 20 caractères.
LONGUEUR_UTILISATEUR = 20
LONGUEUR_PROPRIETAIRE = 100
LONGUEUR_RAISON = 500

TENUE = "O"

# Les deux façons d'ouvrir une unité. Elles se distinguent ici, et non dans
# `ouverture.py`, parce que c'est le verrou qui fait la différence : le mode
# consultation n'écrit rien dans la base métier.
MODE_MODIFIABLE = "modifiable"
MODE_CONSULTATION = "consultation"
MODES = (MODE_MODIFIABLE, MODE_CONSULTATION)


def lire(une_code_ident: str) -> dict[str, Any]:
    """État de verrou d'une unité. Lève `UniteIntrouvableError` si elle n'existe pas."""
    schema = db.schema()

    with db.curseur() as cur:
        cur.execute(
            f"""
            SELECT une_code_ident,
                   coalesce(une_ind_verro, 'N') AS une_ind_verro,
                   coalesce(une_nom_propr_verro, '') AS une_nom_propr_verro,
                   une_date_verro,
                   coalesce(une_raiso_verro, '') AS une_raiso_verro
              FROM {schema}.unite_echan
             WHERE une_code_ident = %s
            """,
            [une_code_ident],
        )
        lignes = db.lignes_en_dictionnaires(cur)

    if not lignes:
        raise UniteIntrouvableError(
            f"L'unité {une_code_ident} n'existe pas dans la base IFA.",
        )

    return lignes[0]


def poser(une_code_ident: str, utilisateur: str, raison: str) -> dict[str, Any]:
    """Verrouille l'unité au nom de l'utilisateur.

    L'`UPDATE` porte lui-même la condition de non-conflit : deux ouvertures
    simultanées ne peuvent pas réussir toutes les deux, quel que soit
    l'entrelacement. Reprendre son propre verrou est permis — un technicien qui
    rouvre son unité ne doit pas se heurter à lui-même.
    """
    unite = lire(une_code_ident)
    proprietaire = utilisateur[:LONGUEUR_PROPRIETAIRE]
    schema = db.schema()

    with db.curseur_ecriture() as cur:
        cur.execute(
            f"""
            UPDATE {schema}.unite_echan
               SET une_ind_verro       = %(tenue)s,
                   une_nom_propr_verro = %(proprietaire)s,
                   une_date_verro      = LOCALTIMESTAMP,
                   une_raiso_verro     = %(raison)s,
                   une_date_maj        = LOCALTIMESTAMP,
                   une_code_utili_maj  = %(utilisateur)s
             WHERE une_code_ident = %(code)s
               AND (coalesce(une_ind_verro, 'N') <> %(tenue)s
                    OR une_nom_propr_verro = %(proprietaire)s)
            """,
            {
                "tenue": TENUE,
                "proprietaire": proprietaire,
                "raison": raison[:LONGUEUR_RAISON],
                "utilisateur": utilisateur[:LONGUEUR_UTILISATEUR],
                "code": une_code_ident,
            },
        )
        pose = cur.rowcount == 1

    if not pose:
        raise UniteVerrouilleeError(
            "L'unité {code} est verrouillée par {qui}{depuis}.".format(
                code=une_code_ident,
                qui=unite["une_nom_propr_verro"] or "un autre utilisateur",
                depuis=(
                    f" depuis le {unite['une_date_verro']:%Y-%m-%d}"
                    if unite["une_date_verro"]
                    else ""
                ),
            ),
        )

    logger.info(
        "[IFA] verrou pose sur %s par %s",
        une_code_ident,
        utilisateur,
    )

    return lire(une_code_ident)


def lever(une_code_ident: str, utilisateur: str) -> bool:
    """Relâche le verrou, à condition qu'il appartienne à l'utilisateur.

    Sert au rattrapage : si la préparation du projet échoue après la pose du
    verrou, l'unité ne doit pas rester tenue par une ouverture qui n'a jamais
    abouti.
    """
    schema = db.schema()

    with db.curseur_ecriture() as cur:
        cur.execute(
            f"""
            UPDATE {schema}.unite_echan
               SET une_ind_verro       = 'N',
                   une_nom_propr_verro = NULL,
                   une_date_verro      = NULL,
                   une_raiso_verro     = NULL,
                   une_date_maj        = LOCALTIMESTAMP,
                   une_code_utili_maj  = %(utilisateur)s
             WHERE une_code_ident = %(code)s
               AND une_nom_propr_verro = %(proprietaire)s
            """,
            {
                "utilisateur": utilisateur[:LONGUEUR_UTILISATEUR],
                "proprietaire": utilisateur[:LONGUEUR_PROPRIETAIRE],
                "code": une_code_ident,
            },
        )
        leve = cur.rowcount == 1

    if leve:
        logger.info("[IFA] verrou leve sur %s par %s", une_code_ident, utilisateur)

    return leve


def relacher(une_code_ident: str, utilisateur: str) -> dict[str, Any]:
    """Relâche le verrou à la demande de son détenteur.

    Contrepartie de `poser()`, exposée par un point d'accès : le technicien qui
    vient de synchroniser ses modifications rend l'unité aux autres équipes.

    Trois cas, et un seul est une erreur :

    * l'unité n'est pas verrouillée — il n'y a rien à faire, et le dire par une
      erreur serait absurde : le résultat voulu est déjà là. `deverrouille`
      vaut `False`, l'appel réussit ;
    * elle est tenue par l'utilisateur — le verrou tombe ;
    * elle est tenue par quelqu'un d'autre — refusé, et le message le nomme.
      Un technicien ne déverrouille pas l'unité d'un collègue depuis le
      terrain : celui-ci la croirait encore à lui.
    """
    unite = lire(une_code_ident)

    if unite["une_ind_verro"] != TENUE:
        return {"unite": unite, "deverrouille": False}

    if tenue_par_un_autre(unite, utilisateur):
        raise UniteVerrouilleeError(
            "L'unité {code} est verrouillée par {qui} : elle ne peut être "
            "déverrouillée que par son détenteur.".format(
                code=une_code_ident,
                qui=unite["une_nom_propr_verro"] or "un autre utilisateur",
            ),
        )

    lever(une_code_ident, utilisateur)

    return {"unite": lire(une_code_ident), "deverrouille": True}


def tenue_par_un_autre(unite: dict[str, Any], utilisateur: str) -> bool:
    """Vrai si l'unité est verrouillée au nom de quelqu'un d'autre."""
    return (
        unite["une_ind_verro"] == TENUE
        and unite["une_nom_propr_verro"] != utilisateur[:LONGUEUR_PROPRIETAIRE]
    )
