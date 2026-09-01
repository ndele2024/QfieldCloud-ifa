"""Erreurs des points d'accès IFA.

QFieldCloud renvoie ses erreurs sous la forme `{"code", "message"}` et laisse
tomber le détail hors mode DEBUG (voir `qfieldcloud.core.rest_utils`). Une
`ValidationError` de Django REST Framework y arriverait donc chez le client
sous le seul libellé « API Error » — inexploitable pour un technicien sur le
terrain, qui n'a ni le journal du serveur ni personne à qui le demander.

Les erreurs ci-dessous portent donc leur message dans le champ `message`,
rédigé pour être affiché tel quel dans la fenêtre du plugin.
"""

from __future__ import annotations

from rest_framework import status

from qfieldcloud.core.exceptions import QFieldCloudException


class FiltreInvalideError(QFieldCloudException):
    """Le filtre de recherche envoyé par le client n'est pas exploitable."""

    code = "ifa_filtre_invalide"
    message = "Filtre de recherche invalide"
    status_code = status.HTTP_400_BAD_REQUEST
    # Une saisie fautive n'est pas un incident du serveur.
    log_as_error = False

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)


class BaseIfaIndisponibleError(QFieldCloudException):
    """La base métier n'est pas configurée, pas joignable, ou trop lente."""

    code = "ifa_base_indisponible"
    message = "La base de données IFA n'est pas joignable."
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)
