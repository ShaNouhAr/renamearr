"""Service d'intégration avec l'API TMDB."""
import asyncio
from typing import Optional
from urllib.parse import quote

import httpx

from app.config import settings
from app.models import MediaType, TMDBSearchResult


class TMDBService:
    """Service pour interagir avec l'API TMDB."""
    
    def __init__(self):
        self.api_key = settings.tmdb_api_key
        self.base_url = settings.tmdb_base_url
        self.language = settings.tmdb_language
        self.image_base_url = "https://image.tmdb.org/t/p/w500"
    
    def _get_headers(self) -> dict:
        """Retourne les headers pour les requêtes API."""
        return {
            "Accept": "application/json",
        }
    
    def _get_params(self, **kwargs) -> dict:
        """Retourne les paramètres de base pour les requêtes."""
        params = {
            "api_key": self.api_key,
            "language": self.language,
        }
        params.update(kwargs)
        return params
    
    async def search_movie(self, query: str, year: Optional[int] = None) -> list[TMDBSearchResult]:
        """Recherche un film sur TMDB."""
        async with httpx.AsyncClient() as client:
            params = self._get_params(query=query)
            if year:
                params["year"] = year
            
            response = await client.get(
                f"{self.base_url}/search/movie",
                params=params,
                headers=self._get_headers(),
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            results = []
            
            for item in data.get("results", [])[:10]:
                release_year = None
                if item.get("release_date"):
                    try:
                        release_year = int(item["release_date"][:4])
                    except (ValueError, IndexError):
                        pass
                
                results.append(TMDBSearchResult(
                    id=item["id"],
                    title=item.get("title", ""),
                    original_title=item.get("original_title"),
                    year=release_year,
                    release_date=item.get("release_date"),
                    overview=item.get("overview"),
                    poster_path=f"{self.image_base_url}{item['poster_path']}" if item.get("poster_path") else None,
                    media_type=MediaType.MOVIE,
                    popularity=item.get("popularity", 0),
                ))
            
            return results
    
    async def search_tv(self, query: str, year: Optional[int] = None) -> list[TMDBSearchResult]:
        """Recherche une série sur TMDB."""
        async with httpx.AsyncClient() as client:
            params = self._get_params(query=query)
            if year:
                params["first_air_date_year"] = year
            
            response = await client.get(
                f"{self.base_url}/search/tv",
                params=params,
                headers=self._get_headers(),
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            results = []
            
            for item in data.get("results", [])[:10]:
                release_year = None
                if item.get("first_air_date"):
                    try:
                        release_year = int(item["first_air_date"][:4])
                    except (ValueError, IndexError):
                        pass
                
                results.append(TMDBSearchResult(
                    id=item["id"],
                    title=item.get("name", ""),
                    original_title=item.get("original_name"),
                    year=release_year,
                    release_date=item.get("first_air_date"),
                    overview=item.get("overview"),
                    poster_path=f"{self.image_base_url}{item['poster_path']}" if item.get("poster_path") else None,
                    media_type=MediaType.TV,
                    popularity=item.get("popularity", 0),
                ))
            
            return results
    
    async def search_multi(self, query: str, year: Optional[int] = None) -> list[TMDBSearchResult]:
        """Recherche films et séries sur TMDB."""
        # Lancer les deux recherches en parallèle
        movies, tv_shows = await asyncio.gather(
            self.search_movie(query, year),
            self.search_tv(query, year),
        )
        
        # Combiner et trier par popularité
        all_results = movies + tv_shows
        all_results.sort(key=lambda x: x.popularity, reverse=True)
        
        return all_results[:15]
    
    async def get_movie_details(self, movie_id: int) -> Optional[dict]:
        """Récupère les détails d'un film."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/movie/{movie_id}",
                params=self._get_params(),
                headers=self._get_headers(),
            )
            
            if response.status_code != 200:
                return None
            
            return response.json()
    
    async def get_tv_details(self, tv_id: int) -> Optional[dict]:
        """Récupère les détails d'une série."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tv/{tv_id}",
                params=self._get_params(),
                headers=self._get_headers(),
            )
            
            if response.status_code != 200:
                return None
            
            return response.json()
    
    async def get_tv_season(self, tv_id: int, season_number: int) -> Optional[dict]:
        """Récupère les détails d'une saison."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tv/{tv_id}/season/{season_number}",
                params=self._get_params(),
                headers=self._get_headers(),
            )
            
            if response.status_code != 200:
                return None
            
            return response.json()
    
    async def match_media(
        self,
        title: str,
        year: Optional[int] = None,
        media_type: MediaType = MediaType.UNKNOWN
    ) -> Optional[TMDBSearchResult]:
        """Trouve la meilleure correspondance pour un média."""
        if not title:
            return None
        
        # Fonction interne pour chercher
        async def do_search(query: str, search_year: Optional[int] = None):
            if media_type == MediaType.MOVIE:
                return await self.search_movie(query, search_year)
            elif media_type == MediaType.TV:
                return await self.search_tv(query, search_year)
            else:
                return await self.search_multi(query, search_year)
        
        # Stratégie de recherche progressive
        search_attempts = []
        
        # 1. Recherche avec titre et année
        if year:
            search_attempts.append((title, year))
        
        # 2. Recherche avec titre seul (sans année)
        search_attempts.append((title, None))
        
        # 3. Si le titre est court ou spécial, essayer des variantes
        clean_title = title.strip()
        if len(clean_title) <= 4 or not clean_title.isalnum():
            # Essayer avec le titre tel quel (cas spéciaux comme "xXx", "It", etc.)
            search_attempts.append((clean_title, year if year else None))
        
        # Exécuter les recherches
        for query, search_year in search_attempts:
            results = await do_search(query, search_year)
            
            if results:
                # Si on a l'année, chercher une correspondance exacte
                if year:
                    for result in results:
                        if result.year == year:
                            return result
                
                # Sinon retourner le plus populaire
                return results[0]
        
        return None


# Instance globale
tmdb_service = TMDBService()
