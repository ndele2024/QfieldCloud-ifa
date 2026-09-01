-- Colonne technique mono-colonne pour le packaging hors ligne QFieldSync.
-- Generee le 2026-08-31 11:56
-- ATTENTION : ces ordres supposent des TABLES. Pour une VUE, ajouter la
-- colonne a la table sous-jacente puis l'exposer dans la vue.

BEGIN;

-- ifa_structure.amenagement (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."amenagement"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS amenagement_qgis_id_uidx
  ON "ifa_structure"."amenagement" (qgis_id);

-- ifa_structure.analy_physi_chimi (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."analy_physi_chimi"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS analy_physi_chimi_qgis_id_uidx
  ON "ifa_structure"."analy_physi_chimi" (qgis_id);

-- ifa_structure.anoma_speci (cle actuelle : 6 colonnes)
ALTER TABLE "ifa_structure"."anoma_speci"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS anoma_speci_qgis_id_uidx
  ON "ifa_structure"."anoma_speci" (qgis_id);

-- ifa_structure.autre_obser_fauni (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."autre_obser_fauni"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS autre_obser_fauni_qgis_id_uidx
  ON "ifa_structure"."autre_obser_fauni" (qgis_id);

-- ifa_structure.carac_envir_lotiq (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."carac_envir_lotiq"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS carac_envir_lotiq_qgis_id_uidx
  ON "ifa_structure"."carac_envir_lotiq" (qgis_id);

-- ifa_structure.denom_espec (cle actuelle : 6 colonnes)
ALTER TABLE "ifa_structure"."denom_espec"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS denom_espec_qgis_id_uidx
  ON "ifa_structure"."denom_espec" (qgis_id);

-- ifa_structure.descr_habit (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."descr_habit"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS descr_habit_qgis_id_uidx
  ON "ifa_structure"."descr_habit" (qgis_id);

-- ifa_structure.detail_speci (cle actuelle : 5 colonnes)
ALTER TABLE "ifa_structure"."detail_speci"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS detail_speci_qgis_id_uidx
  ON "ifa_structure"."detail_speci" (qgis_id);

-- ifa_structure.ensemencement (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."ensemencement"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS ensemencement_qgis_id_uidx
  ON "ifa_structure"."ensemencement" (qgis_id);

-- ifa_structure.equipe (cle actuelle : 2 colonnes)
ALTER TABLE "ifa_structure"."equipe"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS equipe_qgis_id_uidx
  ON "ifa_structure"."equipe" (qgis_id);

-- ifa_structure.espec_amena (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."espec_amena"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS espec_amena_qgis_id_uidx
  ON "ifa_structure"."espec_amena" (qgis_id);

-- ifa_structure.espec_habit (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."espec_habit"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS espec_habit_qgis_id_uidx
  ON "ifa_structure"."espec_habit" (qgis_id);

-- ifa_structure.facie (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."facie"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS facie_qgis_id_uidx
  ON "ifa_structure"."facie" (qgis_id);

-- ifa_structure.forme_descr_habit (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."forme_descr_habit"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS forme_descr_habit_qgis_id_uidx
  ON "ifa_structure"."forme_descr_habit" (qgis_id);

-- ifa_structure.forme_eleme_habit (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."forme_eleme_habit"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS forme_eleme_habit_qgis_id_uidx
  ON "ifa_structure"."forme_eleme_habit" (qgis_id);

-- ifa_structure.forme_envir_struc (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."forme_envir_struc"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS forme_envir_struc_qgis_id_uidx
  ON "ifa_structure"."forme_envir_struc" (qgis_id);

-- ifa_structure.geome_longi (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."geome_longi"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS geome_longi_qgis_id_uidx
  ON "ifa_structure"."geome_longi" (qgis_id);

-- ifa_structure.geome_trans (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."geome_trans"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS geome_trans_qgis_id_uidx
  ON "ifa_structure"."geome_trans" (qgis_id);

-- ifa_structure.granu_lit (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."granu_lit"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS granu_lit_qgis_id_uidx
  ON "ifa_structure"."granu_lit" (qgis_id);

-- ifa_structure.habitat (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."habitat"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS habitat_qgis_id_uidx
  ON "ifa_structure"."habitat" (qgis_id);

-- ifa_structure.infor_gener (cle actuelle : 2 colonnes)
ALTER TABLE "ifa_structure"."infor_gener"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS infor_gener_qgis_id_uidx
  ON "ifa_structure"."infor_gener" (qgis_id);

-- ifa_structure.labo_obser (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."labo_obser"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS labo_obser_qgis_id_uidx
  ON "ifa_structure"."labo_obser" (qgis_id);

-- ifa_structure.marqu_ensem (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."marqu_ensem"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS marqu_ensem_qgis_id_uidx
  ON "ifa_structure"."marqu_ensem" (qgis_id);

-- ifa_structure.mesurage (cle actuelle : 2 colonnes)
ALTER TABLE "ifa_structure"."mesurage"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS mesurage_qgis_id_uidx
  ON "ifa_structure"."mesurage" (qgis_id);

-- ifa_structure.mobilite (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."mobilite"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS mobilite_qgis_id_uidx
  ON "ifa_structure"."mobilite" (qgis_id);

-- ifa_structure.peche_exper (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."peche_exper"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS peche_exper_qgis_id_uidx
  ON "ifa_structure"."peche_exper" (qgis_id);

-- ifa_structure.perturbation (cle actuelle : 3 colonnes)
ALTER TABLE "ifa_structure"."perturbation"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS perturbation_qgis_id_uidx
  ON "ifa_structure"."perturbation" (qgis_id);

-- ifa_structure.pose_levee_filet (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."pose_levee_filet"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS pose_levee_filet_qgis_id_uidx
  ON "ifa_structure"."pose_levee_filet" (qgis_id);

-- ifa_structure.profi_mesur (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."profi_mesur"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS profi_mesur_qgis_id_uidx
  ON "ifa_structure"."profi_mesur" (qgis_id);

-- ifa_data.proje_sonda (cle actuelle : 1 colonne)
ALTER TABLE "ifa_data"."proje_sonda"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS proje_sonda_qgis_id_uidx
  ON "ifa_data"."proje_sonda" (qgis_id);

-- ifa_structure.resul_analy_physi_chimi (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."resul_analy_physi_chimi"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS resul_analy_physi_chimi_qgis_id_uidx
  ON "ifa_structure"."resul_analy_physi_chimi" (qgis_id);

-- ifa_structure.titra_alcal (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."titra_alcal"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS titra_alcal_qgis_id_uidx
  ON "ifa_structure"."titra_alcal" (qgis_id);

-- ifa_structure.trans_vites (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."trans_vites"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS trans_vites_qgis_id_uidx
  ON "ifa_structure"."trans_vites" (qgis_id);

-- ifa_data.type_unite_echan (cle actuelle : 1 colonne)
ALTER TABLE "ifa_data"."type_unite_echan"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS type_unite_echan_qgis_id_uidx
  ON "ifa_data"."type_unite_echan" (qgis_id);

-- ifa_data.unite_echan (cle actuelle : 1 colonne)
ALTER TABLE "ifa_data"."unite_echan"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS unite_echan_qgis_id_uidx
  ON "ifa_data"."unite_echan" (qgis_id);

-- ifa_structure.veget (cle actuelle : 4 colonnes)
ALTER TABLE "ifa_structure"."veget"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS veget_qgis_id_uidx
  ON "ifa_structure"."veget" (qgis_id);

-- ifa_data.versi_type_unite_echan (cle actuelle : 1 colonne)
ALTER TABLE "ifa_data"."versi_type_unite_echan"
  ADD COLUMN IF NOT EXISTS qgis_id bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS versi_type_unite_echan_qgis_id_uidx
  ON "ifa_data"."versi_type_unite_echan" (qgis_id);

COMMIT;
