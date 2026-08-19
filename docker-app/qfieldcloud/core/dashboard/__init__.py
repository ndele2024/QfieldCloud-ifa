"""Tableau de bord des utilisateurs « équipe ».

L'accueil de QFieldCloud redirige vers l'admin Django, qui n'affiche rien à un
compte `is_staff` dépourvu de permissions de modèle — d'où la page vide. Ce
paquet fournit à la place un espace autonome (projets, profil, mot de passe),
indépendant du système de permissions de l'admin.

Organisation :
    scope.py  — qui a le droit de voir quoi (règle métier, isolée)
    forms.py  — formulaires profil et mot de passe
    views.py  — vues
    urls.py   — routes, montées sur /dashboard/
"""
