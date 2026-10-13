"""Accès en lecture seule à la base métier IFA.

La base IFA (`ifa`, schéma `ifa_data`) est celle du ministère : elle existe
avant QFieldCloud, elle est alimentée par d'autres applications, et QFieldCloud
n'en est pas propriétaire. Trois conséquences, appliquées ici :

1. **Aucun modèle Django.** Le schéma hérité ne se plie pas aux conventions de
   l'ORM (clés composites, types énumérés, colonnes `shape` en EPSG:32187) et
   surtout : le décrire en modèles inviterait tôt ou tard une migration à s'y
   appliquer. Tout passe par du SQL brut, paramétré.
2. **Transaction en lecture seule par défaut.** `curseur()` ouvre un
   `SET TRANSACTION READ ONLY` : même un défaut de programmation ne peut pas
   écrire dans la base de production. La seule exception est
   `curseur_ecriture()`, et toutes les écritures que QFieldCloud pratique sur
   la base métier y passent : le **verrouillage** d'une unité (`verrou.py`) et
   la **création** d'une nouvelle unité (`unite.py`), sur `unite_echan` ; la
   **création** d'un projet de sondage et de ses types d'UE
   (`projet_sonda.py`), puis sa **modification** et sa **suppression**
   (`projet_gestion.py`), sur `proje_sonda` et `proje_type_unite_echan` ; la
   **suppression** d'une unité et de toutes ses données de terrain
   (`unite_gestion.py`). Le compte PostgreSQL du serveur a donc besoin des
   droits `UPDATE` et `INSERT` sur `unite_echan`, `INSERT`, `UPDATE` et
   `DELETE` sur les deux tables du projet, `DELETE` sur les 44 tables qui
   portent `une_code_ident`, et d'eux seuls.
3. **Délai maximal par requête.** `statement_timeout` empêche une recherche mal
   filtrée d'immobiliser un travailleur gunicorn — les tables comptent plusieurs
   centaines de milliers de lignes et certaines colonnes ne sont pas indexées
   (voir `sql/index_recommandes.sql`).

La connexion réutilise les variables `VALIDATION_PG_*` déjà employées par le
conteneur `qgis` pour la validation des livraisons : une seule base, un seul
jeu de paramètres. L'alias est déclaré dans `settings.py`, et seulement si
`VALIDATION_PG_HOST` est renseignée — sur une installation QFieldCloud sans
base IFA, les points d'accès répondent 503 au lieu de faire échouer le
démarrage.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.conf import settings
from django.db import DatabaseError, connections, transaction

from qfieldcloud.ifa.exceptions import BaseIfaIndisponibleError

logger = logging.getLogger(__name__)

# Un nom de schéma ne peut pas voyager comme paramètre de requête : il est
# concaténé dans le SQL. Il vient de la configuration (donc de confiance), mais
# on vérifie tout de même sa forme — une faute de frappe vaut mieux qu'une
# injection.
NOM_SCHEMA_VALIDE = re.compile(r"^[a-z_][a-z0-9_]*$")


def est_configuree() -> bool:
    """Vrai si l'alias de la base IFA a été déclaré au démarrage."""
    return settings.IFA_DB_ALIAS in settings.DATABASES


def schema() -> str:
    """Nom du schéma métier, validé, prêt à être concaténé dans du SQL."""
    nom = settings.IFA_DB_SCHEMA

    if not NOM_SCHEMA_VALIDE.match(nom):
        raise BaseIfaIndisponibleError(
            f"Le schéma IFA configuré est invalide : {nom!r}.",
        )

    return nom


@contextmanager
def curseur() -> Iterator[Any]:
    """Curseur sur la base IFA, dans une transaction en lecture seule."""
    if not est_configuree():
        raise BaseIfaIndisponibleError(
            "La base de données IFA n'est pas configurée sur ce serveur "
            "(variable VALIDATION_PG_HOST absente).",
        )

    alias = settings.IFA_DB_ALIAS
    delai_ms = int(settings.IFA_DB_STATEMENT_TIMEOUT_MS)

    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cur:
                # `SET LOCAL` n'accepte pas de paramètre lié ; la valeur est un
                # entier issu de la configuration, converti juste au-dessus.
                cur.execute(f"SET LOCAL statement_timeout = {delai_ms}")
                cur.execute("SET TRANSACTION READ ONLY")
                yield cur
    except BaseIfaIndisponibleError:
        raise
    except DatabaseError as erreur:
        # Le détail (hôte, requête, schéma) part au journal, pas au client.
        logger.exception("Interrogation de la base IFA en échec")
        raise BaseIfaIndisponibleError(
            "La base de données IFA n'a pas répondu.",
        ) from erreur


@contextmanager
def curseur_ecriture() -> Iterator[Any]:
    """Curseur sur la base IFA, en écriture.

    Contrepartie de `curseur()`, et seule porte d'écriture du module. Trois
    usages : le verrouillage d'une unité — sans quoi deux techniciens
    ouvriraient la même —, la création d'une nouvelle unité, qui réserve son
    code au moment où le technicien la déclare, la création, la
    modification et la suppression d'un projet de sondage dans `proje_sonda`,
    avec ses types d'UE dans `proje_type_unite_echan`, et la suppression d'une
    unité avec toutes ses données de terrain.

    La transaction reste celle de Django (`transaction.atomic`) : une erreur
    levée dans le bloc annule l'`UPDATE`. Le délai maximal est le même que pour
    une lecture — un `UPDATE` sur clé primaire qui dépasse vingt secondes est
    un incident, pas une requête lente.
    """
    if not est_configuree():
        raise BaseIfaIndisponibleError(
            "La base de données IFA n'est pas configurée sur ce serveur "
            "(variable VALIDATION_PG_HOST absente).",
        )

    alias = settings.IFA_DB_ALIAS
    delai_ms = int(settings.IFA_DB_STATEMENT_TIMEOUT_MS)

    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = {delai_ms}")
                yield cur
    except BaseIfaIndisponibleError:
        raise
    except DatabaseError as erreur:
        logger.exception("Écriture dans la base IFA en échec")
        raise BaseIfaIndisponibleError(
            "La base de données IFA n'a pas accepté la mise à jour.",
        ) from erreur


def lignes_en_dictionnaires(cur: Any) -> list[dict[str, Any]]:
    """Résultat d'un `SELECT` sous forme de liste de dictionnaires."""
    colonnes = [description[0] for description in cur.description]
    return [dict(zip(colonnes, ligne)) for ligne in cur.fetchall()]
