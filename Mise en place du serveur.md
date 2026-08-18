# Mise en place du serveur VPS

- ovh coud vps password
```bash
ndele2026@
```

## 1- vps connexion
```bash
ssh ubuntu@149.56.108.189
```

## 2- installation de Docker engine
### 2.1- Set up Docker's apt repository.

```bash
# Add Docker's official GPG key:
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update

```

### 2.2- Install the Docker packages
```bash

sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

```

### 2.3- After installation, verify that Docker is running:
```bash
    sudo systemctl status docker
```
    If Docker is not running, start it manually:
```bash
    sudo systemctl start docker
```

### 2.4- Verify that the installation is successful by running the hello-world image
 ```bash
    sudo docker run hello-world
```
    This command downloads a test image and runs it in a container. When the container runs, it prints a confirmation message and exits

## 3- Installation de PostgreSQL et Postgis

 ```bash
    sudo apt install postgresql postgis
```
 for a specific version :
 sudo apt install postgresql-$version postgis-$version
'$version' is the number of version you want to install
exemple :
```bash
    sudo apt install postgresql-17 postgis-3
```

### 3.1- créer un utilisateur et la base de données

create user ifauser with password 'ifa2026';
create database ifa;

### 3.2- exporter la base de données IFA


### 3.3- accorder les droits à l'utilisateur ifauser

GRANT ALL PRIVILEGES ON DATABASE ifa TO ifauser;



## 4- deployer QFieldCloud

### 4.1- cloner le repo git du code source

### 4.2-  Éditer le fichier .env et vérifier les paramètres à modifier
    Cherche la ligne (vers 133) :
"endpoint_url": "http://host.docker.internal:8009"
et remplace-la par :
"endpoint_url": "http://rustfs:9000"
(rustfs = nom du service dans docker-compose.override.standalone.yml, 9000 = port interne du conteneur, pas le port publié 8009).


### 4.3- Éditer le fichier config.py du script de validation et vérifier les paramètres de connexion à la base de données postgresql

### 4.4- configurer le pare feu
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp



    admin Django : admin    password : adminifa2026


### exécuter le srcipt bash pour l'obtension du token à utiliser dans le plugin qml


1. Modifier le code — docker-app/worker_wrapper/wrapper.py

Le conteneur qgis (qui exécute la validation IFE) est lancé dynamiquement via client.containers.run(...) autour de la ligne 420, sans l'option extra_hosts. C'est pour ça que host.docker.internal ne résout pas sur Linux (contrairement à Docker Desktop Windows/Mac où c'est automatique).

Ouvre docker-app/worker_wrapper/wrapper.py, trouve ce bloc (vers la ligne 420) :

container: Container = client.containers.run(  # type:ignore
    settings.QFIELDCLOUD_QGIS_IMAGE_NAME,
    command,
    environment=environment,
    ports=ports,
    volumes=volumes,
    # TODO stream the logs to something like redis, so they can be streamed back in project jobs page to the user live
    # auto_remove=True,
    network=settings.QFIELDCLOUD_DEFAULT_NETWORK,
    detach=True,

Ajoute la ligne extra_hosts juste après network=... :

container: Container = client.containers.run(  # type:ignore
    settings.QFIELDCLOUD_QGIS_IMAGE_NAME,
    command,
    environment=environment,
    ports=ports,
    volumes=volumes,
    # TODO stream the logs to something like redis, so they can be streamed back in project jobs page to the user live
    # auto_remove=True,
    network=settings.QFIELDCLOUD_DEFAULT_NETWORK,
    extra_hosts={"host.docker.internal": "host-gateway"},
    detach=True,

"host-gateway" est une valeur spéciale supportée par Docker Engine ≥ 20.10 sur Linux — elle fait pointer host.docker.internal vers l'IP de la passerelle du réseau Docker, exactement comme le fait Docker Desktop nativement sur Windows/Mac. Comme ça, ton .env (VALIDATION_PG_HOST=host.docker.internal) reste identique entre dev local et VPS, aucun changement de valeur nécessaire.


3. Configurer PostgreSQL natif sur le VPS pour accepter les connexions depuis Docker

Comme la base ifa tourne nativement sur le VPS (hors Docker), Postgres doit écouter au-delà de localhost et autoriser explicitement le sous-réseau Docker.

a) postgresql.conf (chemin typique /etc/postgresql/<version>/main/postgresql.conf) :
listen_addresses = 'localhost,172.16.0.0/12'
Postgres n'accepte pas de plage CIDR directement dans listen_addresses — utilise plutôt * si c'est plus simple, mais alors restreins bien l'accès via pg_hba.conf et le firewall (étape suivante) :
listen_addresses = '*'

b) pg_hba.conf (même dossier), ajoute une ligne autorisant le sous-réseau Docker (les réseaux bridge Docker/Compose sont dans la plage 172.16.0.0/12) :
host    ifa    postgres    172.16.0.0/12    scram-sha-256
host    ifa    ifauser     172.16.0.0/12    scram-sha-256

c) Redémarrer Postgres :
sudo systemctl restart postgresql

4. Restreindre l'accès via ufw

Comme listen_addresses = '*' expose Postgres sur toutes les interfaces, il faut que le firewall bloque l'accès public au port 5432 et n'autorise que le trafic venant de Docker :
sudo ufw allow from 172.16.0.0/12 to any port 5432 proto tcp
Ne fais surtout pas sudo ufw allow 5432 tout court — ça exposeraitPostgres à tout Internet.

5. configurer le dns et let's encrypt pour le certificat tsl
 Passe 1 — .env sur le VPS, avant l'émission

  Modification 1 — QFIELDCLOUD_HOST (vers la ligne 14)

  -QFIELDCLOUD_HOST=localhost
  +QFIELDCLOUD_HOST=ifa.example.org

  Sans https:// devant, sans barre oblique ni port à la fin — le commentaire du fichier le précise, et cette variable sert à construire les chemins des certificats plus
  bas.

  Modification 2 — DJANGO_ALLOWED_HOSTS (vers la ligne 278)

  -DJANGO_ALLOWED_HOSTS="149.56.108.189 localhost 127.0.0.1 0.0.0.0 app nginx"
  +DJANGO_ALLOWED_HOSTS="ifa.example.org localhost 127.0.0.1 0.0.0.0 app nginx"

  Sans ça Django renvoie 400 sur toutes les requêtes portant le nouveau nom.

  Ce qu'il ne faut pas encore toucher

  Les lignes 48 et 54 (QFIELDCLOUD_TLS_CERT / QFIELDCLOUD_TLS_KEY) restent sur mkcert. Elles se dérivent automatiquement du nouveau QFIELDCLOUD_HOST, donc mkcert va
  générer un certificat auto-signé pour le domaine. C'est voulu : il permet à nginx de démarrer, et le challenge ACME passe par le port 80 en clair de toute façon.

  Puis, en ligne de commande

  cd ~/QfieldCloud-ifa
  cp .env .env.bak-$(date +%F)          # avant d'éditer, idéalement

  docker compose up -d mkcert
  ls -l conf/nginx/certs/               # attendre l'apparition de ifa.example.org.pem

  docker compose up -d --force-recreate nginx app worker_wrapper

  Vérifie que le chemin ACME répond avant d'appeler Let's Encrypt — un échec ici consomme ton quota :

  docker compose exec -T nginx sh -c 'mkdir -p /var/www/certbot/.well-known/acme-challenge && echo ok-acme > /var/www/certbot/.well-known/acme-challenge/test'
  curl -s http://ifa.example.org/.well-known/acme-challenge/test     # doit afficher : ok-acme
  docker compose exec -T nginx rm -f /var/www/certbot/.well-known/acme-challenge/test

  Émission, à blanc puis pour de vrai :

  docker compose run --rm --entrypoint certbot certbot certonly \
    --webroot -w /var/www/certbot -d ifa.example.org \
    --email toi@example.org --agree-tos --no-eff-email \
    --rsa-key-size 4096 --non-interactive --dry-run

  # si l'essai passe, relance la même commande sans --dry-run
  ls -l conf/certbot/conf/live/ifa.example.org/

  ---
  Passe 2 — .env, après l'émission

  Le fichier contient déjà les bonnes lignes en commentaire, juste au-dessus des lignes actives. La modification consiste simplement à inverser lesquelles sont
  commentées.

  Modification 3 — QFIELDCLOUD_TLS_CERT (lignes 45 à 48)

   # For usage with Let's Encrypt certificate, use as:
  -# QFIELDCLOUD_TLS_CERT="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/fullchain.pem"
  +QFIELDCLOUD_TLS_CERT="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/fullchain.pem"
   # DEFAULT: "/etc/nginx/certs/${QFIELDCLOUD_HOST}.pem"
  -QFIELDCLOUD_TLS_CERT="/etc/nginx/certs/${QFIELDCLOUD_HOST}.pem"
  +# QFIELDCLOUD_TLS_CERT="/etc/nginx/certs/${QFIELDCLOUD_HOST}.pem"

  Modification 4 — QFIELDCLOUD_TLS_KEY (lignes 51 à 54)

   # For usage with Let's Encrypt certificate, use as:
  -# QFIELDCLOUD_TLS_KEY="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/privkey.pem"
  +QFIELDCLOUD_TLS_KEY="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/privkey.pem"
   # DEFAULT: "/etc/nginx/certs/${QFIELDCLOUD_HOST}-key.pem"
  -QFIELDCLOUD_TLS_KEY="/etc/nginx/certs/${QFIELDCLOUD_HOST}-key.pem"
  +# QFIELDCLOUD_TLS_KEY="/etc/nginx/certs/${QFIELDCLOUD_HOST}-key.pem"

  Laisse ${QFIELDCLOUD_HOST} tel quel, littéralement — c'est Docker Compose qui l'expanse. Ne remplace pas par le domaine en dur.

  Puis

  docker compose up -d --force-recreate nginx
  docker compose logs --tail=30 nginx

  docker compose up -d --force-recreate nginx

  # le test décisif : SANS -k, exactement ce que fait le XMLHttpRequest du plugin
  curl -sS -o /dev/null -w "HTTP %{http_code}\n" https://ifa.example.org/api/v1/status/

  echo | openssl s_client -connect ifa.example.org:443 -servername ifa.example.org 2>/dev/null \
    | openssl x509 -noout -issuer -dates

  L'émetteur doit être O=Let's Encrypt, CN=R10 (ou R11 / E5). S'il affiche encore mkcert development CA, la passe 2 n'a pas été prise.

  docker compose run --rm --entrypoint certbot certbot renew --dry-run
  docker compose stop mkcert     # il ne sert plus
