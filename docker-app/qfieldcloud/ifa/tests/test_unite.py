"""Création d'une unité : ce qui se décide sans la base.

L'`INSERT` lui-même demande PostgreSQL. Ce qui se casse silencieusement, en
revanche, c'est la règle de reprise : reconnaître sa propre création
interrompue, et refuser une unité du fonds. C'est ce que ces essais tiennent.
"""

from unittest import mock

from django.test import SimpleTestCase

from qfieldcloud.ifa import unite, verrou
from qfieldcloud.ifa.exceptions import (
    FiltreInvalideError,
    TypeUniteIntrouvableError,
    UniteExistanteError,
)


def ligne(
    code="02-12777-IPE",
    verrouillee="O",
    proprietaire="ifauser",
    raison=unite.RAISON_CREATION,
):
    return {
        "une_code_ident": code,
        "une_ind_verro": verrouillee,
        "une_nom_propr_verro": proprietaire,
        "une_date_verro": "",
        "une_raiso_verro": raison,
    }


class CodeTestCase(SimpleTestCase):
    def test_code_absent(self):
        with self.assertRaises(FiltreInvalideError):
            unite.creer("   ", "Inventaire sur plan d'eau", "ifauser")

    def test_code_trop_long(self):
        with self.assertRaises(FiltreInvalideError):
            unite.creer("x" * 41, "Inventaire sur plan d'eau", "ifauser")


class TypeTestCase(SimpleTestCase):
    def test_type_absent(self):
        with self.assertRaises(TypeUniteIntrouvableError):
            unite.type_par_nom("")


class ReprendreTestCase(SimpleTestCase):
    """Le code existe déjà : reprise, ou unité du fonds ?"""

    def test_sa_propre_creation_est_reprise(self):
        """Une préparation qui a échoué ne doit pas bloquer la suivante."""
        with mock.patch.object(verrou, "lire", return_value=ligne()):
            reprise = unite._reprendre("02-12777-IPE", "ifauser")

        self.assertEqual(reprise["une_code_ident"], "02-12777-IPE")

    def test_unite_du_fonds_refusee(self):
        """Une unité existante, non verrouillée : c'est celle de 2009."""
        with mock.patch.object(
            verrou,
            "lire",
            return_value=ligne(verrouillee="N", proprietaire="", raison=""),
        ):
            with self.assertRaises(UniteExistanteError) as erreur:
                unite._reprendre("02-12777-IPE", "ifauser")

        self.assertIn("existe déjà", erreur.exception.message)

    def test_unite_tenue_par_un_autre_nomme_son_detenteur(self):
        with mock.patch.object(
            verrou, "lire", return_value=ligne(proprietaire="kamdo1", raison="Saisie")
        ):
            with self.assertRaises(UniteExistanteError) as erreur:
                unite._reprendre("02-12777-IPE", "ifauser")

        self.assertIn("kamdo1", erreur.exception.message)

    def test_meme_proprietaire_mais_autre_raison(self):
        """Mon verrou, mais posé par une ouverture : ce n'est pas une création."""
        with mock.patch.object(
            verrou, "lire", return_value=ligne(raison="Saisie des données en cours")
        ):
            with self.assertRaises(UniteExistanteError):
                unite._reprendre("02-12777-IPE", "ifauser")


class RaisonTestCase(SimpleTestCase):
    def test_la_raison_est_celle_demandee(self):
        """Le libellé est lu par les autres équipes : il ne s'improvise pas."""
        self.assertEqual(unite.RAISON_CREATION, "nouvelle Unité d'échantillonnage")

    def test_la_raison_tient_dans_la_colonne(self):
        self.assertLessEqual(len(unite.RAISON_CREATION), verrou.LONGUEUR_RAISON)
