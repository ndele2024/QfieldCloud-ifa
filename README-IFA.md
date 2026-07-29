# <img alt="QFieldCloud logo" src="https://qfield.cloud/img/logo_horizontal_embedded_font.svg" width="100%"/> QFieldCloud - IFA 2.0

QFieldCloud est un service basé sur Django conçu pour synchroniser les projets et les données entre QGIS (+ plugin QFieldSync) et QField.

QFieldCloud permet une synchronisation transparente de vos données de terrain avec votre infrastructure spatiale avec des capacités de
suivi des modifications, de gestion d'équipe et de travail en ligne-hors ligne dans QField.
Cette version à été customisé pour répondre aux objectifs du projet IFA 2.0.

# Prérequis

* **Docker + Docker Compose** (Docker Desktop sur Windows/macOS, ou Docker Engine + Compose plugin sur Linux)
* Environ 4–6 Go d'espace disque (les images QGIS sont volumineuses)

# Installation

### Étape 1 — configurer le fichier .env
* Ouvre le fichier .env avec ton éditeur préféré :
```shell
nano .env   # ou code .env, vim .env
```

* Vérifier/modifier les Variables suivantes :
    * QFIELDCLOUD_HOST : donner la valeur  `localhost` ou le `DNS` de votre serveur où est hébergée l'instance QFieldCloud
    * DEBUG : valeur 1 (`DEBUG=1`) en mode developpement ou test ; value 0 (`DEBUG=0`) en production

### Etape 2 - créer le volume qfieldcloud_custom_ca_certificates pour les certificats SSL
```shell
docker volume create qfieldcloud_custom_ca_certificates
```

### Étape 3 - Construire et démarrer les conteneurs
```shell
docker compose up -d --build
```
*NB: Déconnecter votre VPN pour ne pas avoir des restrictions de connexion.*

Cette commande lit les fichiers docker-compose*.yml spécifiés dans la variable `COMPOSE_FILE` du .env, construit les images et démarre tous les conteneurs en arrière-plan : GitHub

La première exécution peut prendre 10 à 20 minutes selon ta connexion (téléchargement des images QGIS notamment).
Pour suivre les logs en temps réel ouvrir un autre terminal et taper :
```shell
docker compose logs -f
```

### Étape 4 - Appliquer les migrations de base de données
Lancer les migrations Django
```shell
docker compose exec app python manage.py migrate
```

### Étape 5 — Collecter les fichiers statiques
Collecter les fichiers CSS/JS/images
```shell
docker compose exec app python manage.py collectstatic --noinput
```

### Étape 6 — Créer le super-utilisateur admin
Créer le compte administrateur qui donne accès à l'interface Django Admin
```shell
docker compose run app python manage.py createsuperuser --username admin --email admin@example.com
```
***NB : Tu seras invité à entrer un mot de passe.***

### Étape 7 : Traduction
Si QFieldCloud doit être traduit, vous pouvez compiler les traductions à l'aide des outils de Django :
```shell
docker compose run --user root app python manage.py compilemessages
```

### Étape 8 — Faire confiance au certificat auto-signé

QFieldCloud génère automatiquement un certificat et son certificat racine dans ./conf/nginx/certs.
Il faut faire confiance à ce certificat racine pour que les autres programmes (navigateur, curl, QGIS) acceptent la connexion HTTPS locale.

Sur Linux (Debian/Ubuntu) :
```bash
sudo cp ./conf/nginx/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt
sudo update-ca-certificates
```

Sur macOS :
```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ./conf/nginx/certs/rootCA.pem
```

Sur Windows:
Renommer le fichier ./conf/nginx/certs/rootCA.pem, en ./conf/nginx/certs/rootCA.crt.
```shell
cp ./conf/nginx/certs/rootCA.pem ./conf/nginx/certs/rootCA.crt
```
Ouvrir le fichier rootCA.crt et cliquer sur
***"Installer le certificat" → "Ordinateur local" → "Autorités de certification racines de confiance"***

### Étape 8 — Vérifier que tout fonctionne
Vérifier que l'instance fonctionne correctement via le endpoint de santé — les clés database et storage doivent avoir le statut ok
```bash
curl https://localhost/api/v1/status/
```
Accède ensuite à l'interface web :
 * Interface principale : https://localhost
 * Admin Django : https://localhost/admin
 * Serveur Django direct : http://localhost:8011

### Commandes utiles au quotidien
```bash
# Démarrer
docker compose up -d

# Arrêter
docker compose down

# Voir les logs
docker compose logs -f nginx app worker_wrapper qgis

# Accéder à la base de données
docker compose exec -it db psql -U qfieldcloud_db_admin -d qfieldcloud_db
```

