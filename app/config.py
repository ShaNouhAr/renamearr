"""Configuration du projet."""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Configuration de l'application."""
    
    # TMDB
    tmdb_api_key: str = Field(default="", description="Clé API TMDB")
    tmdb_language: str = Field(default="fr-FR", description="Langue pour TMDB")
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    
    # Chemins
    source_path: Path = Field(default=Path("/mnt/alldebrid/torrents"), description="Dossier source rclone")
    movies_path: Path = Field(default=Path("/mnt/media/movies"), description="Dossier destination films")
    tv_path: Path = Field(default=Path("/mnt/media/tv"), description="Dossier destination séries")
    
    # Serveur
    host: str = "0.0.0.0"
    port: int = 8080
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./data/media_manager.db"
    
    # Extensions vidéo supportées
    video_extensions: set[str] = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".webm"}
    
    # Taille minimum des fichiers vidéo (en bytes) - 50 MB
    min_video_size: int = 50 * 1024 * 1024
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
