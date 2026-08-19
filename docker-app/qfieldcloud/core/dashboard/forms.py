"""Formulaires du tableau de bord."""

from allauth.account.models import EmailAddress
from django import forms

from qfieldcloud.core.models import Person


class ProfileForm(forms.ModelForm):
    """Informations personnelles modifiables par l'utilisateur lui-même.

    `username` en est volontairement absent : il apparaît dans les chemins de
    stockage des projets et dans les noms d'équipe (`@organisation/equipe`).
    Le renommer depuis cet écran laisserait des références pendantes ; cela
    reste une opération d'administration.
    """

    class Meta:
        model = Person
        fields = [
            "first_name",
            "last_name",
            "email",
            "has_newsletter_subscription",
        ]
        labels = {
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Adresse e-mail",
            "has_newsletter_subscription": "Recevoir la lettre d'information",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")

        self.fields["email"].required = True

    def clean_email(self):
        """Refuse une adresse déjà rattachée à un autre compte.

        `Person.clean()` couvre déjà le champ `User.email`, mais allauth tient
        sa propre table `EmailAddress` (adresses secondaires comprises), avec
        une contrainte d'unicité. Sans cette vérification, l'enregistrement
        échouerait plus loin sur une IntegrityError au lieu d'un message clair.
        """
        email = self.cleaned_data["email"]

        conflict = (
            EmailAddress.objects.filter(email__iexact=email)
            .exclude(user_id=self.instance.pk)
            .exists()
        )
        if conflict:
            raise forms.ValidationError(
                "Cette adresse e-mail est déjà utilisée par un autre compte."
            )

        return email

    def save(self, commit=True):
        user = super().save(commit=commit)

        if commit and "email" in self.changed_data:
            self._sync_allauth_email(user)

        return user

    def _sync_allauth_email(self, user) -> None:
        """Répercute le changement d'adresse dans la table d'allauth.

        `ACCOUNT_LOGIN_METHODS` autorise la connexion par e-mail, et allauth
        n'interroge pas `User.email` mais sa propre table `EmailAddress`. Sans
        cette synchronisation, l'utilisateur continuerait à se connecter avec
        son ANCIENNE adresse et pas avec la nouvelle.

        L'adresse est remise à « non vérifiée », ce qu'elle est réellement.
        La vérification étant configurée en `optional`, cela ne bloque pas la
        connexion.
        """
        address = EmailAddress.objects.filter(user=user, primary=True).first()

        if address is None:
            EmailAddress.objects.create(
                user=user,
                email=user.email,
                primary=True,
                verified=False,
            )
            return

        address.email = user.email
        address.verified = False
        address.save(update_fields=["email", "verified"])
