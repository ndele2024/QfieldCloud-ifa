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


class UniteIntrouvableError(QFieldCloudException):
    """Le code d'unité demandé n'existe pas dans la base métier."""

    code = "ifa_unite_introuvable"
    message = "Unité d'échantillonnage introuvable."
    status_code = status.HTTP_404_NOT_FOUND
    log_as_error = False

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)


class UniteExistanteError(QFieldCloudException):
    """Le code de la nouvelle unité est déjà porté par une unité de la base.

    Le cas est fréquent et n'a rien d'anormal : l'identifiant est composé de la
    région, du n° de plan d'eau et du type d'UE, et le fonds porte déjà des
    unités de 2009 sur les mêmes plans d'eau. Le message doit donc dire quoi
    faire — modifier l'identifiant — plutôt que constater l'échec.
    """

    code = "ifa_unite_existante"
    message = "Une unité d'échantillonnage porte déjà ce code."
    status_code = status.HTTP_409_CONFLICT
    log_as_error = False

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)


class TypeUniteIntrouvableError(QFieldCloudException):
    """Le type d'UE demandé n'existe pas dans `type_unite_echan`.

    `unite_echan.tue_code_ident` porte une clé étrangère vers ce référentiel :
    une unité ne peut pas être créée sans un type qui existe. La liste des
    types est encore codée en dur dans le plugin, d'où la possibilité d'un
    désaccord avec la base — que ce message doit rendre lisible.
    """

    code = "ifa_type_unite_introuvable"
    message = "Type d'unité d'échantillonnage inconnu de la base IFA."
    status_code = status.HTTP_400_BAD_REQUEST
    log_as_error = False

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)


class UniteVerrouilleeError(QFieldCloudException):
    """L'unité est déjà tenue par quelqu'un d'autre.

    Le cas est normal sur le terrain — deux équipes visent le même plan d'eau —
    et le message doit nommer le détenteur : c'est la seule information qui
    permette au technicien de savoir à qui s'adresser.
    """

    code = "ifa_unite_verrouillee"
    message = "Cette unité est verrouillée par un autre utilisateur."
    status_code = status.HTTP_409_CONFLICT
    log_as_error = False

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)


class TravauxNonSynchronisesError(QFieldCloudException):
    """Le projet d'affichage porte des modifications qui n'ont pas été appliquées.

    Ouvrir une autre unité remplacerait le `data.gpkg` du projet : les
    modifications faites sur le terrain et jamais synchronisées seraient
    perdues sans que rien ne les rappelle.
    """

    code = "ifa_travaux_non_synchronises"
    message = (
        "Des modifications de l'unité précédente ne sont pas encore "
        "synchronisées : synchronisez-les avant d'ouvrir une autre unité."
    )
    status_code = status.HTTP_409_CONFLICT
    log_as_error = False

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)


class ProjetModeleInvalideError(QFieldCloudException):
    """Le projet modèle est absent, jamais packagé, ou illisible.

    C'est une erreur d'installation, pas une erreur du client : le projet
    modèle est désigné par la configuration du serveur et doit avoir été
    packagé au moins une fois.
    """

    code = "ifa_projet_modele_invalide"
    message = "Le projet modèle IFA n'est pas exploitable sur ce serveur."
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, message: str = "", detail: str = ""):
        if message:
            self.message = message
        super().__init__(detail=detail or self.message)
