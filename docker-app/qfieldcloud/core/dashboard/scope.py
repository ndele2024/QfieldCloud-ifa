"""Périmètre de visibilité du tableau de bord.

Une seule question est traitée ici : quels projets un utilisateur a-t-il le
droit de voir ? Tout le reste du tableau de bord s'appuie dessus — y compris le
contrôle d'accès de la vue de détail — pour qu'il n'existe qu'UN endroit à
modifier le jour où la règle change.

Règle actuelle : est visible tout projet sur lequel une synchronisation (un
`Job`) a été lancée soit par l'utilisateur lui-même, soit par un membre d'une
des équipes auxquelles il appartient.

Le rattachement se fait donc par l'activité réelle (`Job.created_by`) et non
par la propriété du projet : un technicien qui synchronise un projet d'équipe
n'en est pas propriétaire, mais c'est bien ce projet-là qui l'intéresse.
"""

from django.db.models import OuterRef, Q, QuerySet, Subquery

from qfieldcloud.core.models import Job, Project, Team, TeamMember


def user_teams(user) -> QuerySet[Team]:
    """Équipes auxquelles l'utilisateur appartient."""
    return Team.objects.filter(members__member=user)


def teammate_ids(user):
    """Identifiants des coéquipiers, l'utilisateur lui-même exclu.

    L'exclusion est ce qui permet de séparer proprement « mes projets » de
    « ceux des équipes » : sans elle, tout projet personnel réapparaîtrait
    dans la liste des équipes.
    """
    return (
        TeamMember.objects.filter(team__in=user_teams(user))
        .exclude(member=user)
        .values_list("member_id", flat=True)
    )


def own_project_ids(user):
    """Projets synchronisés par l'utilisateur."""
    return Job.objects.filter(created_by=user).values_list("project_id", flat=True)


def team_project_ids(user):
    """Projets synchronisés par les coéquipiers."""
    return Job.objects.filter(created_by__in=teammate_ids(user)).values_list(
        "project_id", flat=True
    )


def with_last_sync(qs: QuerySet[Project]) -> QuerySet[Project]:
    """Ajoute la dernière synchronisation connue de chaque projet.

    Renseigne `last_sync_at`, `last_sync_by` et `last_sync_type` en une seule
    requête. `Project.updated_at` ne dit que « quelque chose a changé » sans
    dire par qui : c'est le dernier `Job` qui porte cette information.
    """
    latest = Job.objects.filter(project=OuterRef("pk")).order_by("-created_at")

    return qs.annotate(
        last_sync_at=Subquery(latest.values("created_at")[:1]),
        last_sync_by=Subquery(latest.values("created_by__username")[:1]),
        last_sync_type=Subquery(latest.values("type")[:1]),
    )


def own_projects(user) -> QuerySet[Project]:
    return with_last_sync(
        Project.objects.filter(id__in=own_project_ids(user)).select_related("owner")
    ).order_by("-updated_at")


def team_projects(user) -> QuerySet[Project]:
    return with_last_sync(
        Project.objects.filter(id__in=team_project_ids(user))
        .exclude(id__in=own_project_ids(user))
        .select_related("owner")
    ).order_by("-updated_at")


def visible_projects(user) -> QuerySet[Project]:
    """Union des deux listes.

    Sert de contrôle d'accès à la vue de détail : un projet absent de ce
    queryset renvoie 404, ce qui évite d'avoir à redire la règle ailleurs.
    """
    return Project.objects.filter(
        Q(id__in=own_project_ids(user)) | Q(id__in=team_project_ids(user))
    )
