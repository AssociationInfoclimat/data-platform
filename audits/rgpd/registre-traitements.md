# Registre des traitements de données personnelles — volet data-platform

> **Document généré** par `tools/build_rgpd_register.py` depuis `audits/rgpd/traitements.yaml`. Ne pas éditer à la main — modifier la source.

Ce registre recense **où vivent les données personnelles** dans le système d'information, regroupées par finalité. Il constitue la contribution technique de la data-platform au registre des traitements de l'association (art. 30 RGPD).

Les champs juridiques (**base légale**, **durée de conservation**, mesures de sécurité) relèvent du bureau de l'association et sont à confirmer — ils figurent ici en l'état pour être complétés, non comme position arrêtée.

**10 traitements**, **32 tables** porteuses de données personnelles (source de vérité du périmètre : `inventory/tables.yaml`, flag `personal_data`).

## Gestion des comptes utilisateurs et de l'authentification

- **Identifiant** : `comptes-authentification`
- **Personnes concernées** : Membres inscrits du site
- **Données** : Identité (pseudo), secret (mot de passe haché), email de contact, IP et user-agent de connexion, jetons de session et de réinitialisation
- **Base légale** : à confirmer (exécution du service / consentement à l'inscription)
- **Conservation** : à confirmer (jetons à expiration ; comptes ?)
- **Contrat de données** : [`v5-comptes-utilisateurs`](../../contracts/v5-comptes-utilisateurs.odcs.yaml)
- **Tables** :
    - `mariadb://V5/comptes`
    - `mariadb://V5/comptes_pseudos`
    - `mariadb://V5/comptes_reinitialisations`
    - `mariadb://V5/comptes_statuts`
    - `mariadb://V5/comptes_tokens`
    - `mariadb://V5/connectes`

## Notifications push et paramètres des applications mobiles

- **Identifiant** : `applications-mobiles`
- **Personnes concernées** : Utilisateurs des applications iOS/Android
- **Données** : Jetons d'appareil (APNS/FCM), paramètres applicatifs liés au compte
- **Base légale** : à confirmer (consentement aux notifications)
- **Conservation** : à confirmer
- **Contrat de données** : —
- **Tables** :
    - `mariadb://V5/apns_devices`
    - `mariadb://V5/gcm_devices`
    - `mariadb://V5/appli_params`
    - `mariadb://V5/appli_tokens`

## Contributions des membres (observations, photos, messages, lieux favoris)

- **Identifiant** : `contributions-communautaires`
- **Personnes concernées** : Membres contributeurs
- **Données** : Lien compte (id_compte), géolocalisation des contributions, contenus, messages privés
- **Base légale** : à confirmer
- **Conservation** : à confirmer
- **Contrat de données** : [`photolive`](../../contracts/photolive.odcs.yaml)
- **Tables** :
    - `mariadb://V5/personnes`
    - `mariadb://V5/personnes_coordonnees`
    - `mariadb://V5/lieux_preferes`
    - `mariadb://V5/mp_mp`
    - `mariadb://V5/electric_users`

## Gestion des adhérents, cotisations et votes de l'association

- **Identifiant** : `vie-associative`
- **Personnes concernées** : Adhérents de l'association
- **Données** : Identité, coordonnées, paiements (dont HelloAsso), pouvoirs de vote
- **Base légale** : à confirmer (obligation légale comptable / exécution de l'adhésion)
- **Conservation** : à confirmer (obligations comptables et statutaires)
- **Contrat de données** : —
- **Tables** :
    - `mariadb://asso/asso_adherants`
    - `mariadb://asso/paiements`
    - `mariadb://asso/paiements_helloasso`
    - `mariadb://asso/pouvoirs`

## Traitement des commandes de la boutique

- **Identifiant** : `boutique`
- **Personnes concernées** : Clients de la boutique
- **Données** : Identité, coordonnées de livraison, données de commande
- **Base légale** : à confirmer (exécution du contrat de vente)
- **Conservation** : à confirmer (obligations comptables)
- **Contrat de données** : —
- **Tables** :
    - `mariadb://V5/boutique_commandes`

## Participation aux concours de prévision et aux rencontres

- **Identifiant** : `concours-rencontres`
- **Personnes concernées** : Membres participants
- **Données** : Lien compte, inscriptions
- **Base légale** : à confirmer
- **Conservation** : à confirmer
- **Contrat de données** : —
- **Tables** :
    - `mariadb://concoursprevi/participants_v5`
    - `mariadb://V5_rencontres/participants_v5`

## Habilitations de l'équipe prévision et bulletins

- **Identifiant** : `equipe-prevision`
- **Personnes concernées** : Prévisionnistes habilités
- **Données** : Lien compte, pseudo, périmètre d'habilitation
- **Base légale** : à confirmer
- **Conservation** : à confirmer
- **Contrat de données** : [`previsions-bulletins`](../../contracts/previsions-bulletins.odcs.yaml)
- **Tables** :
    - `mariadb://V5_prevs/previsionnistes`
    - `mariadb://V5_chroniques/bqs_users`

## Rattachement des stations à leurs propriétaires et exploitation réseau

- **Identifiant** : `reseau-stations`
- **Personnes concernées** : Propriétaires de stations
- **Données** : Lien compte propriétaire, adresses IP des stations
- **Base légale** : à confirmer
- **Conservation** : à confirmer
- **Contrat de données** : [`static-stations-obs`](../../contracts/static-stations-obs.odcs.yaml)
- **Tables** :
    - `mariadb://V5_data_params/static_ip`
    - `mariadb://V5_climato/postes`

## Accès FTP de service

- **Identifiant** : `services-techniques`
- **Personnes concernées** : Comptes techniques / partenaires
- **Données** : Identifiants FTP
- **Base légale** : à confirmer
- **Conservation** : à confirmer
- **Contrat de données** : —
- **Tables** :
    - `mariadb://proftpd/ftpuser`

## Forum communautaire (plateforme IPBoard)

- **Identifiant** : `forum`
- **Personnes concernées** : Membres du forum
- **Données** : Profils et sessions des membres
- **Base légale** : à confirmer
- **Conservation** : gérée par IPBoard — hors périmètre data-platform
- **Contrat de données** : [`forums2-ipboard`](../../contracts/forums2-ipboard.odcs.yaml)
- **Note** : Base applicative tierce (IPBoard), gestion autonome. Les tables forums/ibf_* sont mortes (ancienne version, candidates à suppression — à confirmer côté RGPD).
- **Tables** :
    - `mariadb://forums2/core_members`
    - `mariadb://forums2/core_sessions`
    - `mariadb://forums/ibf_core_members`
    - `mariadb://forums/ibf_members`
    - `mariadb://forums/ibf_sessions`

