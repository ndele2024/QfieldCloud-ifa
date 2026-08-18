UE IFE LISTE DES REGLES 

# Table / Couche : Analyse physico-chimique (ANALY_PHYSI_CHIMI)

   - Numéro de station (PHC_NO_STATI) : à la validation du formulaire de saisie de la couche "Analyse physico-chimique"
      valeur obligatoire

   - Appareil & Autre appareil : lors de la saisie et à la validation du formulaire de saisie de la couche "Analyse physico-chimique"

      Si (Appareil est vide) ET (Autre appareil est renseigné)
      → Alors Appareil = "AUTRE - Autre appareil"
         dans ce cas autre appareil doit spécifier la marque le modéle et la précision de cet autre appareil sinon indiquer "inconnu"
      
      quand un utilisateur saisit quelque chose dans le champ "Autre appareil" sans avoir choisi un appareil standard, la règle remplit automatiquement le champ "Appareil" avec la valeur générique 'AUTRE', pour assurer la cohérence des données.

      si on a renseigné au moin un profil de mesures (PROFI_MESUR) 
         alors "Appareil" doit être renseigné (ne peut pas être vide)



   - Territoire faunique vs Région administrative du projet : à l'ouverture et à la validation du formulaire de saisie de la couche "Analyse physico-chimique"

      Si le projet n'a pas de région administrative 
      → Alors aucun filtre n'est appliqué sur le champ "Territoire faunique"
      Sinon 
      → Alors le champ "Territoire faunique" est filtré pour n'afficher que les territoires fauniques situés dans la région administrative du projet. (cas particulier : pour la région 04 - Mauricie, filtrer les territoires fauniques avec 04 - Mauricie et 17 - Centre-du-Québecc)

      si Type de plan d'eau de "information générales" à la valeur 'L-lac'
      → Alors ne pas mesurer territoire faunique (on le désactive du formulaire)
      sinon mesurer (on laisse activer le champ territoire faunique)


   - Date de visite de la station : pendant la saisie de la couche "Analyse physico-chimique" et à la validation du formulaire de saisie

      si la date n'est pas renseignée
      → Alors lui assigner la valeur de date de début d'inventaire de la table "Informations générales"

      La date de visite doit être suppérieure à la date de debut d'inventaire et inférieure à la date de fin d'inventaire de la table/couche "Informations générales". Si ce n'est pas le cas, un message d'erreur doit être affiché pour informer l'utilisateur de corriger la date.

      la date de visite de la sation est obligatoire


# Table / Couche : profil de mesures phisico-chimie (PROFI_MESUR) 

   - Profondeur (PME_PROFD_M) : à l'ouverture du formulaire de saisie de la couche "Analyse physico-chimique (ANALY_PHYSI_CHIMI)"

      si le nombre d'occurrence de la couche "Profil de mesures physico-chimie" est égal à 0
      → Alors Selon la profondeur maximale du plan d'eau (ING_PROFD_MAX_M) saisie dans information générale, générer toutes les occurrences pour se rendre jusqu'à cette profondeur en respectant les règles suivantes : 
         /// - à 0,5 mètre;
         /// - à tous les mètres de 1 à 14 mètres inclusivement;
         /// - à tous les deux mètres de 16 à 20 mètres inclusivement;
         /// - à tous les quatre mètres à partir de 24 mètres,
         /// et ce, jusqu'au fond (profondeur maximale). Si la profondeur max est absente → 20 m

         0.5 m                          → toujours (premier point)
         1, 2, 3, ... 14 m             → tous les 1 m
         16, 18, 20 m                  → tous les 2 m  (i % 2 == 0)
         24, 28, 32, ... jusqu'au fond → tous les 4 m  (i % 4 == 0)
      
      la liste des valeurs de profondeur générées va être utilisée comme liste de chois pour le champ "Profondeur" du formulaire de saisie de la couche "Profil de mesures physico-chimie" et l'utilisateur peut les modifier si nécessaire avant de valider.

      code python : 
         def generer_profondeurs(profondeur_max: float = None) -> list[float]:
            """
            Génère la liste des profondeurs de mesure pour un profil
            physico-chimique selon les règles du MRNF.

            Règles :
               - 0.5 m (toujours)
               - tous les 1 m de 1 à 14 m inclusivement
               - tous les 2 m de 16 à 20 m inclusivement  (pairs seulement)
               - tous les 4 m à partir de 24 m            (multiples de 4)
               - jusqu'à profondeur_max inclusivement

            Args:
               profondeur_max: Profondeur maximale du plan d'eau en mètres.
                                 Défaut : 20 m si None ou invalide.

            Returns:
               Liste ordonnée des profondeurs à mesurer.
            """

            # Valeur par défaut si absente ou invalide (équivalent du catch C#)
            if profondeur_max is None:
               profondeur_max = 20.0

            profondeurs = [0.5]  # Premier point fixe

            for i in range(1, int(profondeur_max) + 1):

               if i <= 14:
                     # Tous les mètres de 1 à 14
                     profondeurs.append(float(i))

               elif i <= 20:
                     # Tous les 2 mètres de 15 à 20 (pairs seulement)
                     if i % 2 == 0:
                        profondeurs.append(float(i))

               else:
                     # Tous les 4 mètres au-delà de 20
                     if i % 4 == 0:
                        profondeurs.append(float(i))

            return profondeurs
      


# Table / Couche : Informations générales (INFOR_GENER)

   - Territoire : pendant la saisie de la couche "Informations générales" et à la validation du formulaire de saisie

      si territoire faunique à la valeur "LIBRE - Territoire Libre"
         → Alors Territoire doit avoir la valeur "Territoire Libre"


   -  No du plan d'eau officiel (ING_NO_PLAN_EAU_OFFIC) : pendant la saisie de la couche "Informations générales" et à la validation du formulaire de saisie

    /// À la saisie de la variable "Information général.No du plan d'eau officiel" vérifie dans les fichiers CSV "lac_LCE.txt" ou 
    /// "cours_eau_LCE.txt" selon le cas si cette valeur existe. Les numéros à 5 caractères font référence à des lacs "lac_LCE.txt" 
    /// et le numéro à 8 caractères font référence à des cours d'eau (rivières) et se retrouvent dans le fichier "cours_eau_LCE.txt"
    /// Si elle n'est pas présente, en avertir l'utilisateur avec un message d'erreur. 
    /// Si la valeur est présente on l'assigne aux variables correspondantes dans le cas où la variable est vide. Si elle n'est pas
    /// vide aucune assignation est faite, l'ancienne valeur demeure.
    /// Lorsque les champs Superficie, Profondeur max, Altitude et Perimètre contiennent la valeur -99 ou -999, le champs correspondant 
    /// est laissé vide.






# Table / couche : Détails des spécimens (DETAIL_SPECI)

   - Panneau du filet (CDE_CODE) : pendant la saisie de la couche "Détails des spécimens" et à la validation du formulaire de saisie

      La valeur du champ "Panneau du filet" est assignée en fonction de la valeur des champs : 
         Type de pêche de pêche expérimentale 
         Grandeur de maille de Détail des spécimens
         si type de pêche est contient les valeurs ["PENDJ", "PENT'] alors
            si detail des spécimens contient 25 
               → Alors Panneau du filet = "PAN1"
            sinon si detail des spécimens contient 38
               → Alors Panneau du filet = "PAN2"
            sinon si detail des spécimens contient 51
               → Alors Panneau du filet = "PAN3"
            sinon si detail des spécimens contient 64
               → Alors Panneau du filet = "PAN4"
            sinon si detail des spécimens contient 76
               → Alors Panneau du filet = "PAN5"
            sinon si detail des spécimens contient 102
               → Alors Panneau du filet = "PAN6"
            sinon si detail des spécimens contient 127
               → Alors Panneau du filet = "PAN7"
            sinon si detail des spécimens contient 152
               → Alors Panneau du filet = "PAN8"
         sinon si type de pêche est contient les valeurs ["PENOC", "PENOF'] alors
            si detail des spécimens contient 25 
               → Alors Panneau du filet = "PAN1"
            sinon si detail des spécimens contient 32
               → Alors Panneau du filet = "PAN2"
            sinon si detail des spécimens contient 38
               → Alors Panneau du filet = "PAN3"
            sinon si detail des spécimens contient 51
               → Alors Panneau du filet = "PAN4"
            sinon si detail des spécimens contient 64
               → Alors Panneau du filet = "PAN5"
            sinon si detail des spécimens contient 76
               → Alors Panneau du filet = "PAN6"
         sinon si type de pêche est contient les valeurs ["PECPM"] alors
            si detail des spécimens contient 32
               → Alors Panneau du filet = "PAN1"
            sinon si detail des spécimens contient 19
               → Alors Panneau du filet = "PAN2"
            sinon si detail des spécimens contient 38
               → Alors Panneau du filet = "PAN3"
            sinon si detail des spécimens contient 13
               → Alors Panneau du filet = "PAN4"
            sinon si detail des spécimens contient 25
               → Alors Panneau du filet = "PAN5"
         sinon si type de pêche est contient les valeurs ["PECGM"] alors
            si detail des spécimens contient 76
               → Alors Panneau du filet = "PAN1"
            sinon si detail des spécimens contient 114
               → Alors Panneau du filet = "PAN2"
            sinon si detail des spécimens contient 51
               → Alors Panneau du filet = "PAN3"
            sinon si detail des spécimens contient 89
               → Alors Panneau du filet = "PAN4"
            sinon si detail des spécimens contient 38
               → Alors Panneau du filet = "PAN5"
            sinon si detail des spécimens contient 127
               → Alors Panneau du filet = "PAN6"
            sinon si detail des spécimens contient 64
               → Alors Panneau du filet = "PAN7"
            sinon si detail des spécimens contient 102
               → Alors Panneau du filet = "PAN8"

   - Numéro échantillon laboratoire 1 (DSP_NO_ECHAN_LABOR_1) & Numéro échantillon laboratoire 2 (DSP_NO_ECHAN_LABOR_2) : Aprés l'ajout d'une occurence dans la couche "Détails des spécimens"
      
      si Type de structure conservée pour déterminer l'âge 1 (TSA_CODE_1) = ["OT - Otolithe", "EC - Ecaille", "OP - Opercule", "RE - Rayon épineux"] 
         → Parcourir tous les spécimens existants
         → Trouver le plus grand numéro parmi Échantillon 1 et Échantillon 2 (Le numéro d'échantillon peut être un caractère suivit  d'un entier, dans ce cas on considère seulement la partie entière pour trouver le plus grand numéro)
         → Incrémenter de 1
         → Assigner le nouveau numéro à Échantillon 1 pour le spécimen en cours de saisie (garder le caractère dans le numéro si existant)
      Même logique pour Type de structure conservée pour déterminer l'âge 2 (TSA_CODE_2) et Échantillon 2

            code python pour extraire la partie entière d'un numéro d'échantillon :
               def assigner_no_vial(specimens: list[dict], occurrence_courante: dict) -> str:
                  """
                  Génère un numéro d'échantillon automatique en incrémentant
                  le plus grand numéro existant de 1.

                  Args:
                     specimens: Liste de tous les spécimens existants
                                 Chaque dict contient: 'echantillon_1', 'echantillon_2',
                                                      'type_structure_1', 'type_structure_2'
                     occurrence_courante: Le spécimen pour lequel on génère le numéro

                  Returns:
                     Le nouveau numéro d'échantillon (ex: "43" ou "A43")
                  """

                  # On ne traite que les structures de type OT (Otolithe)
                  if occurrence_courante.get("type_structure_1") != "OT":
                     return None

                  max_echantillon_1 = 0.0
                  max_echantillon_2 = 0.0
                  lettre_debut_1 = " "
                  lettre_debut_2 = " "

                  def extraire_lettre_et_numero(valeur: str) -> tuple[str, float]:
                     """Sépare le préfixe lettre du numéro."""
                     if not valeur:
                           return " ", 0.0
                     if not valeur[0].isdigit():
                           return valeur[0], float(valeur[1:])
                     return " ", float(valeur)

                  # Parcourir tous les spécimens existants
                  for specimen in specimens:
                     echantillon_1    = specimen.get("echantillon_1", "")
                     echantillon_2    = specimen.get("echantillon_2", "")
                     type_structure_1 = specimen.get("type_structure_1", "")
                     type_structure_2 = specimen.get("type_structure_2", "")

                     # Traitement échantillon 1
                     if echantillon_1 and type_structure_1 == "OT":
                           lettre_temp, no_echant = extraire_lettre_et_numero(echantillon_1)
                           if no_echant > max_echantillon_1:
                              max_echantillon_1 = no_echant
                              lettre_debut_1 = lettre_temp

                     # Traitement échantillon 2
                     if echantillon_2 and type_structure_2 == "OT":
                           lettre_temp, no_echant = extraire_lettre_et_numero(echantillon_2)
                           if no_echant > max_echantillon_2:
                              max_echantillon_2 = no_echant
                              lettre_debut_2 = lettre_temp

                  # Déterminer le maximum global
                  if max_echantillon_1 >= max_echantillon_2:
                     max_no_seq = max_echantillon_1
                     lettre_finale = lettre_debut_1
                  else:
                     max_no_seq = max_echantillon_2
                     lettre_finale = lettre_debut_2

                  # Incrémenter et formater le résultat
                  max_no_seq += 1
                  nouveau_no = f"{lettre_finale.strip()}{int(max_no_seq)}"

                  return nouveau_no

   - Numéro de spécimen (DSP_NO_SPECI) : Après l'ajout d'une occurence dans la couche "Détails des spécimens"

      Un numéro de spécimen unique est généré par unité d'échantillonnage et l'espèce du spécimen précédent est copié vers le nouveau spécimen ajouté

         code python : 
            def assigner_no_specimen_unique(specimens: list[dict]) -> list[dict]:
               """
               Génère un numéro unique pour le dernier spécimen ajouté
               et copie l'espèce de l'avant-dernier spécimen.

               Args:
                  specimens: Liste de tous les spécimens. Le dernier est
                              le nouveau (no_seq et espece à remplir).
                              Chaque dict contient: 'no_seq' (float), 'espece' (str)

               Returns:
                  La liste mise à jour, ou inchangée si conditions non remplies.
               """

               # Garde-fou : aucun spécimen
               if not specimens:
                  return specimens

               max_no_seq    = 0.0
               espece_precedente = ""

               for i, specimen in enumerate(specimens):

                  # Trouver le numéro de séquence maximum
                  no_seq = specimen.get("no_seq", 0.0)
                  if no_seq > max_no_seq:
                        max_no_seq = no_seq

                  # Capturer l'espèce de l'avant-dernier spécimen
                  if i == len(specimens) - 2:
                        espece_precedente = specimen.get("espece", "")

               # Cibler le dernier spécimen (le nouveau)
               nouveau = specimens[-1]

               # Assigner le nouveau numéro de séquence et l'espèce précédente
               max_no_seq += 1
               nouveau["no_seq"] = max_no_seq
               nouveau["espece"] = espece_precedente

               return specimens

   - Validation des données saisies Masse totale (g), Nombre pesé, Nombre capturé : à la validation du formulaire de saisie de la couche "Détails des spécimens"

      Description:
      Fait la somme des enregistrements par "Détail spécimen.No pêche" + "Détail spécimen.No pose et levée" + "Détail spécimen.Espèce" + 
      "Détail spécimen.Panneau", fait aussi la somme pour le même groupe de toutes des enregistrements pour lesquels la variable 
      "Détail spécimens.Masse (g)" a été saisie. Pour chaque occurrence on vérifie si un enregistrement correspond dans le groupe 
      "Dénombrement par espèce.No pêche" + "Dénombrement par espèce.No pose et levée" + "Dénombrement par espèce.Espèce" + 
      "Dénombrement par espèce. Catégorie de dénombrement" et vérifie si la variable "Dénombrement par espèce.Nbre capturé" existe. 
      Si c'est le cas, vérifie si le nombre inscrit est inférieur au nombre d'enregistrement de l'espèce, si c'est le cas l'utilisateur 
      est averti à l'aide d'un message d'erreur et d'une pastille. Si le nombre capturé n'est pas mesuré, on assigne le nombre 
      d'enregistrement à cette variable. Pour la même occurrence de Détail de spécimen, vérifie si la variable
      "Dénombrement par espèce.Nbre pesé" est mesurée. Si ce n'est pas le cas, assigne à cette variable le nombre d'enregistrements 
      trouvés qui ont une masse de mesurée. Si elle est mesurée et que la valeur diffère de celle calculée, indique un avertissement 
      avec la valeur qui a été calculée. Même procédé par la variable "Dénombrement par espèce.Masse totale (g)" si la valeur n'existe 
      pas, assigne la sommation de tous les spécimens de la même espèce. Si elle existe et que la valeur est différente de celle 
      calculée, indique un avertissement avec la valeur calculée.

   - Validation des occurrences entre Détail des spécimens et Dénombrement par espèce : à la validation du formulaire

      Valide que toutes les "Espèce" présente dans le groupe de variable "Détail spécimens" se retrouvent dans le groupe de 
      variable "Dénombrement par espèce" Et ce pour un même "No pêche" et "No pose et levée"

   - Cohérence des indicateurs contenu stomacal
      si Indicateur contenu stomacal vide (DSP_IND_CONTE_STOMA_VIDE) est coché (oui) 
       Alors les autres indicateurs de contenu stomacal ne devraient pas être coché à savoir 
         Indicateur contenu stomacal insecte (DSP_IND_CONTE_STOMA_INSEC)
         Indicateur contenu stomacal benthos (DSP_IND_CONTE_STOMA_BENTH)
         Indicateur contenu stomacal plancton (DSP_IND_CONTE_STOMA_PLANC)
         Indicateur contenu stomacal chyme (DSP_IND_CONTE_STOMA_CHYME)
         Indicateur contenu stomacal poisson (DSP_IND_CONTE_STOMA_POISS)

   - Cohérence des longueurs : Longueur à la fourche (DSP_LONG_FOURC_MM) et Longueur totale maximale (DSP_LONG_TOT_MAX_M)
      la longueur de la fourche doit être inférieur à la longueur totale maximale
   
   - Valeur obligatoire si espèce est mesuré : 
      si espéce (EFA_CODE) est saisi 
       Alors au moins une de ces valeurs : 
       Longueur totale maximale ; Longueur à la fourche ; Masse ; Sexe ; Maturité sexuelle ; doit être saisi

   - Contenu stomacal - Espèce de poisson 1 (EPO_CODE_STOMA_1) VS Contenu stomacal - Espèce de poisson 2 (EPO_CODE_STOMA_2)
      si les deux valeurs sont saisies elles doivent être différentes 
      Si une seule des deux valeur est sasie alors elle doit être dans Contenu stomacal - Espèce de poisson 1 (donc Contenu stomacal - Espèce de poisson 2 ne peut pas être renseignée lorsque Contenu stomacal - Espèce de poisson 1 est vide)
   
   - Valeur interdite pour le champ Espèce : 
      Espèce ne doit pas contenir les valeurs : RIEN (Aucune espèce), AU (Autre espèce), MULTI (Multi espèces), NI (Espèce non identifiée)

   - si Contenu stomacal - Espèce de poisson 1 ou Contenu stomacal - Espèce de poisson 2 
      si Indicateur contenu stomacal poisson à la valeur non (faux) 
         Alors lui assigner la valeur oui (vrai)
   
   - si Indicateur informations supplémentaires disponibles (DSP_IND_INFOR_SUPPL_DISPO) a la valeur oui (vrai) 
      Alors Emplacement (DSP_VAL_EMPLA) doit aussi avoir une valeur
     si Emplacement (DSP_VAL_EMPLA) est saisit Alors Indicateur informations supplémentaires disponibles (DSP_IND_INFOR_SUPPL_DISPO) doit avoir la valeur oui (vrai) 

   - cohérence TypeType de structure conservée pour déterminer l'âge 1 et Type de structure conservée pour déterminer l'âge 2
      si type structure 1 a une valeur différente de AS (Aucune) et type structure 2 a une valeur différente de AS (Aucune) 
         Alors type structure 1  doit être différent de type structure 2
      
      Type structure 2 ne peut pas avoir une valeur lorsque type structure 1 est vide

   - si Numéro échantillon laboratoire 1 est saisi et Age 1 est saisit 
      Alors Type structure 1 doit avoir une valeur et elle doit être différente de AS (Aucune) 

   - si Numéro échantillon laboratoire 2 est saisi et Age 2 est saisit 
      Alors Type structure 2 doit avoir une valeur et elle doit être différente de AS (Aucune) 

   - Valeurs obligatoires : les champs suivants sont obligatoires
      * Numéro de spécimen (DSP_NO_SPECI)
      * Espèce (EFA_CODE) 
      * Longueur totale maximale ou Longueur à la fourche (au moins une longueur est obligatoire)
      * Masse 
      * Sexe
      * Maturité sexuelle
      * Statut du marquage est obligatoire si Type de marquage est saisi 

   - si Type de marquage a l'une des valeurs : "ABNAG", "AUTRE", "CHIM", "COLOR", "CRYO", "EMETT", "MAGN_C", "MAGN_NC", "PIT_TAG", "THERMI", "THERMO", 
      Alors Description de l'étiquette de marquage (DSP_DESCR_ETIQU_MARQU) doit être saisi
     sinon si Type de marquage a l'une des valeurs : "CARLIN", "EXT_AUT", "SPAGH"
         Alors Couleur de l'étiquette (COU_CODE) et Numéro d'étiquette de marquage (DSP_NO_ETIQU_MARQU) doivent être saisis
   
   - Filtre Type de structure selon espèce 
      si Espèce a l'une des valeurs : "ACFU", "ACOX", "ACSP" Alors type structure = ["AU", "AS", "NP"]
      si Espèce a l'une des valeurs : "ESLU", "ESMA" Alors type structure = ["AU", "AS", "CL", "EC"]
      si Espèce a l'une des valeurs : "MIDO", "MISA" Alors type structure = ["AU", "AS", "OP"]
      si Espèce a l'une des valeurs : "PEFL", "SACA" Alors type structure = ["AU", "AS", "ND", "OP", "OT"]
      si Espèce a l'une des valeurs : "SANA", "SAVI" Alors type structure = ["AU", "AS", "OT"]
      si Espèce a l'une des valeurs : "SAAL", "SAFO" Alors type structure = ["AU", "AS", "OT", "EC"]

   - valeurs obligatoires des couches parents  
      . couche / table Pêche expérimentale : vérifier que les valeurs suivantes sont saisies (Aucun spécimen ne peut être créé tant que toutes les caractéristiques de la pêche ne sont pas saisies) 
         * Type de pêche (TPC_CODE)
         * Espèce visée (EFA_CODE)
         * Type d'engin utilisé (TEG_CODE)
      . couche / table Pose et levée
         * Date de pose (PLF_DATE_POSE)
         * Date de levée (PLF_DATE_LEVEE)
   
   - Numéro d'étiquette - échantillon tissus génétique (DSP_NO_ETIQU_GENET) et Numéro d'étiquette - échantillon tissu contamination (DSP_NO_ETIQU_CONTA)
      Attribuer à ces champs la valeur de Numéro échantillon laboratoire 1 (DSP_NO_ECHAN_LABOR_1)

   - si Espèce a la valeur "CACA" (Meunier rouge) et Longueur totale maximale est saisi et Masse est saisi 
      Alors on calcul 
         coeficient1 = Masse * 100000 / (longueur totale maximale ^ 3) -> doit être suppérieur ou égal à 0.8
         coeficient2 = Masse * 100000 / (longueur totale maximale ^ 3) -> doit être inférieur ou égal à 1.3

   - si Espèce a la valeur "COAR" (Meunier rouge) et Longueur totale maximale est saisi et Masse est saisi 
      Alors on calcul 
         coeficient1 = Masse * 100000 / (longueur totale maximale ^ 3) -> doit être suppérieur ou égal à 0.6
         coeficient2 = Masse * 100000 / (longueur totale maximale ^ 3) -> doit être inférieur ou égal à 1.1

   - si Espèce a la valeur "COCL" (Meunier rouge) et Longueur totale maximale est saisi et Masse est saisi 
      Alors on calcul 
         coeficient1 = Masse * 100000 / (longueur totale maximale ^ 3) -> doit être suppérieur ou égal à 0.6
         coeficient2 = Masse * 100000 / (longueur totale maximale ^ 3) -> doit être inférieur ou égal à 1.4

   


   

# Table / Couche : Dénombrement par espèce (DENOM_ESPEC)

   - Nombre capturé (DES_NB_CAPTU) selon Espèce visée (EFA_CODE) : pendant la saisie de la couche "Dénombrement par espèce" et à la validation du formulaire de saisie

      si Espèce visée (EFA_CODE) est à la valeur "RIEN - Aucune espèce de poisson"
         → Alors Nombre capturé doit être égal à 0 (on assigne automatiquement la valeur 0 à cette variable et on la rend non modifiable)
   
   - Longueur minimale (mm) (DES_LONG_MIN_MM) vs Longueur maximale (mm) (DES_LONG_MAX_MM) : pendant la saisie de la couche "Dénombrement par espèce" et à la validation du formulaire de saisie

      si Longueur minimale (mm) est supérieure à Longueur maximale (mm)
      → Alors afficher un message d'erreur pour informer l'utilisateur de corriger les valeurs

   - Nombre capturé (DES_NB_CAPTU) vs Nombre pesé (DES_NB_PESE) : pendant la saisie de la couche "Dénombrement par espèce" et à la validation du formulaire de saisie

      si Nombre pesé est supérieur à Nombre capturé
      → Alors afficher un message d'erreur pour informer l'utilisateur de corriger les valeurs
   
   - Variables obligatoires : A la validation du formulaire de saisie de la couche "Dénombrement par espèce", et pendant la saisie des données
      si Espèce visée (EFA_CODE) a une valeur (différente de "RIEN - Aucune espèce de poisson")
      → Alors Nombre capturé (DES_NB_CAPTU) doit être renseigné (valeur obligatoire)

         si Masse totale (DES_VAL_MASSE_TOTAL_G) est saisi 
         → Alors Nombre pesé (DES_NB_PESE) doit être saisi (valeur obligatoire)
          
         si Nombre pesé (DES_NB_PESE) est saisi 
         → Alors Masse totale (DES_VAL_MASSE_TOTAL_G) doit être saisi (valeur obligatoire)

   - Catégorie de dénombrement (CDE_CODE) : controle de la valeur saisie
      si Catégorie de dénombrement (CDE_CODE) n'est pas saisi, 
       Alors lui attribuer la valeur '-' (Aucune catégorie)

       

   
# Table / Couche : Autres observations fauniques (AUTRE_OBSER_FAUNI)

   - Territoire faunique vs Région administrative du projet : à l'ouverture du formulaire de saisie de la couche "Autres observations fauniques"
   
      Filtrer le champ "Territoire faunique" pour n'afficher que les territoires fauniques situés dans la région administrative du projet. (cas particulier : pour la région 04 - Mauricie, filtrer les territoires fauniques avec 04 - Mauricie et 17 - Centre-du-Québecc)

      à la validation du formulaire de saisie de la couche "Autres observations fauniques" :

      si Type de plan d'eau de "information générales" à la valeur 'L-lac'
      → Alors ne pas mesurer territoire faunique (on le désactive du formulaire)
      sinon mesurer (on laisse activer le champ territoire faunique)


   - Date de l'observation : pendant la saisie de la couche "Autres observations fauniques" et à la validation du formulaire de saisie
      si la date n'est pas renseignée
      → Alors lui assigner la valeur de date de début d'inventaire de la table "Informations générales"

      La date de l'observation doit être supérieure à la date de debut d'inventaire et inférieure à la date de fin d'inventaire de la table/couche "Informations générales". Si ce n'est pas le cas, un message d'erreur doit être affiché pour informer l'utilisateur de corriger la date.

      la date de l'observation est obligatoire si elle n'est pas renseignée, la valeur par défaut est la date de début d'inventaire de la table "Informations générales"

   - Espèce visée (EFA_CODE) : pendant la saisie de la couche "Autres observations fauniques" et à la validation du formulaire de saisie
      
      Valeur obligatoire

      si catégorie d'espèce est mesurée 
         si espèce visée est à la valeur "A - Amphibien"
            filtrer le champ "Espèce visée" avec "A - Amphibien"
         sinon si espèce visée est à la valeur "C - Crustacé"
            filtrer le champ "Espèce visée" avec "C - Crustacé"
         sinon si espèce visée est à la valeur "MA - Mammifère"
            filtrer le champ "Espèce visée" avec "MA - Mammifère"
         sinon si espèce visée est à la valeur "MO - Mollusque"
            filtrer le champ "Espèce visée" avec "MO - Mollusque"
         sinon si espèce visée est à la valeur "O - Oiseau"
            filtrer le champ "Espèce visée" avec "O - Oiseau"
         sinon si espèce visée est à la valeur "R - Reptile"
            filtrer le champ "Espèce visée" avec "R - Reptile"
         sinon si espèce visée est à la valeur "PP - Plantes Précaires"
            filtrer le champ "Espèce visée" avec "PP - Plantes Précaires"
         sinon aucun filtre n'est appliqué sur le champ "Espèce visée" (on affiche toutes les espèces)
      sinon aucun filtre n'est appliqué sur le champ "Espèce visée" (on affiche toutes les espèces)
   
   - Catégorie d'espèce (CEF_CODE)
      Valeur obligatoire 

   - Latitude (AOF_LATIT) et Longitude (AOF_LONGIT)
      Valeurs obligatoires


# Table / Couche : Pêche expérimentale (PECH_EXPERI)

   - Date de pose du filet (PLF_DATE_POSE) & Date de levée du filet (PLF_DATE_LEVEE) : pendant la saisie de la couche "Pêche expérimentale"
    
      Lors de la saisie de la variable "Date de pose du filet", assigne automatiquement la date
      du lendemain à la variable "Date de levée du filet".


   
# Table / Couche : Habitat (HABITAT) 

   - Historique des habitats : lorsqu'on clique sur le bouton "Consulter l'historique des habitats" dans la couche "Habitat"

      Permet de consulter sous forme de rapport, l'historique de tous les
      habitats de cette unité d'échantillonnage, pour tous les mesurages.

         les champs suivants : DATE     |  NO  | CODE | LATITU | LONGIT | SUPERF |     NOM     |  QUALIF 

      La liste doit être triée par date de début d'habitat, du plus récent au plus ancien.

   
# Table / Couche : Pertubation (PERTUBATION)

   - Historique des Pertubations : lorsqu'on clique sur le bouton "Consulter l'historique des Pertubations" dans la couche "Pertubation"

      Permet de consulter sous forme de rapport, l'historique de toutes les
      perturbations de cette unité d'échantillonnage, pour tous les mesurages.
.

         les champs suivants :   DATE      |    TYPE    |    LATITUDE    |    LONGITUDE    |    SUPERFICIE    |    CORRECTIF 

      La liste doit être triée par date de début de mesurage, du plus récent au plus ancien.


# Table / Couche : Description de l'habitat (DESCR_HABIT)

   - Date (DHA_DATE) : A la validation du formulaire 
      La date est obligatoire

      si la date n'est pas renseignée
      → Alors lui assigner la valeur de date de début d'inventaire de la table "Informations générales"

   - Profondeur de la prise de données de vitesse du courant (DHA_PRFD_VITES_COURA) : A la validation du formulaire 
      si Vitesse courant avec profondeur (DHA_VAL_VITES_COURA) est saisie et Profondeur donnée courant n'est pas renseigée
      → Alors assigner à Profondeur donnée courant la valeur 0
   
   - Superficie (DHA_SUPRF) : A la validation et pendant la saisie du formulaire
      si longueur est saisie et largeur est saisie 
      → Alors assigner à Superficie la valeur longueur x largeur 
   
   - Territoire faunique (DHA_NOM_TERRI_FAUNI) : pendant la saisie et à la validation
      Filtrer les valeurs du territoire faunique en fonction de la région administrative (même algorithme que pour la couche Analyse-physico-chimique)
      si Type de plan d'eau de "information générales" à la valeur 'L-lac'
      → Alors ne pas mesurer territoire faunique (on le désactive du formulaire)
      sinon mesurer (on laisse activer le champ territoire faunique)
   


   

   


   