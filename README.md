# PokéVeille 30 — veille et comparaison de prix Pokémon (30e anniversaire)

Bot Discord en français qui repère les produits Pokémon du 30e anniversaire sur le marché français.
Il compare leurs prix, avec Amazon.fr comme référence, et prévient l'utilisateur quand un produit
suivi passe sous un prix maximum ou revient en stock.

- Priorité au JCC : boosters, coffrets, mini-boîtes, classeurs, decks, Coffrets Dresseur d'élite,
  collections Premium et Ultra-Premium. Les produits dérivés (peluches, figurines…) sont aussi gérés.
- Prix total = prix + livraison + frais obligatoires connus. Si la livraison est inconnue, le bot
  écrit « frais de livraison à vérifier » et ne présente jamais le total comme exact.
- Reconnaissance stricte des produits : EAN → ASIN / référence → nom exact → édition, langue,
  contenu, variante, état et gradation.
- Protection contre les fausses bonnes affaires : prix anormalement bas, vendeur inconnu, mots
  « copie / proxy / reproduction / personnalisé », produit ouvert vendu comme scellé, absence de
  référence, frais de port élevés.
- **Le bot n'achète jamais rien et ne demande jamais de coordonnées bancaires.**

> ⚠️ **Mode démo** : tous les produits et prix de `data/demo/` sont **FICTIFS**. Les noms
> commencent par « DÉMO », les liens pointent vers `exemple.invalid` et chaque message affiche
> « DONNÉES FICTIVES ».

---

## 1. Installation (Windows, PowerShell)

Prérequis : Python 3.11 ou plus récent (testé avec 3.14).

```powershell
cd chemin\vers\le\projet
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## 2. Essayer tout de suite (mode démo, sans clé API)

Le mode démo en ligne de commande ne demande aucune installation de paquets.

```powershell
py -m pokebot demo                    # gamme anniversaire + une fiche détaillée
py -m pokebot fiche demo_booster      # comparatif d'un produit
py -m pokebot recherche pikachu       # recherche
py -m pokebot alerte-test demo_etb 55 # simule deux vérifications d'alerte
py -m pokebot sources                 # état des sources
```

Lancer les tests :

```powershell
py -m unittest discover -s tests -t .
```

## 3. Lancer le bot Discord

1. Sur le [Discord Developer Portal](https://discord.com/developers/applications), cliquez sur
   **New Application**. Dans l'onglet **Bot**, cliquez sur **Reset Token** et copiez le jeton.
   Aucun « Privileged Gateway Intent » n'est nécessaire, sauf si vous relayez des salons suivis
   (§ 4.5 : « Message Content Intent »).
2. Onglet **OAuth2 › URL Generator** : cochez les scopes `bot` et `applications.commands`, puis
   les permissions **Send Messages** et **Read Message History**. Ouvrez l'URL générée pour inviter
   le bot sur votre serveur.
3. Dans `.env` :
   - `DISCORD_BOT_TOKEN=...` (laissez `BOT_MODE=demo` pour commencer) ;
   - `DISCORD_GUILD_ID=...`, conseillé : les commandes apparaissent tout de suite sur ce serveur.
     Pour trouver l'identifiant : Paramètres Discord › Avancés › Mode développeur, puis clic droit
     sur le serveur › Copier l'identifiant ;
   - facultatif : `DISCORD_UTILISATEURS_AUTORISES=<votre identifiant>` pour réserver le bot à vous.
4. Lancez :

```powershell
.\.venv\Scripts\python.exe -m pokebot bot
```

**Démarrage automatique avec Windows** : un raccourci « PokeVeille bot » dans le dossier Démarrage
(`Win+R` › `shell:startup`) lance `scripts\demarrer_bot_cache.vbs`, qui exécute
`scripts\demarrer_bot.cmd` sans fenêtre. Le bot est relancé 60 s après un arrêt (coupure réseau…),
son journal est dans `data\bot.log`, et un second lancement est refusé (un seul bot par PC, sinon
chaque alerte partirait en double). Pour l'arrêter : Gestionnaire des tâches › `python.exe`
(et `cmd.exe` du lanceur) ; pour le désactiver : supprimez le raccourci.

Toutes les commandes sont des **commandes slash**. Discord propose les options et complète
automatiquement les noms de produits.

| Commande | Rôle |
|---|---|
| `/aide` | commandes et explication des avis (remplace `/start`) |
| `/recherche mot_cle:` | rechercher un produit |
| `/anniversaire` | produits repérés de la gamme 30e anniversaire |
| `/fiche produit:` | comparatif détaillé d'un produit |
| `/alerte produit: prix_max:` | créer une alerte (ex. `prix_max:49,90`) : baisse sous le prix max, retour en stock, bon plan Le CrocoDeal |
| `/alertes` · `/supprimer_alerte numero:` | lister ou supprimer ses alertes |
| `/favoris` · `/suivre produit:` · `/retirer produit:` | produits suivis |
| `/preferences` | prix max, catégorie, état, langue, sites, fréquence (« aucun » retire un réglage) |
| `/sorties` | calendrier des sorties : date annoncée, compte à rebours, dernière info (§ 4.5) |
| `/drop produit: magasin: ville: details:` | signaler un arrivage en magasin ; prévient ceux qui suivent le produit |
| `/drops produit:` | arrivages signalés sur 30 jours et jours où ils reviennent le plus |
| `/sources` | état de chaque source de prix et de la veille |
| `/oubliermoi` | effacer toutes ses données |

Les réponses qui concernent vos données (préférences, alertes, favoris, sources) sont
**éphémères** : vous seul les voyez, même dans un salon public. Les recherches et les fiches
sont visibles par le salon.

Le choix des sites filtre les offres affichées et alertées. La référence Amazon et la médiane
restent calculées sur tout le marché.

Le bot vérifie les alertes à la fréquence choisie, avec un minimum de 15 minutes
(`config/parametres.toml`). Il vous écrit **en message privé**. Si vos messages privés sont
fermés, il vous mentionne dans le salon où l'alerte a été créée. Il prévient quand :
- la meilleure offre fiable passe sous votre prix maximum. Un nouveau message n'est envoyé que si le prix baisse encore ;
- le produit revient en stock.

Les offres suspectes (copie, produit ouvert, mauvaise langue ou mauvais état, correspondance
incertaine) ne déclenchent jamais d'alerte.

## 4. Passer aux données réelles

Dans `.env`, mettez `BOT_MODE=reel`. Ensuite :

### 4.1 Catalogue officiel : `data/catalogue.csv`

Le site pokemon.com/fr ne propose pas d'API produits publique documentée. Le catalogue de
référence se remplit donc **à la main**, à partir des pages officielles (une ligne par produit).

| Colonne | Exemple / remarque |
|---|---|
| `id` | `etb_anniv_fr` (lettres, chiffres, `_`) |
| `nom` | nom exact du produit |
| `categorie` | `booster`, `coffret dresseur d'élite`, `collection ultra-premium`, `peluche`… |
| `type` | `scelle`, `derive`, `carte`, `carte_gradee` |
| `langue` | `fr`, `en`, `ja`… |
| `gamme` | doit contenir « anniversaire » pour apparaître dans `/anniversaire` |
| `ean`, `asin`, `ref_fabricant` | identifiants (EAN vérifié par clé de contrôle). Pour une carte : son numéro |
| `edition`, `contenu`, `variante` | si renseignés, l'annonce doit les préciser pour être jugée identique |
| `etat_carte`, `societe_gradation`, `note_gradation` | cartes à l'unité / gradées |
| `lien_officiel` | URL de la page pokemon.com/fr |
| `prix_conseille` + `source_prix_conseille` | **seulement** si une source officielle le publie (sinon laisser vide) |

Le fichier `data/demo/catalogue_demo.csv` sert de modèle. `data/catalogue.csv` est déjà rempli avec
les 22 produits du 30e anniversaire (provenance de chaque EAN et ASIN : `data/SOURCES_CATALOGUE.md`).

### 4.2 Amazon.fr : Creators API (référence principale)

PA-API 5 est dépréciée. Ses anciennes clés renvoient une erreur 403. Le bot utilise la
**Creators API** officielle.

1. Avoir un compte **Partenaires Amazon (amazon.fr)** actif.
2. Accès soumis à conditions : Amazon demande **au moins 10 ventes qualifiantes sur les 30 derniers
   jours**. L'accès peut être retiré après 30 jours sans vente.
3. Dans Associates Central, générez des identifiants Creators API. Vous obtiendrez un
   **Credential ID**, un **Credential Secret** et une **Version** (3.2 pour l'Europe).
4. Remplissez `.env` : `AMAZON_CREDENTIAL_ID`, `AMAZON_CREDENTIAL_SECRET`,
   `AMAZON_CREDENTIAL_VERSION=3.2`, `AMAZON_PARTNER_TAG` (votre identifiant de suivi).

Fonctionnement technique : jeton OAuth (« client credentials »), puis
`POST https://creatorsapi.amazon/catalog/v1/searchItems` (ou `getItems` si l'ASIN est connu), avec
l'en-tête `x-marketplace: www.amazon.fr`. Quota de départ : 1 requête/seconde et 8 640 par jour.
Le bot espace ses appels et garde les résultats en cache 15 minutes.

Limites à connaître :
- La réponse (`offersV2`) ne donne **ni les frais de livraison, ni la note du vendeur**. Les offres
  Amazon s'affichent donc « frais de livraison à vérifier ». Vous pouvez saisir votre propre barème
  (`livraison_estimee`, `livraison_gratuite_des`) dans `[sources.amazon_fr]`. Le total est alors
  marqué « estimé ».
- Un vendeur tiers sur Amazon n'est jamais retenu comme référence si sa réputation est inconnue.
- Deux points de la documentation sont ambigus et sont lus des deux façons possibles : le nom de
  l'enveloppe GetItems et le format des EAN. Vérifiez-les avec `-v` sur une première vraie réponse.
- Sans accès API, le bot reste utilisable et affiche « prix Amazon non vérifié ».

### 4.3 Autres magasins et Cardmarket

| Source | État | Pourquoi / que faire |
|---|---|---|
| Fnac, Cultura, JouéClub, King Jouet | ⛔ connecteur désactivé | Aucune API publique de recherche produit documentée. Activable avec un flux produits ou un programme partenaire **autorisé par l'enseigne**. |
| Cardmarket | ⛔ connecteur désactivé | API soumise à l'accord de Cardmarket. Pas de scraping. |
| pokemon.com/fr | ⛔ non automatisé | Catalogue tenu à la main (§ 4.1). |
| Le CrocoDeal | ✅ actif (flux RSS) | Bons plans communautaires, voir § 4.4. |

Le bot ne fait **aucun scraping**. Il ne contourne ni CAPTCHA, ni connexion obligatoire, ni
protection anti-robots.

**Solution de secours : `data/offres_manuelles.csv`.** Vous y notez les offres relevées
vous-même. Les colonnes sont les mêmes que dans `data/demo/offres_demo.csv`. `verifie_le`
(date ISO) est obligatoire. Laissez `livraison` vide si vous ne la connaissez pas. Pour Cardmarket,
`vente_reelle=1` indique un prix réellement payé, et non une annonce.

Pour intégrer une source autorisée : créez une classe dans `pokebot/connecteurs/` qui hérite de
`Connecteur`, implémentez `_rechercher(requete) -> list[Offre]` et ajoutez-la dans
`pokebot/connecteurs/__init__.py`.

### 4.4 Le CrocoDeal : bons plans communautaires

Le bot lit le **flux RSS public** de recherche de lecrocodeal.com
(`https://lecrocodeal.com/?s=pokemon&feed=rss2`). Il fait une seule requête toutes les 30 minutes,
avec un User-Agent identifiable. Il ne suit jamais les liens de redirection `/go/` et `/visit/`
(interdits par leur `robots.txt`) et renvoie toujours vers l'article du bon plan.

- **Ce qui est repris** : titre, lien, date de publication, enseigne citée et prix annoncé dans le
  texte (« à 44,99 € », jamais le prix barré « au lieu de »). Si plusieurs enseignes sont citées,
  le bon plan n'est attribué à aucune.
- **Ce qui est ignoré** : les articles « Où acheter… ? » et les annonces de sortie (pas de prix),
  les bons plans de plus de `age_max_jours` jours (14 par défaut), ceux sans prix lisible.
- **Comment c'est affiché** : « bon plan Le CrocoDeal », « publié le … », avis ⚠️ **À vérifier**.
  Stock, vendeur et livraison ne sont pas confirmés. Ces prix ne servent **jamais** de référence
  Amazon ni dans la médiane, et ne déclenchent pas l'alerte « sous votre prix maximum ».
- **Alerte dédiée 📣 « Bon plan signalé »** : pour un produit suivi avec `/alerte`, le bot vous
  prévient quand un **nouveau** bon plan est publié sous votre prix maximum. Il écarte les mentions
  de copie, de produit ouvert, d'autre langue ou d'autre état. À la création de l'alerte, les bons
  plans déjà publiés ne sont pas renvoyés.

Réglages dans `[sources.lecrocodeal]` : `actif`, `recherche` (terme du flux), `age_max_jours`,
`cache_secondes`.

### 4.5 Veille des sorties et des drops

**Constat** : aucune enseigne (Carrefour, Leclerc, Auchan, Maison de la Presse, Relay…) ne publie
son stock en magasin par API ou par flux, et leurs sites bloquent les robots. Le bot ne les
interroge donc pas. Il combine à la place quatre sources légitimes, plus vos propres signalements :

| Source | Ce qu'elle apporte | Accès |
|---|---|---|
| **Poképédia** | date de sortie en France de chaque produit (et son EAN) | API MediaWiki publique, toutes les 12 h, contenu CC BY-NC-SA (source citée, usage personnel) |
| **Le CrocoDeal** | articles « Où acheter… ? », reports de date, enseignes à surveiller | flux RSS public |
| **Fnac — L'Éclaireur** | ventes spéciales Pokémon (tirages Fnac+, dates de mise en vente) | flux RSS du blog, filtré sur « Pokémon » |
| **Salons Discord suivis** | restocks et arrivages publiés par des communautés | fonction « Suivre » de Discord (voir ci-dessous) |
| **`/drop`** | arrivages repérés par les membres de votre serveur | commande du bot |

Pour un produit en **alerte** ou en **favori**, vous recevez en message privé :
📅 une date de sortie annoncée ou modifiée (report), ⏰ un rappel la veille de la sortie,
📰 un nouvel article qui cite le produit, 🏬 un arrivage signalé. À la toute première lecture
d'une source, le bot mémorise l'existant sans rien envoyer.

Les produits sont reconnus dans le texte par leur EAN, ou par leur nom (« ETB 30 ans »,
« UPC Mentali ») avec la gamme et la variante : un article sur l'ETB d'une autre extension ou sur
la Pokébox n'est pas rattaché au coffret.

**Relayer un serveur de restock (salons suivis)**
1. Rejoignez un serveur communautaire de restock français et repérez un **salon d'annonces**
   (icône mégaphone). Cliquez sur **Suivre** et choisissez un salon de **votre** serveur.
2. Clic droit sur ce salon de votre serveur › **Copier l'identifiant**, puis dans `.env` :
   `DISCORD_SALONS_VEILLE=<identifiant>` (plusieurs : séparés par des virgules).
3. Developer Portal › votre application › **Bot** › activez **Message Content Intent**.
4. Relancez le bot. Seuls les messages qui citent un produit du catalogue sont relayés, avec
   l'enseigne et le code postal s'ils sont écrits. Respectez les règles du serveur d'origine.

Les dates sont des dates **annoncées** : elles changent souvent, et Poképédia n'enregistre pas
toujours les reports aussitôt. Un arrivage signalé n'est **jamais vérifié** par le bot : appelez le
magasin avant de vous déplacer. Réglages : section `[veille]` de `config/parametres.toml`,
`[sources.pokepedia]` et `[sources.fnac_eclaireur]`. En mode démo, seule la commande `/drop`
fonctionne (aucune requête réseau). En console : `py -m pokebot sorties` et `py -m pokebot drops`.

### 4.6 Version « site + webhook » (gratuite, sans carte bancaire, PC éteint)

GitHub Actions exécute `py -m pokebot tache` toutes les 30 minutes :
1. lecture de la veille (Poképédia, Le CrocoDeal, Fnac) et des prix des produits de `config/suivi.toml` ;
2. nouveautés postées dans un salon Discord par **webhook** (aucun bot connecté) ;
3. site statique publié sur **GitHub Pages** : calendrier, dernières infos, bons plans, fiche par produit.

La base SQLite est conservée entre deux exécutions dans la branche `donnees` (un seul commit réécrit).
Le site est public (aucune donnée personnelle : seulement prix et dates).

**Mise en place**
1. Compte GitHub gratuit, dépôt **public** contenant ce projet (`.env` n'est jamais envoyé : il est
   dans `.gitignore`).
2. Discord : Paramètres du serveur › Intégrations › Webhooks › **Nouveau webhook**, choisissez le
   salon, **Copier l'URL du webhook**.
3. GitHub : dépôt › Settings › Secrets and variables › Actions › **New repository secret** :
   `DISCORD_WEBHOOK_URL` = l'URL copiée (facultatif : `AMAZON_CREDENTIAL_ID`,
   `AMAZON_CREDENTIAL_SECRET`, `AMAZON_PARTNER_TAG`).
4. GitHub : Settings › Pages › Source : **GitHub Actions**.
5. Onglet **Actions** › « Veille PokéVeille » › **Run workflow** pour le premier passage (il mémorise
   l'existant sans rien poster).

Produits suivis et prix maximum : `config/suivi.toml` (modifiable sur GitHub avec le crayon ; chaque
modification relance une exécution). Essai local : `py -m pokebot tache --sans-envoi` (base séparée
`data/pokeveille_site.sqlite3`, site dans `site/`).

Différences avec le bot : pas de commandes slash ni de messages privés, pas de `/drop`, pas de tri des
salons suivis (les alertes Alert&Go arrivent quand même dans votre salon, gérées par Discord). GitHub peut
retarder les exécutions programmées de quelques minutes, et suspend celles d'un dépôt public sans
activité pendant 60 jours (la branche `donnees` est réécrite à chaque passage).

## 5. Règles de l'avis du bot

Tous les seuils se modifient dans `config/parametres.toml`, section `[seuils]`.

| Avis | Règle (produits scellés et dérivés) |
|---|---|
| 🟢 Très bonne affaire | total ≤ 90 % de la référence Amazon **et** ≤ 95 % de la médiane |
| 🔵 Prix raisonnable | total ≤ +5 % de la référence Amazon **ou** de la médiane |
| 🟠 Un peu cher | entre les deux |
| 🔴 Cher | total > +10 % de la référence Amazon **et** de la médiane |
| ⚠️ À vérifier | prix < 60 % de la référence du marché, vendeur inconnu ou peu fiable, frais inconnus, copie possible, produit ouvert, sans référence, correspondance incertaine |
| ⚪ Comparaison insuffisante | pas assez de données, ou état non comparable (occasion face à du neuf) |

- **Référence Amazon** : offre Amazon.fr disponible, neuve et identique. Une offre vendue et
  expédiée par Amazon est prioritaire. Sinon, c'est un vendeur tiers fiable, signalé comme tel.
- **Médiane** : au moins 3 offres comparables, disponibles, à total connu, de vendeurs fiables
  (Amazon, enseignes, ou vendeurs avec ≥ 95 % d'avis positifs et ≥ 50 avis).
- S'il n'existe qu'une seule référence, « très bonne affaire » n'est pas attribuée. L'option
  `exiger_deux_references` permet de changer ce comportement.
- **Cartes à l'unité / gradées** : comparées seulement entre elles, sans Amazon, avec la même carte,
  la même langue, le même état et, pour une carte gradée, la même société et la même note.
  Les ventes réellement conclues sont affichées à part.

## 6. Structure

```
pokebot/
  models.py          produits, offres, préférences
  correspondance.py  reconnaissance produit (EAN, ASIN, nom, attributs)
  risques.py         signaux de fausses bonnes affaires
  analyse.py         prix total, références, avis, classement
  alertes.py         prix maximum, retour en stock et bons plans signalés
  comparateur.py     orchestration catalogue + connecteurs + historique
  base.py            SQLite : historique des prix, préférences, favoris, alertes, annonces, dates de sortie
  veille.py          reconnaissance des produits et des dates dans un texte libre
  sources_veille.py  Poképédia (API), flux RSS d'annonces (Le CrocoDeal, Fnac L'Éclaireur)
  service_veille.py  veille des sorties et des drops (nouveautés, reports, rappels, /drop, salons suivis)
  affichage_veille.py  mise en forme de la veille
  affichage.py       mise en forme française (Markdown Discord / console)
  discord_bot.py     bot Discord (commandes slash, alertes en message privé)
  connecteurs/       amazon.py (Creators API), lecrocodeal.py (flux RSS), fichiers.py (démo, CSV),
                     non_integres.py
config/parametres.toml   seuils, sources, fréquences
data/demo/               données FICTIVES
data/catalogue.csv       catalogue réel : 22 produits du 30e anniversaire
data/offres_manuelles.csv  vos relevés manuels (vide au départ)
tests/                   tests unitaires et de bout en bout (démo)
```

## 7. Données personnelles et sécurité

- Données stockées : votre identifiant d'utilisateur Discord, l'identifiant du salon où vous avez
  créé une alerte (pour la livrer si vos messages privés sont fermés), vos préférences, favoris et
  alertes, et l'auteur des arrivages que vous signalez avec `/drop`. Rien d'autre. `/oubliermoi`
  efface tout ; vos `/drop` restent visibles des autres membres mais ne sont plus rattachés à vous.
- Les messages des salons suivis ne sont lus que dans les salons listés dans `DISCORD_SALONS_VEILLE`,
  et seuls ceux qui citent un produit du catalogue sont conservés (sans leur auteur).
- Les secrets ne vont que dans `.env`, qui est exclu par `.gitignore`. Ne partagez jamais ce fichier.
- La démo utilise une base séparée (`data/pokeveille_demo.sqlite3`) pour ne jamais mélanger fictif et réel.
- Historique des prix : une ligne est ajoutée à chaque changement de prix, de livraison ou de stock.
  Les lignes de démo sont marquées.
