"""Service de gestion de la configuration dynamique."""
import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


CONFIG_FILE = Path("./data/config.json")


class AppConfig(BaseModel):
    """Configuration de l'application."""
    # Mode: "unified" = 1 dossier source, "separate" = 2 dossiers sources
    source_mode: str = Field(default="unified", description="Mode source: unified ou separate")
    
    # Dossier source unique (mode unified)
    source_path: str = Field(default="/mnt/alldebrid/torrents", description="Dossier source des torrents (mode unifié)")
    
    # Dossiers sources séparés (mode separate)
    source_movies_path: str = Field(default="/mnt/alldebrid/movies", description="Dossier source des films")
    source_tv_path: str = Field(default="/mnt/alldebrid/tv", description="Dossier source des séries")
    
    # Dossiers destination
    movies_path: str = Field(default="/mnt/media/movies", description="Dossier destination des films")
    tv_path: str = Field(default="/mnt/media/tv", description="Dossier destination des séries")
    
    # Radarr
    radarr_url: str = Field(default="", description="URL de Radarr (ex: http://localhost:7878)")
    radarr_api_key: str = Field(default="", description="Clé API Radarr")
    
    # Sonarr
    sonarr_url: str = Field(default="", description="URL de Sonarr (ex: http://localhost:8989)")
    sonarr_api_key: str = Field(default="", description="Clé API Sonarr")
    
    # Obligatoire ?
    require_arr: bool = Field(default=False, description="Exiger Radarr/Sonarr pour scanner")
    
    # Auto-scan
    auto_scan_enabled: bool = Field(default=False, description="Activer le scan automatique")
    auto_scan_interval: int = Field(default=30, description="Intervalle de scan")
    auto_scan_unit: str = Field(default="minutes", description="Unité de l'intervalle: seconds ou minutes")
    
    # Options
    tmdb_language: str = Field(default="fr-FR", description="Langue TMDB")
    min_video_size_mb: int = Field(default=50, description="Taille minimum des vidéos en MB")
    video_extensions: list[str] = Field(
        default=[".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".webm"],
        description="Extensions vidéo supportées"
    )


class ConfigManager:
    """Gestionnaire de configuration persistante."""
    
    def __init__(self):
        self._config: Optional[AppConfig] = None
        self._ensure_data_dir()
    
    def _ensure_data_dir(self):
        """S'assure que le dossier data existe."""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    def load(self) -> AppConfig:
        """Charge la configuration depuis le fichier."""
        if self._config is not None:
            return self._config
        
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = AppConfig(**data)
            except Exception:
                self._config = AppConfig()
        else:
            self._config = AppConfig()
            self.save(self._config)
        
        return self._config
    
    def save(self, config: AppConfig) -> None:
        """Sauvegarde la configuration."""
        self._ensure_data_dir()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
        self._config = config
    
    def update(self, **kwargs) -> AppConfig:
        """Met à jour la configuration avec les valeurs fournies."""
        current = self.load()
        updated_data = current.model_dump()
        updated_data.update({k: v for k, v in kwargs.items() if v is not None})
        new_config = AppConfig(**updated_data)
        self.save(new_config)
        return new_config
    
    def get_source_mode(self) -> str:
        """Retourne le mode source."""
        return self.load().source_mode
    
    def get_source_path(self) -> Path:
        """Retourne le chemin source unique (mode unified)."""
        return Path(self.load().source_path)
    
    def get_source_movies_path(self) -> Path:
        """Retourne le chemin source des films (mode separate)."""
        return Path(self.load().source_movies_path)
    
    def get_source_tv_path(self) -> Path:
        """Retourne le chemin source des séries (mode separate)."""
        return Path(self.load().source_tv_path)
    
    def get_movies_path(self) -> Path:
        """Retourne le chemin des films."""
        return Path(self.load().movies_path)
    
    def get_tv_path(self) -> Path:
        """Retourne le chemin des séries."""
        return Path(self.load().tv_path)
    
    def get_video_extensions(self) -> set[str]:
        """Retourne les extensions vidéo."""
        return set(self.load().video_extensions)
    
    def get_min_video_size(self) -> int:
        """Retourne la taille minimum en bytes."""
        return self.load().min_video_size_mb * 1024 * 1024


# Instance globale
config_manager = ConfigManager()
