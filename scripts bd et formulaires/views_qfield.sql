-- Vues auto-modifiables pour le packaging hors ligne QFieldSync.
-- Generees le 2026-09-01 01:10
--
-- Une vue n'a pas de PRIMARY KEY declaree : QGIS respecte donc le
-- `key='qgis_id'` de l'URI au lieu d'imposer la cle composite de la table.
-- `SELECT *` sur une seule table reste auto-modifiable en PostgreSQL :
-- les INSERT / UPDATE / DELETE de la synchro QField passent directement.
--
-- Pour tout annuler : DROP SCHEMA ifa_qfield CASCADE;

BEGIN;

CREATE SCHEMA IF NOT EXISTS ifa_qfield;

CREATE OR REPLACE VIEW ifa_qfield."amenagement" AS SELECT * FROM ifa_structure."amenagement";
CREATE OR REPLACE VIEW ifa_qfield."analy_physi_chimi" AS SELECT * FROM ifa_structure."analy_physi_chimi";
CREATE OR REPLACE VIEW ifa_qfield."anoma_speci" AS SELECT * FROM ifa_structure."anoma_speci";
CREATE OR REPLACE VIEW ifa_qfield."autre_obser_fauni" AS SELECT * FROM ifa_structure."autre_obser_fauni";
CREATE OR REPLACE VIEW ifa_qfield."carac_envir_lotiq" AS SELECT * FROM ifa_structure."carac_envir_lotiq";
CREATE OR REPLACE VIEW ifa_qfield."denom_espec" AS SELECT * FROM ifa_structure."denom_espec";
CREATE OR REPLACE VIEW ifa_qfield."descr_habit" AS SELECT * FROM ifa_structure."descr_habit";
CREATE OR REPLACE VIEW ifa_qfield."detail_speci" AS SELECT * FROM ifa_structure."detail_speci";
CREATE OR REPLACE VIEW ifa_qfield."ensemencement" AS SELECT * FROM ifa_structure."ensemencement";
CREATE OR REPLACE VIEW ifa_qfield."equipe" AS SELECT * FROM ifa_structure."equipe";
CREATE OR REPLACE VIEW ifa_qfield."espec_amena" AS SELECT * FROM ifa_structure."espec_amena";
CREATE OR REPLACE VIEW ifa_qfield."espec_habit" AS SELECT * FROM ifa_structure."espec_habit";
CREATE OR REPLACE VIEW ifa_qfield."facie" AS SELECT * FROM ifa_structure."facie";
CREATE OR REPLACE VIEW ifa_qfield."forme_descr_habit" AS SELECT * FROM ifa_structure."forme_descr_habit";
CREATE OR REPLACE VIEW ifa_qfield."forme_eleme_habit" AS SELECT * FROM ifa_structure."forme_eleme_habit";
CREATE OR REPLACE VIEW ifa_qfield."forme_envir_struc" AS SELECT * FROM ifa_structure."forme_envir_struc";
CREATE OR REPLACE VIEW ifa_qfield."geome_longi" AS SELECT * FROM ifa_structure."geome_longi";
CREATE OR REPLACE VIEW ifa_qfield."geome_trans" AS SELECT * FROM ifa_structure."geome_trans";
CREATE OR REPLACE VIEW ifa_qfield."granu_lit" AS SELECT * FROM ifa_structure."granu_lit";
CREATE OR REPLACE VIEW ifa_qfield."habitat" AS SELECT * FROM ifa_structure."habitat";
CREATE OR REPLACE VIEW ifa_qfield."infor_gener" AS SELECT * FROM ifa_structure."infor_gener";
CREATE OR REPLACE VIEW ifa_qfield."labo_obser" AS SELECT * FROM ifa_structure."labo_obser";
CREATE OR REPLACE VIEW ifa_qfield."marqu_ensem" AS SELECT * FROM ifa_structure."marqu_ensem";
CREATE OR REPLACE VIEW ifa_qfield."mesurage" AS SELECT * FROM ifa_structure."mesurage";
CREATE OR REPLACE VIEW ifa_qfield."mobilite" AS SELECT * FROM ifa_structure."mobilite";
CREATE OR REPLACE VIEW ifa_qfield."peche_exper" AS SELECT * FROM ifa_structure."peche_exper";
CREATE OR REPLACE VIEW ifa_qfield."perturbation" AS SELECT * FROM ifa_structure."perturbation";
CREATE OR REPLACE VIEW ifa_qfield."pose_levee_filet" AS SELECT * FROM ifa_structure."pose_levee_filet";
CREATE OR REPLACE VIEW ifa_qfield."profi_mesur" AS SELECT * FROM ifa_structure."profi_mesur";
CREATE OR REPLACE VIEW ifa_qfield."resul_analy_physi_chimi" AS SELECT * FROM ifa_structure."resul_analy_physi_chimi";
CREATE OR REPLACE VIEW ifa_qfield."titra_alcal" AS SELECT * FROM ifa_structure."titra_alcal";
CREATE OR REPLACE VIEW ifa_qfield."trans_vites" AS SELECT * FROM ifa_structure."trans_vites";
CREATE OR REPLACE VIEW ifa_qfield."veget" AS SELECT * FROM ifa_structure."veget";

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ifauser') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA ifa_qfield TO ifauser';
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ifa_qfield TO ifauser';
  END IF;
END $$;

COMMIT;
