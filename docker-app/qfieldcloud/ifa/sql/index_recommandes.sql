-- ---------------------------------------------------------------------------
--  Index conseillés sur la base IFA pour la recherche d'unités
-- ---------------------------------------------------------------------------
--  Facultatif : les points d'accès fonctionnent sans. Ce fichier n'est pas
--  appliqué automatiquement — la base IFA appartient au ministère, QFieldCloud
--  n'y exécute aucune migration (voir qfieldcloud/ifa/db.py).
--
--  À passer par un administrateur de la base, de préférence hors heures de
--  production. CONCURRENTLY évite de verrouiller les tables en écriture ;
--  chaque instruction doit alors s'exécuter hors transaction.
--
--  Mesures relevées sur le fonds de développement (142 000 unités,
--  700 000 mesurages) :
--
--    recherche par région   ~250 ms   →  déjà correcte sans index
--    recherche par zone     ~240 ms   →  déjà correcte (index GiST existant)
--    recherche par code   45-90 ms    →  déjà correcte ; voir la note trigramme
--    recherche par n° LCE   ~950 ms   →  ~15 ms avec l'index ci-dessous
-- ---------------------------------------------------------------------------

-- Recherche par n° de plan d'eau. Les numéros sont stockés avec des zéros de
-- tête, la requête les compare dézérotés : l'index doit porter sur la même
-- expression que le prédicat, sinon il est ignoré.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_infor_gener_no_plan_eau_offic
    ON ifa_data.infor_gener (ltrim(ing_no_plan_eau_offic, '0'));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_infor_gener_no_plan_eau
    ON ifa_data.infor_gener (ltrim(ing_no_plan_eau, '0'));

-- Recherche par région : la jointure mesurage → proje_sonda balaye
-- actuellement l'index primaire de `mesurage` en entier.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mesurage_pro_code_ident
    ON ifa_data.mesurage (pro_code_ident);

ANALYZE ifa_data.infor_gener;
ANALYZE ifa_data.mesurage;


-- ---------------------------------------------------------------------------
--  Projets de sondage : « utilisé par combien d'UE ? »
-- ---------------------------------------------------------------------------
--  « Modifier / Afficher / Supprimer un projet » compte les unités de chaque
--  projet (`projet_gestion.nombre_unites`, et la liste entière en une
--  requête) : c'est ce qui décide si le projet est encore modifiable et
--  supprimable. `mesurage` n'a pas d'index sur `pro_code_ident` : chaque
--  comptage balaye la table, ~350 ms sur 700 000 mesurages. L'index couvrant
--  ci-dessous répond depuis l'index seul.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mesurage_pro_code_ident
    ON ifa_data.mesurage (pro_code_ident, une_code_ident);


-- ---------------------------------------------------------------------------
--  Facultatif, et plus intrusif : recherche par fragment de code
-- ---------------------------------------------------------------------------
--  La recherche par code est partielle (`ILIKE '%…%'`), donc non indexable par
--  un index B-tree : PostgreSQL balaye la table, en 45 à 90 ms. C'est
--  acceptable, et rien de ce qui suit n'est nécessaire.
--
--  Si ce temps devient gênant — par exemple avec une recherche déclenchée à
--  chaque frappe plutôt qu'à la validation — un index trigramme le ramène à
--  quelques millisecondes. Il demande en revanche une EXTENSION sur la base du
--  ministère, ce qui n'est pas une décision de développeur :
--
--    CREATE EXTENSION IF NOT EXISTS pg_trgm;
--
--    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_unite_echan_code_trgm
--        ON ifa_data.unite_echan USING gin (une_code_ident gin_trgm_ops);
--
--  L'index sert aussi bien `ILIKE` que `LIKE`, et n'exige aucune modification
--  de `filtres.py`.
-- ---------------------------------------------------------------------------
