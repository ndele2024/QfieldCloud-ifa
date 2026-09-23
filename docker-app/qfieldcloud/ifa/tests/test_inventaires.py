"""Copie des inventaires : appariement des tables, des colonnes, et filtre.

Le curseur PostgreSQL est ici une doublure qui enregistre les requêtes reçues :
ce qu'on veut vérifier, c'est la forme de ce que le module demande à la base —
le filtre sur l'unité, la présence des bornes à côté de la géométrie, et les
colonnes retenues. Le comportement de PostgreSQL lui-même n'est pas en cause.
"""

import sqlite3
import struct
import tempfile

from django.test import SimpleTestCase

from qfieldcloud.ifa import gpkg, inventaires
from qfieldcloud.ifa.paquet import Correspondance

POINT_WKB = struct.pack("<BI2d", 1, 1, 100.0, 200.0)


def correspondance(table_pg, table_gpkg, schema="ifa_qfield"):
    return Correspondance(
        id_couche=f"{table_pg}_001",
        nom=table_pg,
        table_gpkg=table_gpkg,
        schema_pg=schema,
        table_pg=table_pg,
        cle="qgis_id",
    )


class CurseurDouble:
    """Curseur minimal : retient les requêtes et rend des lignes préparées."""

    def __init__(self, reponses=None):
        self.requetes = []
        self.reponses = reponses or {}
        self._restant = []

    def execute(self, requete, parametres=None):
        self.requetes.append((" ".join(requete.split()), parametres))

        for motif, lignes in self.reponses.items():
            if motif in requete:
                self._restant = list(lignes)
                return

        self._restant = []

    def fetchmany(self, taille):
        lot, self._restant = self._restant[:taille], self._restant[taille:]
        return lot

    def fetchall(self):
        lignes, self._restant = self._restant, []
        return lignes


class DedupliquerTestCase(SimpleTestCase):
    def test_une_entree_par_table_du_geopackage(self):
        """92 couches pour 37 tables : sans cela, chaque ligne serait copiée 2 ou 3 fois."""
        retenues = inventaires._dedupliquer(
            [
                correspondance("mesurage", "c0913e60"),
                correspondance("mesurage", "c0913e60"),
                correspondance("veget", "ad54240c"),
            ]
        )

        self.assertEqual(len(retenues), 2)
        self.assertEqual({c.table_pg for c in retenues}, {"mesurage", "veget"})

    def test_premiere_retenue_en_cas_de_desaccord(self):
        retenues = inventaires._dedupliquer(
            [
                correspondance("mesurage", "c0913e60"),
                correspondance("autre_table", "c0913e60"),
            ]
        )

        self.assertEqual(len(retenues), 1)
        self.assertEqual(retenues[0].table_pg, "mesurage")

    def test_liste_vide(self):
        self.assertEqual(inventaires._dedupliquer([]), [])


class ExpressionsGeometrieTestCase(SimpleTestCase):
    def test_wkb_et_quatre_bornes(self):
        expressions = inventaires._expressions_geometrie("shape", 32187)

        self.assertEqual(len(expressions), 5)
        self.assertEqual(expressions[0], 'ST_AsBinary("shape")')
        self.assertEqual(expressions[1], 'ST_XMin("shape")')
        self.assertEqual(expressions[4], 'ST_YMax("shape")')

    def test_pas_de_reprojection_quand_les_srid_concordent(self):
        for expression in inventaires._expressions_geometrie("shape", 32187):
            self.assertNotIn("ST_Transform", expression)

    def test_reprojection_quand_le_geopackage_diverge(self):
        expressions = inventaires._expressions_geometrie("shape", 3857)

        self.assertIn('ST_Transform("shape", 3857)', expressions[0])


class ColonneGeometrieTestCase(SimpleTestCase):
    def test_reperee_par_son_type(self):
        colonnes = {"une_code_ident": "varchar", "shape": "geometry", "qgis_id": "int8"}

        self.assertEqual(inventaires._colonne_geometrie(colonnes), "shape")

    def test_absente(self):
        self.assertIsNone(inventaires._colonne_geometrie({"code": "varchar"}))


class CopierTableTestCase(SimpleTestCase):
    """Assemblage du `SELECT` et écriture dans un GeoPackage réel."""

    def setUp(self):
        fichier = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
        fichier.close()
        self.chemin = fichier.name

        connexion = sqlite3.connect(self.chemin)
        connexion.executescript(
            """
            CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER);
            CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER);
            CREATE TABLE points (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB,
                                 une_code_ident TEXT, mes_no_seq REAL, qgis_id INTEGER);
            INSERT INTO gpkg_contents VALUES ('points', 'features', 32187);
            INSERT INTO gpkg_geometry_columns VALUES ('points', 'geom', 32187);
            """
        )
        connexion.commit()
        connexion.close()

        self.connexion = gpkg.ouvrir(self.chemin)
        self.addCleanup(self._nettoyer)

    def _nettoyer(self):
        import os

        self.connexion.close()

        try:
            os.unlink(self.chemin)
        except OSError:
            pass

    def test_filtre_sur_l_unite_et_geometrie_encodee(self):
        curseur = CurseurDouble(
            {
                "FROM ifa_data": [
                    ("02-12777-IPE", 1.0, 42, POINT_WKB, 100.0, 100.0, 200.0, 200.0)
                ]
            }
        )

        ecrites = inventaires._copier_table(
            curseur,
            self.connexion,
            "ifa_data",
            "mesurage",
            "points",
            ["une_code_ident", "mes_no_seq", "qgis_id"],
            ("geom", 32187),
            "shape",
            inventaires.Selection.pour_unite("02-12777-IPE", 1000),
        )

        self.assertEqual(ecrites, 1)

        requete, parametres = curseur.requetes[0]
        self.assertIn('WHERE "une_code_ident" = %s', requete)
        self.assertEqual(parametres, ["02-12777-IPE"])
        self.assertIn('ST_AsBinary("shape")', requete)
        self.assertIn('ST_XMin("shape")', requete)

        ligne = self.connexion.execute(
            "SELECT une_code_ident, qgis_id, geom FROM points"
        ).fetchone()
        self.assertEqual(ligne[0], "02-12777-IPE")
        self.assertEqual(ligne[1], 42)
        self.assertEqual(ligne[2][:2], b"GP")

    def test_referentiel_copie_en_entier(self):
        """Une table sans `une_code_ident` n'est pas filtrée."""
        curseur = CurseurDouble({"FROM ifa_data": [("A", 1.0, 1), ("B", 2.0, 2)]})

        ecrites = inventaires._copier_table(
            curseur,
            self.connexion,
            "ifa_data",
            "type_unite_echan",
            "points",
            ["une_code_ident", "mes_no_seq", "qgis_id"],
            None,
            None,
            None,
        )

        self.assertEqual(ecrites, 2)

        requete, parametres = curseur.requetes[0]
        self.assertNotIn("WHERE", requete)
        self.assertEqual(parametres, [])

    def test_selection_sur_plusieurs_unites(self):
        """« Créer une UE » embarque les unités d'une région ou d'une emprise."""
        curseur = CurseurDouble({"FROM ifa_data": [("A", 1.0, 1), ("B", 2.0, 2)]})

        ecrites = inventaires._copier_table(
            curseur,
            self.connexion,
            "ifa_data",
            "mesurage",
            "points",
            ["une_code_ident", "mes_no_seq", "qgis_id"],
            None,
            None,
            inventaires.Selection.pour_unites(["A", "B"], "région 02", 1000),
        )

        self.assertEqual(ecrites, 2)

        requete, parametres = curseur.requetes[0]
        self.assertIn('WHERE "une_code_ident" = ANY(%s)', requete)
        self.assertEqual(parametres, [["A", "B"]])

    def test_geometrie_nulle_conservee_nulle(self):
        curseur = CurseurDouble(
            {"FROM ifa_data": [("A", 1.0, 1, None, None, None, None, None)]}
        )

        inventaires._copier_table(
            curseur,
            self.connexion,
            "ifa_data",
            "mesurage",
            "points",
            ["une_code_ident", "mes_no_seq", "qgis_id"],
            ("geom", 32187),
            "shape",
            None,
        )

        self.assertIsNone(
            self.connexion.execute("SELECT geom FROM points").fetchone()[0]
        )


class StructurePostgresqlTestCase(SimpleTestCase):
    def test_regroupement_par_table(self):
        curseur = CurseurDouble(
            {
                "pg_attribute": [
                    ("mesurage", "une_code_ident", "varchar"),
                    ("mesurage", "shape", "geometry"),
                    ("veget", "une_code_ident", "varchar"),
                ]
            }
        )

        structure = inventaires._structure_postgresql(
            curseur, "ifa_data", {"mesurage", "veget"}
        )

        self.assertEqual(structure["mesurage"]["shape"], "geometry")
        self.assertEqual(set(structure), {"mesurage", "veget"})

    def test_aucune_table_demandee(self):
        curseur = CurseurDouble()

        self.assertEqual(
            inventaires._structure_postgresql(curseur, "ifa_data", set()), {}
        )
        self.assertEqual(curseur.requetes, [])
