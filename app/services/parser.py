"""Service de parsing des noms de fichiers médias."""
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from guessit import guessit

from app.models import MediaType


@dataclass
class ParsedMedia:
    """Résultat du parsing d'un nom de fichier."""
    title: Optional[str] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    media_type: MediaType = MediaType.UNKNOWN
    quality: Optional[str] = None
    source: Optional[str] = None
    codec: Optional[str] = None
    release_group: Optional[str] = None


class MediaParser:
    """Service de parsing des noms de fichiers médias."""
    
    # Patterns courants pour le nettoyage
    CLEAN_PATTERNS = [
        r'\[.*?\]',  # Supprime les tags entre crochets [TAG]
        r'\(.*?\)',  # Supprime les tags entre parenthèses (TAG) sauf année
        r'www\..*?\.com',  # Supprime les URLs
        r'www\..*?\.org',
        r'\.www\..*?',
        r'-\s*$',  # Tiret à la fin
    ]
    
    # Patterns pour détecter les séries
    TV_PATTERNS = [
        r'[Ss]\d{1,2}[Ee]\d{1,2}',  # S01E01
        r'[Ss]eason\s*\d+',  # Season 1
        r'[Ee]pisode\s*\d+',  # Episode 1
        r'\d{1,2}x\d{1,2}',  # 1x01
        r'[Ee]\d{1,2}',  # E01
    ]
    
    def __init__(self):
        pass
    
    def parse(self, filename: str) -> ParsedMedia:
        """Parse un nom de fichier et extrait les informations média."""
        # Utiliser guessit pour le parsing initial
        result = guessit(filename)
        
        parsed = ParsedMedia()
        
        # Extraire le titre
        if 'title' in result:
            parsed.title = str(result['title'])
        
        # Extraire l'année
        if 'year' in result:
            parsed.year = int(result['year'])
        
        # Extraire la saison et l'épisode
        if 'season' in result:
            parsed.season = int(result['season'])
        if 'episode' in result:
            ep = result['episode']
            if isinstance(ep, list):
                parsed.episode = int(ep[0])
            else:
                parsed.episode = int(ep)
        
        # Déterminer le type de média
        if 'type' in result:
            if result['type'] == 'episode':
                parsed.media_type = MediaType.TV
            elif result['type'] == 'movie':
                parsed.media_type = MediaType.MOVIE
        else:
            # Fallback: vérifier manuellement avec les patterns TV
            parsed.media_type = self._detect_media_type(filename, parsed)
        
        # Extraire les infos de qualité
        if 'screen_size' in result:
            parsed.quality = str(result['screen_size'])
        if 'source' in result:
            parsed.source = str(result['source'])
        if 'video_codec' in result:
            parsed.codec = str(result['video_codec'])
        if 'release_group' in result:
            parsed.release_group = str(result['release_group'])
        
        # Nettoyer le titre si nécessaire
        if parsed.title:
            parsed.title = self._clean_title(parsed.title)
        
        return parsed
    
    def _detect_media_type(self, filename: str, parsed: ParsedMedia) -> MediaType:
        """Détecte si c'est un film ou une série."""
        # Si on a une saison ou un épisode, c'est une série
        if parsed.season is not None or parsed.episode is not None:
            return MediaType.TV
        
        # Vérifier les patterns TV
        for pattern in self.TV_PATTERNS:
            if re.search(pattern, filename, re.IGNORECASE):
                return MediaType.TV
        
        # Par défaut, considérer comme film si on a un titre
        if parsed.title and parsed.year:
            return MediaType.MOVIE
        
        return MediaType.UNKNOWN
    
    def _clean_title(self, title: str) -> str:
        """Nettoie un titre de ses artefacts."""
        cleaned = title
        
        # Remplacer les points et underscores par des espaces
        cleaned = cleaned.replace('.', ' ').replace('_', ' ')
        
        # Supprimer les patterns de nettoyage
        for pattern in self.CLEAN_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Nettoyer les espaces multiples
        cleaned = ' '.join(cleaned.split())
        
        return cleaned.strip()
    
    def parse_path(self, file_path: Path) -> ParsedMedia:
        """Parse un chemin de fichier complet.
        
        Essaie d'abord avec le nom du fichier, puis avec le dossier parent
        si le parsing échoue.
        """
        # D'abord essayer avec le nom du fichier
        parsed = self.parse(file_path.stem)
        
        # Si on n'a pas de titre, essayer avec le dossier parent
        if not parsed.title and file_path.parent.name:
            parent_parsed = self.parse(file_path.parent.name)
            if parent_parsed.title:
                parsed = parent_parsed
        
        return parsed


# Instance globale
parser = MediaParser()
