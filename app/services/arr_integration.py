"""Service d'intégration avec Radarr et Sonarr."""
import re
from typing import Optional
from pathlib import Path

import httpx

from app.services.config_manager import config_manager


def normalize_url(url: str) -> str:
    """Normalise une URL en enlevant le slash final."""
    if url:
        return url.rstrip('/')
    return url


class RadarrService:
    """Service pour communiquer avec Radarr."""
    
    def __init__(self):
        pass
    
    @property
    def url(self) -> str:
        return normalize_url(config_manager.load().radarr_url)
    
    @property
    def api_key(self) -> str:
        return config_manager.load().radarr_api_key
    
    @property
    def enabled(self) -> bool:
        return bool(self.url and self.api_key)
    
    def _get_headers(self) -> dict:
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
    
    async def test_connection(self) -> tuple[bool, str]:
        """Teste la connexion à Radarr."""
        if not self.enabled:
            return False, "Radarr non configuré"
        
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.url}/api/v3/system/status",
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    data = response.json()
                    return True, f"Connecté à Radarr v{data.get('version', '?')}"
                return False, f"Erreur {response.status_code}"
        except Exception as e:
            return False, str(e)
    
    async def get_naming_config(self) -> Optional[dict]:
        """Récupère la configuration de nommage de Radarr."""
        if not self.enabled:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.url}/api/v3/config/naming",
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    return response.json()
        except Exception:
            pass
        return None
    
    async def lookup_movie(self, tmdb_id: int) -> Optional[dict]:
        """Recherche un film par TMDB ID."""
        if not self.enabled:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.url}/api/v3/movie/lookup/tmdb",
                    params={"tmdbId": tmdb_id},
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    return response.json()
        except Exception:
            pass
        return None
    
    def format_movie_folder(self, title: str, year: Optional[int], tmdb_id: int = None) -> str:
        """Formate le nom du dossier film selon le format Plex standard.
        
        Format Plex: Titre (Année)
        """
        clean_title = self._clean_title(title)
        if year:
            return f"{clean_title} ({year})"
        return clean_title
    
    def format_movie_file(self, title: str, year: Optional[int], quality: str = "", extension: str = "") -> str:
        """Formate le nom du fichier film selon le format Plex standard.
        
        Format Plex: Titre (Année).ext
        """
        clean_title = self._clean_title(title)
        if year:
            filename = f"{clean_title} ({year})"
        else:
            filename = clean_title
        
        if extension:
            return f"{filename}{extension}"
        return filename
    
    def _clean_title(self, title: str) -> str:
        """Nettoie un titre pour le système de fichiers."""
        # Supprimer les caractères interdits
        invalid = '<>:"/\\|?*'
        for char in invalid:
            title = title.replace(char, '')
        return title.strip()


class SonarrService:
    """Service pour communiquer avec Sonarr."""
    
    def __init__(self):
        pass
    
    @property
    def url(self) -> str:
        return normalize_url(config_manager.load().sonarr_url)
    
    @property
    def api_key(self) -> str:
        return config_manager.load().sonarr_api_key
    
    @property
    def enabled(self) -> bool:
        return bool(self.url and self.api_key)
    
    def _get_headers(self) -> dict:
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
    
    async def test_connection(self) -> tuple[bool, str]:
        """Teste la connexion à Sonarr."""
        if not self.enabled:
            return False, "Sonarr non configuré"
        
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.url}/api/v3/system/status",
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    data = response.json()
                    return True, f"Connecté à Sonarr v{data.get('version', '?')}"
                return False, f"Erreur {response.status_code}"
        except Exception as e:
            return False, str(e)
    
    async def get_naming_config(self) -> Optional[dict]:
        """Récupère la configuration de nommage de Sonarr."""
        if not self.enabled:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.url}/api/v3/config/naming",
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    return response.json()
        except Exception:
            pass
        return None
    
    async def lookup_series(self, tmdb_id: int) -> Optional[dict]:
        """Recherche une série par TMDB ID."""
        if not self.enabled:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                # Sonarr utilise TVDB, on doit chercher par terme
                response = await client.get(
                    f"{self.url}/api/v3/series/lookup",
                    params={"term": f"tmdb:{tmdb_id}"},
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    results = response.json()
                    if results:
                        return results[0]
        except Exception:
            pass
        return None
    
    def format_series_folder(self, title: str, year: Optional[int], tmdb_id: int = None) -> str:
        """Formate le nom du dossier série selon le format Plex standard.
        
        Format Plex: Titre (Année)
        """
        clean_title = self._clean_title(title)
        if year:
            return f"{clean_title} ({year})"
        return clean_title
    
    def format_episode_file(
        self,
        series_title: str,
        season: int,
        episode: int,
        episode_title: str = "",
        quality: str = "",
        extension: str = ""
    ) -> str:
        """Formate le nom du fichier épisode selon le format Plex standard.
        
        Format Plex: Série - SXXEXX - Titre Episode.ext
        ou simplement: Série - SXXEXX.ext
        """
        clean_title = self._clean_title(series_title)
        filename = f"{clean_title} - S{season:02d}E{episode:02d}"
        
        if episode_title:
            clean_episode_title = self._clean_title(episode_title)
            filename = f"{filename} - {clean_episode_title}"
        
        if extension:
            return f"{filename}{extension}"
        return filename
    
    def format_season_folder(self, season: int) -> str:
        """Formate le nom du dossier saison selon le format Plex standard."""
        if season == 0:
            return "Specials"
        return f"Season {season:02d}"
    
    def _clean_title(self, title: str) -> str:
        """Nettoie un titre pour le système de fichiers."""
        invalid = '<>:"/\\|?*'
        for char in invalid:
            title = title.replace(char, '')
        return title.strip()


# Instances globales
radarr_service = RadarrService()
sonarr_service = SonarrService()
