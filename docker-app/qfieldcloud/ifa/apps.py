from django.apps import AppConfig


class IfaConfig(AppConfig):
    """Points d'accès propres au programme IFA 2.0.

    L'application ne définit aucun modèle : la base métier (`ifa`) est celle
    du ministère, QFieldCloud n'en administre ni le schéma ni les migrations.
    Elle l'interroge en lecture seule, à une exception près — le verrouillage
    d'une unité d'échantillonnage, qui écrit quatre colonnes de `unite_echan`.
    Voir `db.py` et `verrou.py`.
    """

    name = "qfieldcloud.ifa"
    verbose_name = "IFA"
