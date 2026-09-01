from typing import Any

from django.conf import settings


class IfaDatabaseRouter:
    """Tient la base IFA hors de portée de l'ORM et des migrations.

    La base `ifa` est une base de production existante, partagée avec d'autres
    applications du ministère. QFieldCloud ne doit ni y créer de tables, ni y
    déplacer les tables de Django : le routeur renvoie donc systématiquement
    `False` pour `allow_migrate` sur cet alias, et `False` pour toute migration
    qui viserait la base par défaut alors qu'elle appartient à l'alias IFA.

    L'accès se fait exclusivement en SQL brut depuis `qfieldcloud.ifa.db`.
    """

    def db_for_read(self, model: Any, **hints: Any) -> str | None:
        return None

    def db_for_write(self, model: Any, **hints: Any) -> str | None:
        return None

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        return None

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool | None:
        if db == settings.IFA_DB_ALIAS:
            return False
        return None
