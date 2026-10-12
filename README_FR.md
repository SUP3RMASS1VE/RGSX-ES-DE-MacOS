# 🎮 RGSX pour macOS (ES-DE, Apple Silicon)

**[Installation](#-installation)** • **[Dépannage](#-dépannage)** • **[Documentation anglaise](README.md)** • **[Issues](https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS/issues)** • **[Projet d'origine (upstream)](https://github.com/RetroGameSets/RGSX)**

Un téléchargeur de ROMs gratuit et simple d'utilisation, qui fonctionne dans [ES-DE](https://es-de.org) (EmulationStation Desktop Edition) sur les Mac Apple Silicon, avec support multi-sources.

Ce dépôt est un **fork uniquement macOS** de [RetroGameSets/RGSX](https://github.com/RetroGameSets/RGSX) (Retro Game Sets Xtra), le téléchargeur de ROMs pour Batocera, Knulli et RetroBat. Tout le mérite de RGSX revient aux auteurs et contributeurs du projet d'origine. Ce fork ne contient que le portage macOS (Apple Silicon, arm64) lancé depuis ES-DE. Pour Batocera, Knulli, RetroBat ou Docker, utilisez le [projet d'origine](https://github.com/RetroGameSets/RGSX).

<p align="center">
  <img width="69%" alt="main" src="https://github.com/user-attachments/assets/a98f1189-9a50-4cc3-b588-3f85245640d8" />
  <img width="30%" alt="aide contrôles" src="https://github.com/user-attachments/assets/38cac7e6-14f2-4e83-91da-0679669822ee" />
</p>
<p align="center"><sub>Captures d'écran du projet d'origine.</sub></p>

---

## 🚀 Installation

Rien à installer : ni Homebrew, ni terminal, ni Python. RGSX télécharge ce dont il a besoin au premier lancement.

1. Téléchargez le zip depuis les [releases](https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS/releases/latest) de ce fork (`RGSX_macos_arm64.zip`) et décompressez-le. Ou clonez le dépôt : `git clone https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS.git`.
2. Déplacez le dossier `ports` dans votre dossier ROMs d'ES-DE (par défaut `~/ES-DE/ROMs`). Tout dossier ROMs convient tant que RGSX se trouve dans `<ROMs>/ports/RGSX`. Si vous avez déjà un ancien `ports/RGSX`, remplacez-le au lieu de fusionner.
3. Dans ES-DE, ouvrez **Ports > RGSX**.
4. Premier lancement uniquement : RGSX télécharge environ 60 Mo. Comptez quelques minutes selon votre connexion. Une fenêtre Terminal avec la progression et une petite boîte de dialogue apparaissent ; un écran vide un instant est normal. Gardez le Mac connecté. Les lancements suivants démarrent en quelques secondes et fonctionnent hors ligne.
   - Une fenêtre Terminal restante après l'installation est normale et peut être fermée.
   - ES-DE peut lancer le script avec `/bin/sh`, bash ou zsh ; le lanceur fonctionne avec les trois.
   - Visuels facultatifs : copiez `ports/gamelist.xml` et `ports/images` dans `~/ES-DE/gamelists/ports` et `~/ES-DE/downloaded_media` (RGSX n'écrit jamais dans `~/ES-DE`).

### Ce que RGSX installe automatiquement

Au premier lancement, dans `~/Library/Application Support/RGSX/runtime` (environ 200 Mo) :

- Un runtime Python 3.12 figé (arm64)
- Les paquets Python nécessaires à RGSX (avec empreintes vérifiées)
- libtorrent, pour les sources torrent
- 7-Zip (`7zz`), pour les archives, RAR compris

Le runtime est conservé si vous remplacez le dossier `ports` : une mise à jour ne le retélécharge pas.

### Emplacements

- Paramètres, logs, contrôles, historique, clés API : `~/Library/Application Support/RGSX`
- Logs : `~/Library/Application Support/RGSX/logs/` (`bootstrap.log` pour l'installation, `RGSX.log` pour l'application)
- Runtime (Python, bibliothèques, 7-Zip) : `~/Library/Application Support/RGSX/runtime`
- ROMs : le dossier qui contient `ports` (`<ROMs>/ports/RGSX/RGSX.sh` donne `<ROMs>`), donc les téléchargements arrivent là où ES-DE cherche. Si RGSX n'est pas dans un dossier `ports`, repli sur `~/ROMs` s'il existe, sinon `~/Documents/RGSX/roms`.
- Personnalisation, par priorité décroissante : le paramètre `roms_folder` de `rgsx_settings.json`, la variable `RGSX_ROMS_DIR`, le dossier dérivé de l'emplacement de RGSX, puis les valeurs par défaut ci-dessus.

### Mise à jour

Remplacez le dossier `ports` par le nouveau (supprimez d'abord l'ancien `ports/RGSX` au lieu de fusionner). Les paramètres et le runtime sont hors de ce dossier et sont conservés.

La mise à jour intégrée sur macOS **prévient seulement** : quand le fork publie une version plus récente, un message renvoie vers la [page des releases du fork](https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS/releases). Elle ne télécharge ni n'installe rien, et ne touche jamais `~/Library/Application Support/RGSX` (vos paramètres et le runtime). Téléchargez `RGSX_macos_arm64.zip` depuis la page des releases et remplacez le dossier `ports` comme ci-dessus. Le paquet de mise à jour d'upstream n'est pas prévu pour macOS et n'est jamais installé par ce fork.

Ce fork est synchronisé avec RGSX upstream v2.7.0.7 (la version affichée dans l'app). Au premier lancement après la mise à jour, RGSX construit sa base locale du catalogue de jeux (`rgsx.sqlite3` dans `~/Library/Application Support/RGSX`), ce qui peut prendre un moment.

### Noms de dossiers ES-DE

RGSX utilise les noms de dossiers Batocera/RetroBat, ES-DE les siens. Sur macOS RGSX les traduit pour que les jeux arrivent dans les dossiers scannés par ES-DE :

| RGSX | ES-DE | RGSX | ES-DE |
|---|---|---|---|
| `3ds` | `n3ds` | `lynx` | `atarilynx` |
| `amiga500` | `amiga` | `MSX2+ (Archive)` | `msx2` |
| `amigacdtv` | `cdtv` | `o2em` | `odyssey2` |
| `c20` | `vic20` | `sg1000` | `sg-1000` |
| `cplus4` | `plus4` | `wswan` | `wonderswan` |
| `cdi` | `cdimono1` | `wswanc` | `wonderswancolor` |
| `gamecube` | `gc` | `jaguar` | `atarijaguar` |

- Les autres systèmes ont déjà le même nom.
- Les systèmes absents d'ES-DE (`advision`, `atom`, `chihiro`, `lindbergh`, `namco2x6`, `pico`, `teknoparrot`) gardent le nom RGSX et nécessitent un système ES-DE personnalisé pour apparaître.
- Dans `rgsx_settings.json`, `"esde_folder_mapping": false` désactive la traduction. `"rom_folder_map": {"gamecube": "gc", "pico": "segapico"}` ajoute ou remplace des entrées (une valeur identique à la clé désactive cette entrée par défaut).
- Les jeux déjà téléchargés sous un ancien nom RGSX (par exemple `gamecube`) ne sont plus détectés après ce changement. Déplacez-les vous-même vers le dossier ES-DE ; rien n'est déplacé automatiquement.

### Prérequis

- Mac Apple Silicon (M1 ou plus récent). Les Mac Intel ne sont pas supportés : le lanceur s'arrête avec un message.
- ES-DE pour macOS.
- Internet au premier lancement (environ 60 Mo). Les lancements suivants fonctionnent hors ligne, hors téléchargement de jeux.
- Les sources torrent nécessitent macOS 14 (Sonoma) ou plus récent. Sur macOS 11 à 13 le reste fonctionne et les torrents sont désactivés avec un message clair.

---

## 🎮 Utilisation

### Premier lancement

- Télécharge automatiquement les images des systèmes et les listes de jeux
- Tous les systèmes sont listés, car il n'y a pas ici de configuration EmulationStation pour définir ceux supportés
- Mode fenêtré par défaut (modifiable dans Paramètres > Mode d'affichage)

### Contrôles

**Clavier** (sans manette détectée, les contrôles s'affichent sous la forme `[Touche]` au lieu d'icônes) :

| Action | Touche |
|---|---|
| Valider / Annuler | `Entrée` / `Échap` |
| Naviguer | Flèches |
| Start (menu pause) | `P` |
| Filtre | `F` |
| Historique | `H` |
| Vider l'historique | `X` |
| Page précédente / suivante | `Fn+↑` / `Fn+↓` |
| Supprimer | `Retour arrière` |
| Espace | `Espace` |

Les manettes sont mappées automatiquement si elles sont reconnues, et vous pouvez les reconfigurer depuis le menu pause. **Contrôles cassés ?** Supprimez `~/Library/Application Support/RGSX/controls.json` et relancez.

### Structure du menu pause

**Catégories principales**
- Jeux (téléchargements, scans, visibilité des plateformes)
- Langue (changer la langue de l'interface)
- Contrôles (aide et remappage)
- Affichage (disposition, polices, moniteur/mode, options visuelles)
- Paramètres (musique, symlink, extraction auto, état réseau et API)
- Support (générer un ZIP/log de support)
- Quitter (quitter ou redémarrer)

**Contrôles**
- Afficher l'aide des contrôles (actions actuellement mappées)
- Remapper les contrôles (reconfigurer clavier/manette)

**Affichage**
- Disposition (3×3 jusqu'à 8×6)
- Sous-menu taille de police (interface générale + pied de page)
- Famille de police (Pixel ou DejaVu)
- Sélection du moniteur (si plusieurs sont détectés)
- Mode léger (rendu économe en performances)
- Masquer l'avertissement d'extension inconnue

**Jeux**
- Mettre à jour le cache des jeux (retélécharger systèmes/jeux)
- Scanner les ROMs possédées (ajouter les ROMs locales à l'historique)
- Historique des téléchargements (voir/gérer les entrées)
- Afficher les plateformes non supportées (plateformes sans dossier ROM local)
- Filtrer les plateformes (visibilité source/plateforme)

**Paramètres**
- Musique de fond (activer/désactiver)
- Options symlink (copie ou lien symbolique)
- Extraction automatique (extraction auto des archives)
- Sélecteur de dossier ROMs (dossier racine personnalisé)
- État des clés API (présence des clés des fournisseurs)
- État de la connexion (tester les sites requis)

---

## ✨ Fonctionnalités

- 📦 **Gestion intelligente des archives** – Extraction automatique quand un système ne supporte pas les ZIP (RAR via le 7-Zip intégré)
- 🔑 **Déblocage premium** – API 1Fichier + AllDebrid/Debrid-Link/Real-Debrid/TorBox en secours pour des téléchargements illimités
- 🎨 **Entièrement personnalisable** – Disposition (3×3 jusqu'à 8×6), polices, tailles (interface + pied de page), langues (EN/FR/DE/ES/IT/PT/TR)
- 🎮 **Pensé pour la manette** – Mapping automatique des manettes courantes + remappage personnalisé
- 🧲 **Sources torrent** – libtorrent intégré, aucune application supplémentaire
- 🔍 **Filtrage avancé** – Recherche par nom, affichage/masquage des systèmes non supportés, filtre de plateformes
- 📊 **Gestion des téléchargements** – File d'attente, historique, notifications de progression
- ♿ **Accessibilité** – Taille de police séparée pour l'interface et le pied de page, mode 100 % clavier

> ### 🔑 Configuration des clés API
> Pour des téléchargements 1Fichier illimités, ajoutez vos clés API dans `~/Library/Application Support/RGSX/` :
> - `1FichierAPI.txt` – clé API 1Fichier (recommandée)
> - `AllDebridAPI.txt` – secours AllDebrid (optionnel)
> - `DebridLinkAPI.txt` – secours Debrid-Link (optionnel)
> - `RealDebridAPI.txt` – secours Real-Debrid (optionnel)
> - `TorBoxAPI.txt` – secours TorBox (optionnel)
>
> **Chaque fichier doit contenir UNIQUEMENT la clé, sans texte supplémentaire.**

### Télécharger des jeux

1. Parcourez les plateformes → Sélectionnez un jeu
2. **Téléchargement direct** : appuyez sur `Valider`
3. **Ajout à la file** : appuyez sur `X` (bouton Ouest)
4. Suivez la progression dans le menu **Historique** ou via les notifications

### Torrents

Les sources torrent passent par libtorrent, installé automatiquement sur macOS 14 ou plus récent.

- Le partage (seed) n'a lieu que pendant que RGSX est ouvert.
- Au premier torrent, le pare-feu macOS peut demander d'autoriser les connexions entrantes. Refuser permet quand même de télécharger.
- Pour ne jamais avoir cette demande, définissez `RGSX_TORRENT_LISTEN=off` : RGSX écoute alors uniquement en local et désactive DHT, LSD et UPnP.
- Lors d'un partage entre volumes, une seconde copie du fichier est conservée jusqu'à la fermeture de RGSX.

---

## 🌐 Interface Web

RGSX démarre une petite interface web pour parcourir et télécharger depuis un navigateur.

- Locale par défaut : `http://localhost:5000`, ou le port libre suivant jusqu'à 5010 si le port choisi est occupé. Le récepteur AirPlay de macOS utilise le port 5000 et RGSX ne l'arrête jamais : vous aurez souvent `5001`. Choisissez un autre port dans les Paramètres, ou désactivez le récepteur AirPlay (Réglages Système > Général > AirDrop et Handoff).
- Le port réellement utilisé est affiché dans les Paramètres, journalisé et écrit dans `~/Library/Application Support/RGSX/web_port.txt`.
- Quitter RGSX arrête aussi l'interface web, même après un plantage ou un `kill` ; un serveur resté d'une session précédente est arrêté au démarrage suivant.
- `RGSX_OPEN_WEB=1` ouvre l'interface dans le navigateur au lancement.

Modifiable depuis l'application : menu pause, puis Paramètres.
- **Accès à l'interface web** : « Ce Mac uniquement » ou « Réseau local ». L'activation de l'accès réseau demande une confirmation (il n'y a pas de mot de passe).
- **Port de l'interface web** : gauche/droite change le port de 1, les gâchettes (PageUp/PageDown au clavier) de 100, entre 1024 et 65535. Validez pour appliquer ; le serveur web redémarre aussitôt.
- La ligne sélectionnée affiche l'adresse actuelle (`http://localhost:<port>` et, si l'accès réseau est activé, `http://<IP locale de votre Mac>:<port>`).

Alternative manuelle : modifiez `~/Library/Application Support/RGSX/rgsx_settings.json` avec `"web_host": "0.0.0.0"` (par défaut `"127.0.0.1"`, ce Mac uniquement) et `"web_port": 5000` (par défaut 5000 ; une valeur invalide revient à 5000), puis relancez RGSX. Les variables d'environnement `RGSX_WEB_HOST` et `RGSX_WEB_PORT` sont prioritaires sur ces réglages (les Paramètres affichent alors « défini par ... »). ES-DE ne peut pas définir de variables d'environnement : utilisez le menu Paramètres.

Avec l'accès réseau activé, ouvrez `http://<IP locale de votre Mac>:<port>` depuis un téléphone ou un autre ordinateur. macOS peut demander d'autoriser les connexions entrantes : autorisez.

**Attention :** il n'y a aucune connexion/authentification. Toute personne du même réseau peut utiliser l'interface : n'activez l'accès réseau que sur un réseau de confiance. RGSX journalise un WARNING quand elle est exposée.

---

## 🛠 Dépannage

| Problème | Solution |
|-------|----------|
| Rien ne se passe / macOS bloque les fichiers | Exécutez `xattr -dr com.apple.quarantine <dossier ports>` dans le Terminal (le lanceur essaie aussi de le faire), puis relancez. |
| Le premier lancement semble bloqué | Le premier lancement télécharge environ 60 Mo. Patientez quelques minutes, Mac connecté. Consultez `~/Library/Application Support/RGSX/logs/bootstrap.log`. |
| Erreur d'installation citant un hôte | Le message nomme l'hôte injoignable (github.com pour Python, www.7-zip.org pour 7-Zip, pypi.org / files.pythonhosted.org pour les bibliothèques). Vérifiez connexion, VPN ou pare-feu et relancez. |
| Boîte « RGSX is incomplete » | Recopiez tout le dossier `ports` (remplacez l'ancien, ne fusionnez pas). |
| Deux entrées RGSX dans ES-DE | Une ancienne installation est restée dans `<ROMs>/ports`. Supprimez l'ancien dossier `RGSX` et les anciens scripts de lancement, puis copiez le nouveau dossier `ports`. |
| Les téléchargements vont dans `ROMs/ports/<système>` | Vous avez copié `ports` dans `ports`. Le dossier doit être `<ROMs>/ports/RGSX`. Déplacez-le, ou définissez `roms_folder` dans `rgsx_settings.json`. |
| Interface web pas sur le port 5000 | AirPlay occupe 5000. RGSX prend le port libre suivant (souvent 5001), ou choisissez un autre port dans les Paramètres. Voir `~/Library/Application Support/RGSX/web_port.txt`. |
| Demande du pare-feu au premier torrent | Refuser permet quand même de télécharger. Définissez `RGSX_TORRENT_LISTEN=off` pour ne plus l'avoir. |
| Torrents désactivés | Ils nécessitent macOS 14 ou plus récent. |
| 7-Zip manquant | Relancez RGSX avec internet, il se répare seul. Voir `logs/bootstrap.log`. |
| Python ou 7zz ne démarre pas | Exécutez `xattr -dr com.apple.quarantine ~/Library/Application\ Support/RGSX/runtime` puis relancez. |
| Réinitialiser le runtime | Supprimez `~/Library/Application Support/RGSX/runtime` ; le prochain lancement le retélécharge. |
| Contrôles qui ne fonctionnent pas | Supprimez `~/Library/Application Support/RGSX/controls.json` et relancez l'application. |
| Pas de jeux ? | Menu pause > Jeux > Mettre à jour le cache, puis vérifiez Filtrer les plateformes et Afficher les plateformes non supportées. La liste des jeux vient du service de catalogue RGSX, une connexion internet est donc nécessaire la première fois. |
| L'application plante | Consultez `~/Library/Application Support/RGSX/logs/RGSX.log`. |
| Changement de disposition non appliqué | Relancez RGSX après avoir changé la disposition. |
| Problème de téléchargement de certains jeux | Menu pause > Paramètres > État de la connexion. Si des sites requis sont en rouge, vérifiez réseau, VPN, DNS et protections du routeur. |

---

## ⚠️ Limitations

- Apple Silicon uniquement. Les Mac Intel ne sont pas supportés.
- Les conversions PS3 et Xbox (`ps3dec`, `xdvdfs`, `extract-xiso`) ne sont pas supportées ; ces téléchargements restent des archives.
- Les fonctions réservées à Batocera (services au démarrage, DNS personnalisé) sont masquées.
- Non vérifié sur du matériel réel par l'auteur du fork : un blocage Gatekeeper sur un second Mac, et les manettes sur macOS (le clavier est testé).

---

## 🤝 Contribution

- **Bugs / demandes pour ce fork macOS** : ouvrez une [issue](https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS/issues) avec les logs de `~/Library/Application Support/RGSX/logs/`.
- Les sujets Batocera, Knulli, RetroBat ou le cœur de l'application relèvent du [projet d'origine](https://github.com/RetroGameSets/RGSX) (Discord du projet d'origine : [discord.gg/Vph9jwg3VV](https://discord.gg/Vph9jwg3VV)).

---

## 📝 Licence et crédits

RGSX est créé par [RetroGameSets](https://github.com/RetroGameSets/RGSX). Le projet d'origine le décrit comme un logiciel libre et open source, utilisable, modifiable et distribuable librement ; ce fork suit les mêmes conditions. Aucun fichier LICENSE séparé n'est présent dans ce dépôt.

Merci à tous les [contributeurs du projet d'origine](https://github.com/RetroGameSets/RGSX/graphs/contributors) et aux suiveurs de l'application.

**Développé avec ❤️ pour la communauté du retrogaming.**
