"""Préparation du projet de saisie — ce qui peut se vérifier sans la base.

Le remplissage lui-même demande PostgreSQL et un paquet QFieldCloud ; ce qui se
casse silencieusement, en revanche, c'est le filtrage des variables de projet
et la construction de la sélection. C'est ce que ces essais tiennent.
"""

from django.test import SimpleTestCase

from qfieldcloud.ifa import formulaire, inventaires

REGION_02 = {"mode": "region", "valeur": "02"}
BASSIN_SAGUENAY = {"mode": "bassin", "valeur": "Saguenay"}


class VariablesRetenuesTestCase(SimpleTestCase):
    def test_seules_les_variables_attendues_passent(self):
        retenues = formulaire._variables_retenues(
            {
                "code_region": "02",
                "une_code_ident": "02-12777-IPE",
                "rm -rf": "n'importe quoi",
            }
        )

        self.assertEqual(
            retenues, {"code_region": "02", "une_code_ident": "02-12777-IPE"}
        )

    def test_les_vides_ne_sont_pas_posees(self):
        """Une variable vide masquerait l'expression de repli du formulaire."""
        retenues = formulaire._variables_retenues(
            {"code_region": "02", "code_lce": "", "code_projet": "   "}
        )

        self.assertEqual(retenues, {"code_region": "02"})

    def test_valeur_tronquee(self):
        retenues = formulaire._variables_retenues({"type_formulaire": "x" * 500})

        self.assertEqual(len(retenues["type_formulaire"]), formulaire.LONGUEUR_VARIABLE)

    def test_aucune_variable(self):
        self.assertEqual(formulaire._variables_retenues(None), {})
        self.assertEqual(formulaire._variables_retenues({}), {})


class LibelleFiltreTestCase(SimpleTestCase):
    def test_les_quatre_modes(self):
        self.assertIn("région 02", formulaire.libelle_filtre([REGION_02], 12))
        self.assertIn(
            "plan d'eau n° 12777",
            formulaire.libelle_filtre([{"mode": "lce", "valeur": "12777"}], 3),
        )
        self.assertIn("bassin", formulaire.libelle_filtre([BASSIN_SAGUENAY], 7))
        self.assertIn("emprise", formulaire.libelle_filtre([{"mode": "emprise"}], 0))

    def test_le_decompte_est_repris(self):
        self.assertIn("12 unité(s)", formulaire.libelle_filtre([REGION_02], 12))

    def test_les_criteres_croises_apparaissent_tous(self):
        """Le libellé sert de description au projet livré : il doit être entier."""
        libelle = formulaire.libelle_filtre([REGION_02, BASSIN_SAGUENAY], 7)

        self.assertEqual(libelle, "région 02 et bassin « Saguenay » — 7 unité(s)")

    def test_le_bassin_est_un_critere_de_selection(self):
        self.assertIn(formulaire.MODE_BASSIN, formulaire.MODES)
        # Le fragment de code d'unité n'en est pas un.
        self.assertNotIn("code", formulaire.MODES)


class SelectionTestCase(SimpleTestCase):
    def test_liste_d_unites(self):
        selection = inventaires.Selection.pour_unites(["A", "B"], "région 02", 1000)

        self.assertEqual(selection.condition, '"une_code_ident" = ANY(%s)')
        self.assertEqual(selection.parametres, [["A", "B"]])

    def test_unite_seule(self):
        selection = inventaires.Selection.pour_unite("02-12777-IPE", 50)

        self.assertEqual(selection.condition, '"une_code_ident" = %s')
        self.assertEqual(selection.parametres, ["02-12777-IPE"])
        self.assertEqual(selection.lignes_max, 50)

    def test_liste_vide_acceptee(self):
        """Créer une unité là où il n'y en a jamais eu est le cas normal."""
        selection = inventaires.Selection.pour_unites([], "emprise tracée", 1000)

        self.assertEqual(selection.parametres, [[]])
