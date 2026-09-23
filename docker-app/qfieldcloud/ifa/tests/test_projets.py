"""Préparation d'un projet : ce qui se décide sans QFieldCloud ni GDAL.

La préparation elle-même demande un projet modèle packagé, une base et un
travailleur QGIS. Ce qui se casse silencieusement, en revanche, c'est
l'appariement des empreintes de tables avec leur nom métier — et c'est lui qui
décide si l'étape de validation reconnaîtra le GeoPackage livré.
"""

from django.test import SimpleTestCase

from qfieldcloud.ifa import projets
from qfieldcloud.ifa.paquet import Correspondance


def correspondance(table_pg, table_gpkg, schema="ifa_qfield"):
    return Correspondance(
        id_couche=f"{table_pg}_001",
        nom=table_pg,
        table_gpkg=table_gpkg,
        schema_pg=schema,
        table_pg=table_pg,
        cle="fid",
    )


class TablesMetierTestCase(SimpleTestCase):
    def test_une_empreinte_par_table(self):
        renommages = projets._tables_metier(
            [
                correspondance("mesurage", "c0913e60"),
                correspondance("infor_gener", "7d83cbe7"),
            ]
        )

        self.assertEqual(
            renommages, {"c0913e60": "mesurage", "7d83cbe7": "infor_gener"}
        )

    def test_plusieurs_couches_sur_la_meme_table(self):
        """92 couches pour 37 tables : le cas ordinaire du projet modèle."""
        renommages = projets._tables_metier(
            [
                correspondance("mesurage", "c0913e60"),
                correspondance("mesurage", "c0913e60"),
                correspondance("mesurage", "c0913e60"),
            ]
        )

        self.assertEqual(renommages, {"c0913e60": "mesurage"})

    def test_deux_empreintes_pour_une_table_sont_laissees_de_cote(self):
        """Les renommer donnerait deux tables du même nom : le GeoPackage refuse."""
        renommages = projets._tables_metier(
            [
                correspondance("mesurage", "c0913e60"),
                correspondance("mesurage", "ad54240c"),
                correspondance("veget", "fd6a1efe"),
            ]
        )

        self.assertEqual(renommages, {"fd6a1efe": "veget"})

    def test_aucune_correspondance(self):
        self.assertEqual(projets._tables_metier([]), {})


class NomGeoPackageTestCase(SimpleTestCase):
    def test_le_nom_differe_de_celui_du_convertisseur(self):
        """Toute la raison d'être du renommage de fichier."""
        self.assertNotEqual(projets.NOM_GEOPACKAGE, "data.gpkg")
