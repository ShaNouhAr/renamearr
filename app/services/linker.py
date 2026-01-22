"""Service de création de hardlinks et organisation des fichiers."""
import os
import re
from pathlib import Path
from typing import Optional
from datetime import datetime

from app.models import MediaType
from app.services.config_manager import config_manager
from app.services.arr_integration import radarr_service, sonarr_service


def sanitize_filename(name: str) -> str:
    """Nettoie un nom de fichier pour le rendre valide."""
    # Caractères interdits sur Windows et Linux
    invalid_chars = r'<>:"/\\|?*'
    
    # Remplacer les caractères interdits
    for char in invalid_chars:
        name = name.replace(char, '')
    
    # Supprimer les espaces en début/fin et les points en fin
    name = name.strip().rstrip('.')
    
    # Limiter la longueur
    if len(name) > 200:
        name = name[:200]
    
    return name


class FileLinker:
    """Service pour créer des hardlinks et organiser les fichiers."""
    
    def __init__(self):
        pass
    
    @property
    def movies_path(self) -> Path:
        return config_manager.get_movies_path()
    
    @property
    def tv_path(self) -> Path:
        return config_manager.get_tv_path()
    
    def _ensure_dir(self, path: Path) -> None:
        """S'assure qu'un dossier existe."""
        path.mkdir(parents=True, exist_ok=True)
    
    def build_movie_path(
        self,
        title: str,
        year: Optional[int],
        tmdb_id: int,
        source_path: Path
    ) -> Path:
        """Construit le chemin de destination pour un film.
        
        Format Plex: /movies/Titre (Année)/Titre (Année).ext
        """
        extension = source_path.suffix
        
        folder_name = radarr_service.format_movie_folder(title, year)
        file_name = radarr_service.format_movie_file(title, year, extension=extension)
        
        return self.movies_path / sanitize_filename(folder_name) / sanitize_filename(file_name)
    
    def build_tv_path(
        self,
        title: str,
        year: Optional[int],
        tmdb_id: int,
        season: int,
        episode: int,
        source_path: Path
    ) -> Path:
        """Construit le chemin de destination pour un épisode de série.
        
        Format Plex: /tv/Titre (Année)/Season XX/Titre - SXXEXX.ext
        """
        extension = source_path.suffix
        
        series_folder = sonarr_service.format_series_folder(title, year)
        season_folder = sonarr_service.format_season_folder(season)
        file_name = sonarr_service.format_episode_file(title, season, episode, extension=extension)
        
        return self.tv_path / sanitize_filename(series_folder) / season_folder / sanitize_filename(file_name)
    
    def create_hardlink(self, source: Path, destination: Path) -> tuple[bool, str]:
        """Crée un hardlink du fichier source vers la destination.
        
        Returns:
            Tuple (success, message)
        """
        try:
            # Vérifier que la source existe
            if not source.exists():
                return False, f"Fichier source introuvable: {source}"
            
            # Créer le dossier de destination
            self._ensure_dir(destination.parent)
            
            # Supprimer le fichier de destination s'il existe déjà
            if destination.exists():
                destination.unlink()
            
            # Créer le hardlink
            os.link(source, destination)
            
            return True, f"Hardlink créé: {destination}"
            
        except OSError as e:
            # Si hardlink impossible (cross-device), essayer symlink
            if e.errno == 18:  # EXDEV - Invalid cross-device link
                try:
                    if destination.exists():
                        destination.unlink()
                    destination.symlink_to(source)
                    return True, f"Symlink créé (cross-device): {destination}"
                except Exception as se:
                    return False, f"Erreur symlink: {se}"
            return False, f"Erreur hardlink: {e}"
        except Exception as e:
            return False, f"Erreur inattendue: {e}"
    
    def link_movie(
        self,
        source_path: Path,
        title: str,
        year: Optional[int],
        tmdb_id: int
    ) -> tuple[bool, str, Optional[Path]]:
        """Crée un hardlink pour un film.
        
        Returns:
            Tuple (success, message, destination_path)
        """
        destination = self.build_movie_path(title, year, tmdb_id, source_path)
        success, message = self.create_hardlink(source_path, destination)
        return success, message, destination if success else None
    
    def link_tv_episode(
        self,
        source_path: Path,
        title: str,
        year: Optional[int],
        tmdb_id: int,
        season: int,
        episode: int
    ) -> tuple[bool, str, Optional[Path]]:
        """Crée un hardlink pour un épisode de série.
        
        Returns:
            Tuple (success, message, destination_path)
        """
        destination = self.build_tv_path(title, year, tmdb_id, season, episode, source_path)
        success, message = self.create_hardlink(source_path, destination)
        return success, message, destination if success else None
    
    def remove_link(self, destination_path: Path) -> tuple[bool, str]:
        """Supprime un lien (hardlink ou symlink).
        
        Returns:
            Tuple (success, message)
        """
        try:
            if destination_path.exists() or destination_path.is_symlink():
                destination_path.unlink()
                
                # Nettoyer les dossiers vides
                self._cleanup_empty_dirs(destination_path.parent)
                
                return True, f"Lien supprimé: {destination_path}"
            return False, f"Fichier introuvable: {destination_path}"
        except Exception as e:
            return False, f"Erreur suppression: {e}"
    
    def _cleanup_empty_dirs(self, path: Path) -> None:
        """Supprime les dossiers vides en remontant."""
        try:
            # Ne pas supprimer les dossiers racine
            if path in [self.movies_path, self.tv_path]:
                return
            
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
                self._cleanup_empty_dirs(path.parent)
        except Exception:
            pass


# Instance globale
file_linker = FileLinker()
