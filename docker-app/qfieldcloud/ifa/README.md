# `qfieldcloud.ifa` — points d'accès du programme IFA 2.0

Cette application sert les points d'accès `/api/v1/ifa/` que le plugin QField
« IFA 2.0 — Menu » interroge. Elle lit la **base métier du ministère** — pas les
projets QFieldCloud.

---

## 1. Pourquoi une base à part, et sans ORM

La base `ifa` (schéma `ifa_data`) préexiste à QFieldCloud, d'autres applications
l'alimentent, et QFieldCloud n'en est pas propriétaire. Trois règles en
découlent, appliquées dans `db.py` :

1. **Aucun modèle Django.** Le schéma hérité ne se plie pas aux conventions de
   l'ORM (clés composites, types énumérés, colonnes `shape` en EPSG:32187), et
   surtout : le décrire en modèles inviterait tôt ou tard une migration à s'y
   appliquer. Tout passe par du SQL brut, paramétré.
2. **Transaction en lecture seule.** `db.curseur()` ouvre un `SET TRANSACTION
   READ ONLY` : même un défaut de programmation ne peut pas écrire dans la base
   de production.
3. **Aucune migration.** `routers.IfaDatabaseRouter` renvoie `False` pour
   `allow_migrate` sur l'alias `ifa`, et `settings.DATABASES["ifa"]["TEST"]`
   vaut `{"MIRROR": "default"}` pour que le lanceur de tests ne crée jamais de
   base `test_ifa` sur le serveur du ministère.

## 2. Configuration

L'alias réutilise les variables `VALIDATION_PG_*`, déjà celles du conteneur
`qgis` pour la validation des livraisons — une seule base, un seul jeu de
paramètres, aucune chance de les voir diverger.

| Variable | Défaut | Rôle |
|---|---|---|
| `VALIDATION_PG_HOST` | *(vide)* | Hôte. **Vide : l'alias n'est pas déclaré** et les points d'accès répondent 503. |
| `VALIDATION_PG_PORT` | `5432` | Port. |
| `VALIDATION_PG_DB` | `ifa` | Base. |
| `VALIDATION_PG_USER` | `postgres` | Utilisateur. Un compte en lecture seule suffit. |
| `VALIDATION_PG_PASS` | *(vide)* | Mot de passe. |
| `VALIDATION_PG_SCHEMA` | `ifa_data` | Schéma métier. |
| `IFA_DB_SRID` | `32187` | SRID des colonnes `shape`. |
| `IFA_DB_STATEMENT_TIMEOUT_MS` | `20000` | Délai maximal d'une requête. |
| `IFA_RECHERCHE_LIMITE_DEFAUT` | `200` | Taille de page par défaut. |
| `IFA_RECHERCHE_LIMITE_MAX` | `1000` | Plafond qu'un client peut demander. |

En développement local sous Docker Desktop, `VALIDATION_PG_HOST` vaut
`host.docker.internal`. Sur un hôte Linux, cette adresse n'est pas résolue
d'office : passer l'IP de la passerelle Docker, ou ajouter un `extra_hosts` au
service `app`.

## 3. `POST /api/v1/ifa/unites/recherche/`

Recherche les unités d'échantillonnage selon **un** critère. Authentification
requise (`Authorization: Token …`).

Le verbe est POST bien qu'il s'agisse d'une lecture : le filtre par zone
transporte un polygone en WKT, qui ne tient pas raisonnablement dans une chaîne
de requête.

### Requête

```json
{ "mode": "region",  "valeur": "02" }
{ "mode": "lce",     "valeur": "12777" }
{ "mode": "code",    "valeur": "12777" }
{ "mode": "emprise", "wkt": "POLYGON((…))", "bbox": [xmin, ymin, xmax, ymax] }
```

Le mode `code` est une **recherche partielle** : la saisie est cherchée
n'importe où dans `une_code_ident`, sans tenir compte de la casse (deux
caractères minimum). Les trois autres modes sont des égalités.

`limite` (défaut 200, plafond 1000) et `decalage` (défaut 0) complètent le
filtre. `bbox` est acceptée mais **ignorée** : la recherche porte sur le
polygone lui-même, filtrer sur la boîte englobante ramènerait des unités hors
de la zone tracée.

### Réponse

```json
{
  "mode": "region",
  "total": 12561,
  "limite": 200,
  "decalage": 0,
  "tronque": true,
  "resultats": [
    {
      "une_code_ident": "02-12777-IPE",
      "tue_code_ident": "f0758571-e68e-47f5-a3d5-9c865e3c61c9",
      "tue_nom": "Inventaire sur plan d'eau",
      "une_ind_verro": "N",
      "une_nom_propr_verro": "",
      "une_date_verro": "",
      "une_raiso_verro": "",
      "une_date_creat": "2009-10-21T14:52:56",
      "une_code_utili_creat": "ifa0t2",
      "une_date_maj": "2025-04-03T12:31:07",
      "une_code_utili_maj": "kamdo1",
      "rad_no": "02",
      "ing_no_plan_eau": "12777",
      "ing_nom_plan_eau": "ILETS, LAC DES",
      "latitude": 48.196709,
      "longitude": -71.233353
    }
  ]
}
```

Les chaînes absentes sortent vides plutôt que `null` : le plugin affiche les
valeurs telles quelles, et un `null` deviendrait le texte « null » dans une
cellule du tableau. Seules les coordonnées gardent le droit d'être nulles — une
unité sans mesurage localisé n'a pas de position, et un zéro la placerait au
large du golfe de Guinée.

Les horodatages sortent en ISO 8601 **sans fuseau** : les colonnes du schéma
hérité sont des `timestamp without time zone` portant l'heure locale de saisie.
Y coller un `Z` afficherait une heure fausse.

### Erreurs

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | Filtre incomplet, mode inconnu, WKT illisible. Le `message` est rédigé pour être affiché tel quel. |
| 401 | `not_authenticated` | Jeton absent, expiré ou révoqué. |
| 503 | `ifa_base_indisponible` | Base non configurée, injoignable, ou requête au-delà du délai. |

QFieldCloud réduit hors mode DEBUG le détail des erreurs à `{code, message}`
(voir `qfieldcloud.core.rest_utils`). Une `ValidationError` de DRF arriverait
donc chez le client sous le seul libellé « API Error » : les erreurs de cette
application passent par `exceptions.py`, qui porte le message utile dans
`message`.

## 4. Ce que les requêtes savent du schéma

Trois pièges valent d'être connus avant de toucher à `filtres.py`.

**La région ne se lit pas dans le code d'UE.** Le préfixe (`02-…`) s'en approche
mais ment : plus de 5 000 unités portent un préfixe différent de la région de
leur projet, et le fonds contient des codes qui n'ont pas cette forme du tout
(identifiants hérités en hexadécimal). La source qui fait foi est
`proje_sonda.rad_no`, atteinte par les mesurages de l'unité — elle couvre
141 946 des 142 042 unités.

**Le n° de plan d'eau est stocké dézéroté d'un côté, pas de l'autre.** La base
porte `00256` là où le technicien saisit `256`, et le numéro officiel
(`ing_no_plan_eau_offic`) diffère du numéro saisi (`ing_no_plan_eau`) sur une
partie du fonds. Les deux sont interrogés, `ltrim(…, '0')` des deux côtés.

**Le code d'unité se cherche par fragment, et la casse n'y est pas uniforme.**
Un technicien connaît rarement le code entier : il tape le n° du plan d'eau, le
type, ou le début du code. D'où `ILIKE '%…%'`, qui règle du même coup le cas des
familles historiques en minuscules (réseau ANRO). Les jokers `%` et `_` d'une
saisie sont échappés — sans quoi un `%` tapé par mégarde ramènerait la table
entière.

## 5. Performances

Relevés sur le fonds de développement (142 000 unités, 700 000 mesurages) :

| Recherche | Sans index supplémentaire |
|---|---|
| par code (fragment) | 45–90 ms |
| par zone | ~240 ms (index GiST existant sur `infor_gener.shape`) |
| par région | ~250 ms |
| par n° de plan d'eau | ~950 ms |

`sql/index_recommandes.sql` ramène la recherche par n° de plan d'eau à quelques
millisecondes. Ce fichier n'est **pas** appliqué automatiquement : la base
appartient au ministère, à un administrateur de la passer. Il documente aussi
l'index trigramme qui accélérerait la recherche par fragment de code — plus
intrusif, puisqu'il demande l'extension `pg_trgm`.

La pagination s'applique sur `unite_echan` seule, avant les jointures
d'enrichissement : celles-ci ne portent ensuite que sur les lignes affichées, et
non sur les milliers de lignes que peut renvoyer un filtre par région.

## 6. Tests

```bash
docker compose exec app python manage.py test qfieldcloud.ifa
```

Les tests ne touchent pas à la base métier — ils portent sur la construction des
requêtes (`filtres.py`), la validation des filtres (`serializers.py`) et la
normalisation des lignes (`views.py`), tout ce qui peut se casser sans qu'un
appel réseau ne le dise.
