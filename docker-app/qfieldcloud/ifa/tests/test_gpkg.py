"""Encodage GeoPackage : en-tête des géométries et fonctions des déclencheurs.

Ces essais portent sur ce que le remplissage écrit réellement dans le fichier.
L'en-tête est la partie du format qu'il faut produire à la main, et c'est aussi
celle dont dépendent les déclencheurs de l'index R-Tree : une erreur d'un octet
y donnerait un GeoPackage que QGIS ouvre sans rien afficher.
"""

import sqlite3
import struct
import tempfile

from django.test import SimpleTestCase

from qfieldcloud.ifa import gpkg

# POINT(244533.1 5178623.3) en WKB petit-boutien, tel que `ST_AsBinary` le rend.
POINT_WKB = struct.pack("<BI2d", 1, 1, 244533.1, 5178623.3)
ENVELOPPE = (244533.1, 244533.1, 5178623.3, 5178623.3)


class EncoderGeometrieTestCase(SimpleTestCase):
    def test_entete_complet(self):
        blob = gpkg.encoder_geometrie(POINT_WKB, 32187, ENVELOPPE)

        self.assertEqual(blob[:2], b"GP")
        self.assertEqual(blob[2], 0)
        # Petit-boutien (0x01) et enveloppe XY (0x02).
        self.assertEqual(blob[3], 0x03)
        self.assertEqual(struct.unpack_from("<i", blob, 4)[0], 32187)
        # 8 octets d'en-tête, 32 d'enveloppe, puis le WKB inchangé.
        self.assertEqual(blob[40:], POINT_WKB)

    def test_enveloppe_relue(self):
        blob = gpkg.encoder_geometrie(POINT_WKB, 32187, ENVELOPPE)

        for lue, attendue in zip(gpkg._enveloppe(blob), ENVELOPPE):
            self.assertAlmostEqual(lue, attendue, places=6)

    def test_sans_bornes_la_geometrie_est_declaree_vide(self):
        """Sans enveloppe, les déclencheurs ne doivent pas indexer la ligne."""
        blob = gpkg.encoder_geometrie(POINT_WKB, 32187, None)

        self.assertTrue(blob[3] & 0x10)
        self.assertIsNone(gpkg._enveloppe(blob))

    def test_bornes_partiellement_nulles_ecartees(self):
        blob = gpkg.encoder_geometrie(POINT_WKB, 32187, (1.0, None, 2.0, 3.0))

        self.assertIsNone(gpkg._enveloppe(blob))

    def test_geometrie_absente(self):
        self.assertIsNone(gpkg.encoder_geometrie(None, 32187, ENVELOPPE))

    def test_memoryview_acceptee(self):
        """`psycopg` rend les blobs sous forme de `memoryview`."""
        blob = gpkg.encoder_geometrie(memoryview(POINT_WKB), 32187, ENVELOPPE)

        self.assertEqual(blob[40:], POINT_WKB)


class FonctionsSpatialesTestCase(SimpleTestCase):
    """Les cinq fonctions que le module déclare pour les déclencheurs R-Tree."""

    def setUp(self):
        self.connexion = sqlite3.connect(":memory:")
        gpkg._declarer_fonctions(self.connexion)
        self.addCleanup(self.connexion.close)

    def evaluer(self, expression, blob):
        return self.connexion.execute(f"SELECT {expression}(?)", (blob,)).fetchone()[0]

    def test_bornes(self):
        blob = gpkg.encoder_geometrie(POINT_WKB, 32187, (1.0, 2.0, 3.0, 4.0))

        self.assertEqual(self.evaluer("ST_IsEmpty", blob), 0)
        self.assertAlmostEqual(self.evaluer("ST_MinX", blob), 1.0)
        self.assertAlmostEqual(self.evaluer("ST_MaxX", blob), 2.0)
        self.assertAlmostEqual(self.evaluer("ST_MinY", blob), 3.0)
        self.assertAlmostEqual(self.evaluer("ST_MaxY", blob), 4.0)

    def test_geometrie_sans_enveloppe_declaree_vide(self):
        blob = gpkg.encoder_geometrie(POINT_WKB, 32187, None)

        self.assertEqual(self.evaluer("ST_IsEmpty", blob), 1)
        self.assertIsNone(self.evaluer("ST_MinX", blob))

    def test_valeur_nulle(self):
        self.assertEqual(self.evaluer("ST_IsEmpty", None), 1)

    def test_blob_etranger(self):
        """Un blob qui n'est pas une géométrie GeoPackage ne fait pas tomber SQLite."""
        self.assertEqual(self.evaluer("ST_IsEmpty", b"n'importe quoi"), 1)


class ConversionTestCase(SimpleTestCase):
    def test_types_courants(self):
        import datetime
        import uuid
        from decimal import Decimal

        self.assertEqual(gpkg.convertir(None), None)
        self.assertEqual(gpkg.convertir("texte"), "texte")
        self.assertEqual(gpkg.convertir(3), 3)
        self.assertEqual(gpkg.convertir(Decimal("3.50")), 3.5)
        self.assertEqual(
            gpkg.convertir(datetime.date(2026, 9, 1)),
            "2026-09-01",
        )
        self.assertEqual(
            gpkg.convertir(datetime.datetime(2026, 9, 1, 8, 30)),
            "2026-09-01T08:30:00",
        )
        identifiant = uuid.uuid4()
        self.assertEqual(gpkg.convertir(identifiant), str(identifiant))
        self.assertEqual(gpkg.convertir(memoryview(b"abc")), b"abc")


class TableTestCase(SimpleTestCase):
    """Vidage et insertion sur un GeoPackage réduit à ce qui nous concerne."""

    def setUp(self):
        self.fichier = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
        self.fichier.close()
        self.addCleanup(self._supprimer)

        connexion = sqlite3.connect(self.fichier.name)
        connexion.executescript(
            """
            CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER);
            CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER);
            CREATE TABLE gpkg_ogr_contents (table_name TEXT, feature_count INTEGER);
            CREATE TABLE points (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB, code TEXT);
            CREATE TABLE notes (fid INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT);
            INSERT INTO gpkg_contents VALUES ('points', 'features', 32187),
                                             ('notes', 'attributes', 0),
                                             ('carte', 'tiles', 3857);
            INSERT INTO gpkg_geometry_columns VALUES ('points', 'geom', 32187);
            INSERT INTO gpkg_ogr_contents VALUES ('points', NULL), ('notes', NULL);
            INSERT INTO points (geom, code) VALUES (NULL, 'ancien');
            INSERT INTO notes (code) VALUES ('ancienne');
            """
        )
        connexion.commit()
        connexion.close()

        self.connexion = gpkg.ouvrir(self.fichier.name)
        self.addCleanup(self.connexion.close)

    def _supprimer(self):
        import os

        try:
            os.unlink(self.fichier.name)
        except OSError:
            pass

    def test_tables_de_donnees_ecarte_les_tuiles(self):
        self.assertEqual(gpkg.tables_de_donnees(self.connexion), {"points", "notes"})

    def test_colonne_geometrie(self):
        self.assertEqual(
            gpkg.colonne_geometrie(self.connexion, "points"), ("geom", 32187)
        )
        self.assertIsNone(gpkg.colonne_geometrie(self.connexion, "notes"))

    def test_vider_puis_inserer(self):
        efface = gpkg.vider(self.connexion, {"points", "notes"})
        self.assertEqual(efface, 2)

        blob = gpkg.encoder_geometrie(POINT_WKB, 32187, ENVELOPPE)
        ecrites = gpkg.inserer(
            self.connexion,
            "points",
            ["code", "geom"],
            [("A", blob), ("B", None)],
        )

        self.assertEqual(ecrites, 2)
        self.assertEqual(
            self.connexion.execute("SELECT count(*) FROM points").fetchone()[0], 2
        )
        # `fid` est laissé à SQLite : les deux lignes en ont un, distinct.
        identifiants = [
            ligne[0] for ligne in self.connexion.execute("SELECT fid FROM points")
        ]
        self.assertEqual(len(set(identifiants)), 2)

    def test_recompter(self):
        gpkg.vider(self.connexion, {"points"})
        gpkg.inserer(self.connexion, "points", ["code"], [("A",), ("B",), ("C",)])
        gpkg.recompter(self.connexion, {"points"})

        self.assertEqual(
            self.connexion.execute(
                "SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = 'points'"
            ).fetchone()[0],
            3,
        )

    def test_inserer_sans_lignes(self):
        self.assertEqual(gpkg.inserer(self.connexion, "points", ["code"], []), 0)


class RenommerTablesTestCase(SimpleTestCase):
    """Le renommage par GDAL, sur un vrai GeoPackage.

    C'est ce qui rend le GeoPackage reconnaissable par l'étape de validation du
    flux `delta_apply`, qui cherche des tables nommées `mesurage` et
    `infor_gener`.
    """

    def setUp(self):
        import os
        import tempfile

        from osgeo import ogr

        fichier = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
        fichier.close()
        os.unlink(fichier.name)
        self.chemin = fichier.name

        source = ogr.GetDriverByName("GPKG").CreateDataSource(self.chemin)
        source.CreateLayer("c0913e60", geom_type=ogr.wkbPoint)
        source.CreateLayer("7d83cbe7", geom_type=ogr.wkbNone)
        source = None

        self.addCleanup(self._nettoyer)

    def _nettoyer(self):
        import os

        try:
            os.unlink(self.chemin)
        except OSError:
            pass

    def _tables(self):
        import sqlite3

        connexion = sqlite3.connect(self.chemin)
        noms = {
            ligne[0]
            for ligne in connexion.execute("SELECT table_name FROM gpkg_contents")
        }
        connexion.close()
        return noms

    def test_les_tables_prennent_leur_nom_metier(self):
        faits = gpkg.renommer_tables(
            self.chemin, {"c0913e60": "mesurage", "7d83cbe7": "infor_gener"}
        )

        self.assertEqual(faits, {"c0913e60": "mesurage", "7d83cbe7": "infor_gener"})
        self.assertEqual(self._tables(), {"mesurage", "infor_gener"})

    def test_l_index_spatial_suit(self):
        """Un R-Tree resté sur l'ancien nom casserait la couche à l'ouverture."""
        import sqlite3

        gpkg.renommer_tables(self.chemin, {"c0913e60": "mesurage"})

        connexion = sqlite3.connect(self.chemin)
        restes = connexion.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE '%c0913e60%'"
        ).fetchall()
        colonnes = connexion.execute(
            "SELECT table_name FROM gpkg_geometry_columns"
        ).fetchall()
        connexion.close()

        self.assertEqual(restes, [])
        self.assertEqual(colonnes, [("mesurage",)])

    def test_une_table_absente_est_signalee_sans_interrompre(self):
        faits = gpkg.renommer_tables(
            self.chemin, {"inconnue": "veget", "c0913e60": "mesurage"}
        )

        self.assertEqual(faits, {"c0913e60": "mesurage"})

    def test_aucun_renommage_demande(self):
        self.assertEqual(gpkg.renommer_tables(self.chemin, {}), {})
        self.assertIn("c0913e60", self._tables())
