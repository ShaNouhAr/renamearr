"""Service d'intégration avec l'API TVDB pour les séries TV."""
import asyncio
from typing import Optional
from datetime import datetime, timedelta

import httpx

from app.config import settings
from app.models import MediaType


class TVDBSearchResult:
    """Résultat de recherche TVDB."""
    def __init__(
        self,
        id: int,
        title: str,
        original_title: Optional[str] = None,
        year: Optional[int] = None,
        overview: Optional[str] = None,
        poster_path: Optional[str] = None,
        popularity: float = 0.0
    ):
        self.id = id
        self.title = title
        self.original_title = original_title
        self.year = year
        self.overview = overview
        self.poster_path = poster_path
        self.media_type = MediaType.TV
        self.popularity = popularity


class TVDBService:
    """Service pour interagir avec l'API TVDB v4."""
    
    def __init__(self):
        self.base_url = "https://api4.thetvdb.com/v4"
        self.image_base_url = "https://artworks.thetvdb.com"
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._token_lock = asyncio.Lock()
        self._cached_api_key: Optional[str] = None
    
    @property
    def api_key(self) -> str:
        """Retourne la clé API (config > env)."""
        from app.services.config_manager import config_manager
        config_key = config_manager.load().tvdb_api_key
        new_key = config_key if config_key else settings.tvdb_api_key
        # Invalider le token si la clé a changé
        if self._cached_api_key and self._cached_api_key != new_key:
            self._token = None
            self._token_expires = None
        self._cached_api_key = new_key
        return new_key
    
    @property
    def language(self) -> str:
        """Retourne la langue configurée (format TVDB: fra, eng, etc.)."""
        from app.services.config_manager import config_manager
        lang = config_manager.load().tvdb_language or settings.tvdb_language
        # Convertir format ISO (fr-FR) vers format TVDB (fra)
        lang_map = {
            "fr": "fra", "fr-FR": "fra", "fra": "fra",
            "en": "eng", "en-US": "eng", "en-GB": "eng", "eng": "eng",
            "de": "deu", "de-DE": "deu", "deu": "deu",
            "es": "spa", "es-ES": "spa", "spa": "spa",
            "it": "ita", "it-IT": "ita", "ita": "ita",
            "pt": "por", "pt-BR": "por", "por": "por",
            "ja": "jpn", "ja-JP": "jpn", "jpn": "jpn",
            "ko": "kor", "ko-KR": "kor", "kor": "kor",
            "zh": "zho", "zh-CN": "zho", "zho": "zho",
        }
        return lang_map.get(lang, "eng")
    
    async def _get_token(self) -> Optional[str]:
        """Obtient ou rafraîchit le token d'authentification TVDB."""
        async with self._token_lock:
            # Vérifier si le token est encore valide (avec marge de 5 minutes)
            if self._token and self._token_expires:
                if datetime.utcnow() < self._token_expires - timedelta(minutes=5):
                    return self._token
            
            if not self.api_key:
                return None
            
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        f"{self.base_url}/login",
                        json={"apikey": self.api_key},
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        self._token = data.get("data", {}).get("token")
                        # Token TVDB expire après 1 mois, on le rafraîchit toutes les 24h
                        self._token_expires = datetime.utcnow() + timedelta(hours=24)
                        return self._token
                    else:
                        print(f"TVDB login failed: {response.status_code} - {response.text}")
                        return None
            except Exception as e:
                print(f"TVDB login error: {e}")
                return None
    
    def _get_headers(self, token: str) -> dict:
        """Retourne les headers pour les requêtes API."""
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
    
    async def search_series(self, query: str, year: Optional[int] = None) -> list[TVDBSearchResult]:
        """Recherche une série sur TVDB."""
        token = await self._get_token()
        if not token:
            return []
        
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                params = {
                    "query": query,
                    "type": "series",
                }
                if year:
                    params["year"] = year
                
                response = await client.get(
                    f"{self.base_url}/search",
                    params=params,
                    headers=self._get_headers(token),
                )
                
                if response.status_code != 200:
                    return []
                
                data = response.json()
                results = []
                
                for item in data.get("data", [])[:10]:
                    # Extraire l'année depuis first_air_time ou year
                    release_year = None
                    if item.get("year"):
                        try:
                            release_year = int(item["year"])
                        except (ValueError, TypeError):
                            pass
                    elif item.get("first_air_time"):
                        try:
                            release_year = int(item["first_air_time"][:4])
                        except (ValueError, IndexError, TypeError):
                            pass
                    
                    # Construire l'URL du poster
                    poster = None
                    if item.get("image_url"):
                        poster = item["image_url"]
                    elif item.get("thumbnail"):
                        poster = item["thumbnail"]
                    
                    # TVDB retourne tvdb_id dans le champ 'tvdb_id' ou 'id'
                    tvdb_id = item.get("tvdb_id") or item.get("id")
                    if tvdb_id:
                        # S'assurer que c'est un entier
                        if isinstance(tvdb_id, str):
                            # Enlever le préfixe "series-" si présent
                            tvdb_id = tvdb_id.replace("series-", "")
                            try:
                                tvdb_id = int(tvdb_id)
                            except ValueError:
                                continue
                        
                        results.append(TVDBSearchResult(
                            id=tvdb_id,
                            title=item.get("name") or item.get("translations", {}).get(self.language, ""),
                            original_title=item.get("name"),
                            year=release_year,
                            overview=item.get("overview") or item.get("overviews", {}).get(self.language),
                            poster_path=poster,
                            popularity=float(item.get("score", 0) or 0),
                        ))
                
                return results
                
        except Exception as e:
            print(f"TVDB search error: {e}")
            return []
    
    async def get_series_details(self, tvdb_id: int) -> Optional[dict]:
        """Récupère les détails d'une série."""
        token = await self._get_token()
        if not token:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{self.base_url}/series/{tvdb_id}/extended",
                    headers=self._get_headers(token),
                )
                
                if response.status_code != 200:
                    return None
                
                data = response.json()
                series_data = data.get("data", {})
                
                # Extraire les infos pertinentes
                result = {
                    "id": series_data.get("id"),
                    "name": series_data.get("name"),
                    "year": series_data.get("year"),
                    "overview": series_data.get("overview"),
                    "status": series_data.get("status", {}).get("name") if isinstance(series_data.get("status"), dict) else None,
                    "first_aired": series_data.get("firstAired"),
                }
                
                # Trouver le poster
                artworks = series_data.get("artworks", [])
                for artwork in artworks:
                    if artwork.get("type") == 2:  # Type 2 = poster
                        result["poster"] = artwork.get("image")
                        break
                
                # Fallback sur l'image principale
                if "poster" not in result and series_data.get("image"):
                    result["poster"] = series_data.get("image")
                
                return result
                
        except Exception as e:
            print(f"TVDB get series error: {e}")
            return None
    
    async def get_series_episodes(self, tvdb_id: int, season: Optional[int] = None) -> list[dict]:
        """Récupère les épisodes d'une série."""
        token = await self._get_token()
        if not token:
            return []
        
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                params = {}
                if season is not None:
                    params["season"] = season
                
                response = await client.get(
                    f"{self.base_url}/series/{tvdb_id}/episodes/default",
                    params=params,
                    headers=self._get_headers(token),
                )
                
                if response.status_code != 200:
                    return []
                
                data = response.json()
                episodes = data.get("data", {}).get("episodes", [])
                
                return [{
                    "id": ep.get("id"),
                    "name": ep.get("name"),
                    "season": ep.get("seasonNumber"),
                    "episode": ep.get("number"),
                    "aired": ep.get("aired"),
                    "overview": ep.get("overview"),
                } for ep in episodes]
                
        except Exception as e:
            print(f"TVDB get episodes error: {e}")
            return []
    
    async def match_series(
        self,
        title: str,
        year: Optional[int] = None
    ) -> Optional[TVDBSearchResult]:
        """Trouve la meilleure correspondance pour une série."""
        if not title:
            return None
        
        # Stratégie de recherche progressive
        search_attempts = []
        
        # 1. Recherche avec titre et année
        if year:
            search_attempts.append((title, year))
        
        # 2. Recherche avec titre seul
        search_attempts.append((title, None))
        
        # Exécuter les recherches
        for query, search_year in search_attempts:
            results = await self.search_series(query, search_year)
            
            if results:
                # Si on a l'année, chercher une correspondance exacte
                if year:
                    for result in results:
                        if result.year == year:
                            return result
                
                # Sinon retourner le plus pertinent (premier résultat)
                return results[0]
        
        return None


# Instance globale
tvdb_service = TVDBService()
