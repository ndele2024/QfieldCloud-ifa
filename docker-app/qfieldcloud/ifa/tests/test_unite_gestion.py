"""Supprimer une unité : les droits et l'ordre de suppression, sans la base.

Deux choses cassent sans bruit. Les droits : un technicien qui supprime
l'unité d'un collègue ne déclenche aucune erreur. Et l'ordre : une table
oubliée ou mal placée fait échouer chaque suppression sur une clé étrangère
— ou, sans clé, laisse des lignes orphelines.
"""

from unittest import mock

from django.test import SimpleTestCase

from qfieldcloud.ifa import db, unite_gestion
from qfieldcloud.ifa.exceptions import MotDePasseInvalideError

# Les clés étrangères de `ifa_data` entre tables de données d'unité, enfant →
# parent, relevées sur la base (information_schema.referential_constraints).
CLES_ETRANGERES = {
    ("espec_amena", "amenagement"),
    ("profi_mesur", "analy_physi_chimi"),
    ("resul_analy_physi_chimi", "analy_physi_chimi"),
    ("titra_alcal", "analy_physi_chimi"),
    ("facie", "carac_envir_lotiq"),
    ("forme_envir_struc", "carac_envir_lotiq"),
    ("geome_longi", "carac_envir_lotiq"),
    ("geome_trans", "carac_envir_lotiq"),
    ("granu_lit", "carac_envir_lotiq"),
    ("mobilite", "carac_envir_lotiq"),
    ("trans_vites", "carac_envir_lotiq"),
    ("veget", "carac_envir_lotiq"),
    ("forme_descr_habit", "descr_habit"),
    ("anoma_speci", "detail_speci"),
    ("marqu_ensem", "ensemencement"),
    ("espec_habit", "habitat"),
    ("forme_eleme_habit", "habitat"),
    ("recou_espec_veget_aquat", "habitat"),
    ("amenagement", "mesurage"),
    ("analy_physi_chimi", "mesurage"),
    ("autre_obser_fauni", "mesurage"),
    ("carac_envir_lotiq", "mesurage"),
    ("descr_habit", "mesurage"),
    ("detai_speci_mosa", "mesurage"),
    ("ensemencement", "mesurage"),
    ("equipe", "mesurage"),
    ("habitat", "mesurage"),
    ("infor_gener", "mesurage"),
    ("infor_peche_sport", "mesurage"),
    ("labo_obser", "mesurage"),
    ("peche_exper", "mesurage"),
    ("perturbation", "mesurage"),
    ("plan_eau_conve", "mesurage"),
    ("quota_peche_sport", "mesurage"),
    ("recol_peche_sport", "mesurage"),
    ("resea_suivi_angui", "mesurage"),
    ("suiv_tempe", "mesurage"),
    ("suivi_recru_mosa", "mesurage"),
    ("pose_levee_filet", "peche_exper"),
    ("denom_espec", "pose_levee_filet"),
    ("detail_speci", "pose_levee_filet"),
    ("descr_speci_peche_sport", "recol_peche_sport"),
}


def unite(createur="kamdo1", verrou="N", detenteur=""):
    return {
        "une_code_ident": "02-12777-IPE",
        "une_code_utili_creat": createur,
        "une_ind_verro": verrou,
        "une_nom_propr_verro": detenteur,
    }


class OrdreTestCase(SimpleTestCase):
    def test_chaque_enfant_part_avant_son_parent(self):
        rang = {t: i for i, t in enumerate(unite_gestion.TABLES_DONNEES)}
        for enfant, parent in sorted(CLES_ETRANGERES):
            with self.subTest(enfant=enfant, parent=parent):
                self.assertLess(rang[enfant], rang[parent])

    def test_toutes_les_tables_une_seule_fois(self):
        tables = unite_gestion.TABLES_DONNEES
        self.assertEqual(len(tables), len(set(tables)))
        attendues = {t for paire in CLES_ETRANGERES for t in paire}
        self.assertEqual(set(tables), attendues)
        self.assertEqual(len(tables), 43, "42 tables de données + mesurage")

    def test_mesurage_en_dernier_l_unite_a_part(self):
        self.assertEqual(unite_gestion.TABLES_DONNEES[-1], "mesurage")
        self.assertNotIn(unite_gestion.TABLE_UNITE, unite_gestion.TABLES_DONNEES)


class DroitsTestCase(SimpleTestCase):
    def test_createur_unite_non_diffusee(self):
        d = unite_gestion.droits(unite(), "KAMDO1", False, False)
        self.assertTrue(d["createur"], "la casse ne compte pas")
        self.assertTrue(d["supprimable"])

    def test_createur_unite_diffusee_refuse(self):
        d = unite_gestion.droits(unite(), "kamdo1", False, True)
        self.assertFalse(d["supprimable"])
        self.assertIn("diffusées", d["raison_suppression"])

    def test_autre_utilisateur_refuse_et_createur_nomme(self):
        d = unite_gestion.droits(unite(), "robma8", False, False)
        self.assertFalse(d["supprimable"])
        self.assertIn("kamdo1", d["raison_suppression"])

    def test_admin_supprime_tout(self):
        for diffusee in (False, True):
            with self.subTest(diffusee=diffusee):
                d = unite_gestion.droits(unite(createur="x"), "chef", True, diffusee)
                self.assertTrue(d["supprimable"])

    def test_verrouillee_par_un_autre_jamais(self):
        for admin in (False, True):
            with self.subTest(admin=admin):
                d = unite_gestion.droits(
                    unite(verrou="O", detenteur="robma8"), "kamdo1", admin, False
                )
                self.assertFalse(d["supprimable"])
                self.assertIn("robma8", d["raison_suppression"])

    def test_verrouillee_par_soi_supprimable(self):
        """Le cas d'une unité créée par erreur : elle naît verrouillée à son nom."""
        d = unite_gestion.droits(
            unite(verrou="O", detenteur="kamdo1"), "kamdo1", False, False
        )
        self.assertTrue(d["supprimable"])

    def test_createur_inconnu(self):
        d = unite_gestion.droits(unite(createur=""), "", False, False)
        self.assertFalse(d["createur"])
        self.assertFalse(d["supprimable"])


class SuppressionTestCase(SimpleTestCase):
    def test_mot_de_passe_verifie_avant_la_base(self):
        utilisateur = mock.Mock(username="kamdo1")
        utilisateur.check_password.return_value = False

        with (
            mock.patch.object(db, "curseur_ecriture") as ecriture,
            mock.patch.object(db, "curseur") as lecture,
        ):
            with self.assertRaises(MotDePasseInvalideError) as erreur:
                unite_gestion.supprimer("02-12777-IPE", utilisateur, "faux")

        ecriture.assert_not_called()
        lecture.assert_not_called()
        self.assertIn("unité", erreur.exception.message)

    def test_mot_de_passe_vide(self):
        utilisateur = mock.Mock(username="kamdo1")
        with self.assertRaises(MotDePasseInvalideError):
            unite_gestion.supprimer("02-12777-IPE", utilisateur, "")
        utilisateur.check_password.assert_not_called()

    def test_code_trop_long(self):
        from qfieldcloud.ifa.exceptions import FiltreInvalideError

        with self.assertRaises(FiltreInvalideError):
            unite_gestion.valider_code("x" * 41)
