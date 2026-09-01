"""Accès en lecture seule à la base métier IFA.

La base IFA (`ifa`, schéma `ifa_data`) est celle du ministère : elle existe
avant QFieldCloud, elle est alimentée par d'autres applications, et QFieldCloud
n'en est pas propriétaire. Trois conséquences, appliquées ici :

1. **Aucun modèle Django.** Le schéma hérité ne se plie pas aux conventions de
   l'ORM (clés composites, types énumérés, colonnes `shape` en EPSG:32187) et
   surtout : le décrire en modèles inviterait tôt ou tard une migration à s'y
   appliquer. Tout passe par du SQL brut, paramétré.
2. **Transaction en lecture seule.** `curseur()` ouvre un `SET TRANSACTION
   READ ONLY` : même un défaut de programmation ne peut pas écrire dans la base
   de production.
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


def lignes_en_dictionnaires(cur: Any) -> list[dict[str, Any]]:
    """Résultat d'un `SELECT` sous forme de liste de dictionnaires."""
    colonnes = [description[0] for description in cur.description]
    return [dict(zip(colonnes, ligne)) for ligne in cur.fetchall()]
