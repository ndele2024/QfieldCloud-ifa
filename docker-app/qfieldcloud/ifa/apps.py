from django.apps import AppConfig


class IfaConfig(AppConfig):
    """Points d'accès propres au programme IFA 2.0.

    L'application ne définit aucun modèle : la base métier (`ifa`) est celle
    du ministère, QFieldCloud l'interroge en lecture seule et n'en administre
    ni le schéma ni les migrations. Voir `db.py`.
    """

    name = "qfieldcloud.ifa"
    verbose_name = "IFA"
