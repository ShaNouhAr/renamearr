# 🎬 Renamearr

**Organisateur de fichiers médias pour les setups Plex avec debrideurs (AllDebrid, RealDebrid, etc.)**

> ⚠️ **Note importante** : Je ne suis pas développeur. Ce projet a été entièrement créé avec l'aide de l'IA (Claude). Si vous êtes développeur et souhaitez reprendre, améliorer ou forker ce projet, vous êtes les bienvenus ! 🙏

---

## 🎯 Le problème que Renamearr résout

Si vous utilisez un setup Plex avec un service de debrid (AllDebrid, RealDebrid, Premiumize, etc.) monté via **rclone**, vous connaissez le problème :

```
📁 /mnt/alldebrid/torrents/
├── Movie.2024.1080p.WEB-DL.x264-GROUP.mkv
├── Some.Random.Show.S01E05.720p.HDTV.mkv
├── [YTS.MX] Another Movie (2023) 4K.mp4
├── Film.Français.2024.FRENCH.1080p.mkv
└── ... (le bordel total)
```

**Radarr et Sonarr ne peuvent pas gérer ces fichiers** car ils sont en lecture seule sur le cloud et ne peuvent pas être renommés/déplacés.

### La solution Renamearr :

```
📁 /mnt/alldebrid/torrents/ (source - bordel)
        ↓ hardlink ↓
📁 /mnt/media/ (destination - organisé)
├── Films/
│   ├── Inception (2010)/
│   │   └── Inception (2010).mkv
│   └── The Matrix (1999)/
│       └── The Matrix (1999).mkv
└── Séries/
    └── Breaking Bad (2008)/
        └── Season 01/
            └── Breaking Bad - S01E01.mkv
```

Renamearr :
1. **Scanne** vos dossiers torrents
2. **Identifie** les films/séries via TMDB
3. **Crée des hardlinks** vers une structure propre compatible Plex
4. **Gère les cas manuels** via une WebUI intuitive

---

## ✨ Fonctionnalités

- 🔍 **Scan automatique** des dossiers sources
- 🎬 **Identification TMDB** automatique des films et séries
- 🔗 **Hardlinks** (pas de duplication d'espace disque)
- 📊 **Interface web** moderne et temps réel (SSE)
- 🔧 **Gestion manuelle** des fichiers non reconnus
- 📁 **Explorateur de fichiers** intégré
- 🔐 **Authentification** avec gestion des utilisateurs
- 🔌 **Intégration Radarr/Sonarr** pour le format de nommage
- 🐳 **Docker ready**

---

## 🚀 Installation

### Prérequis

- Docker et Docker Compose
- Un montage rclone de votre debrideur
- Une clé API TMDB (gratuite sur [themoviedb.org](https://www.themoviedb.org/settings/api))

### Démarrage rapide

1. **Cloner le repo**
```bash
git clone https://github.com/votre-username/renamearr.git
cd renamearr
```

2. **Configurer l'environnement**
```bash
cp config.example.env .env
# Éditer .env avec votre clé TMDB
```

3. **Lancer avec Docker**
```bash
docker compose up -d
```

4. **Accéder à l'interface**
```
http://localhost:8080
```

5. **Connexion par défaut**
```
Utilisateur: root
Mot de passe: root
```
⚠️ **Changez le mot de passe immédiatement !**

---

## ⚙️ Configuration

### docker-compose.yml

```yaml
services:
  renamearr:
    build: .
    container_name: renamearr
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data          # Base de données
      - /mnt:/mnt                  # Accès aux montages rclone
    environment:
      - TMDB_API_KEY=votre_clé_ici
    restart: unless-stopped
```

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `TMDB_API_KEY` | Clé API TMDB | - |
| `HOST` | Adresse d'écoute | 0.0.0.0 |
| `PORT` | Port | 8080 |

### Configuration dans l'interface

Une fois connecté, allez dans **Configuration** pour définir :
- 📁 Dossiers sources (torrents)
- 📁 Dossiers de destination (Films/Séries)
- 🔌 URLs et clés API Radarr/Sonarr (optionnel)

---

## 📸 Screenshots

*À venir*

---

## 🏗️ Architecture technique

- **Backend** : FastAPI (Python)
- **Frontend** : HTML/CSS/JS vanilla
- **Base de données** : SQLite
- **Temps réel** : Server-Sent Events (SSE)
- **Authentification** : JWT + bcrypt

---

## 🤝 Contribution

### Ce projet a besoin de vous !

Comme mentionné, je ne suis pas développeur. Ce projet fonctionne pour mon usage mais pourrait être grandement amélioré par quelqu'un de compétent.

**Améliorations possibles :**
- [ ] Meilleure gestion des erreurs
- [ ] Tests unitaires
- [ ] Support multi-utilisateurs avec rôles
- [ ] Scan automatique (watch mode)
- [ ] Notifications (Discord, Telegram, etc.)
- [ ] Support d'autres sources de métadonnées
- [ ] Interface mobile responsive
- [ ] Documentation API
- [ ] Internationalisation

**Pour contribuer :**
1. Fork le projet
2. Créez une branche (`git checkout -b feature/amelioration`)
3. Committez (`git commit -m 'Ajout de fonctionnalité'`)
4. Push (`git push origin feature/amelioration`)
5. Ouvrez une Pull Request

---

## 📋 Contexte & Motivation

### Pourquoi ce projet ?

Les services de debrid (AllDebrid, RealDebrid, Debrid-Link, Premiumize...) permettent de télécharger des torrents côté serveur et de les streamer via rclone. C'est une solution populaire pour :
- Éviter les problèmes de ratio
- Téléchargement instantané (si déjà en cache)
- Accès depuis n'importe où

**Le problème** : Les fichiers sont nommés n'importe comment et Plex/Radarr/Sonarr ont du mal à les identifier.

**La solution classique** : FileBot, mais c'est payant et ne gère pas bien le cas spécifique des fichiers en lecture seule sur rclone.

**Renamearr** comble ce vide en créant des hardlinks (quand possible) ou symlinks vers une structure propre.

---

## 📜 Licence

MIT - Faites-en ce que vous voulez !

---

## 🙏 Remerciements

- [TMDB](https://www.themoviedb.org/) pour l'API de métadonnées
- L'écosystème **-arr** (Radarr, Sonarr, Prowlarr...) pour l'inspiration
- La communauté des auto-hébergeurs
- Claude (Anthropic) pour l'aide au développement

---

**⭐ Si ce projet vous aide, une étoile sur GitHub fait toujours plaisir !**
