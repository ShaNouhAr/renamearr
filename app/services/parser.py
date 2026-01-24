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
    
    # Pattern pour les versions (v1, v2, v3, etc.) collées aux épisodes
    VERSION_PATTERN = r'([Ee]\d{1,3})v\d+'  # E01v2 -> E01
    
    # Patterns pour les fichiers spéciaux (extras, bonus, etc.)
    # Ces fichiers seront placés en Saison 0 (Specials selon Plex)
    SPECIAL_PATTERNS = [
        # Format avec numéro: NCED01, NCOP 02, etc.
        (r'NCED\s*(\d+)', 'NCED'),      # No Credit Ending: NCED01 -> S00E01
        (r'NCOP\s*(\d+)', 'NCOP'),      # No Credit Opening: NCOP01 -> S00E01
        (r'(?:^|\s)ED\s*(\d+)', 'ED'),  # Ending: ED1 -> S00E01
        (r'(?:^|\s)OP\s*(\d+)', 'OP'),  # Opening: OP1 -> S00E01
        (r'SP\s*(\d+)', 'SP'),          # Special: SP01 -> S00E01
        (r'OVA\s*(\d+)', 'OVA'),        # OVA: OVA1 -> S00E01
        (r'OAD\s*(\d+)', 'OAD'),        # OAD: OAD1 -> S00E01
        (r'Bonus\s*(\d+)', 'Bonus'),    # Bonus: Bonus1 -> S00E01
        (r'Extra\s*(\d+)', 'Extra'),    # Extra: Extra1 -> S00E01
        (r'PV\s*(\d+)', 'PV'),          # Preview: PV1 -> S00E01
        (r'CM\s*(\d+)', 'CM'),          # Commercial: CM1 -> S00E01
        # Format sans numéro (avec nom de chanson): NCOP Soumonka, ED Creditless, etc.
        (r'^NCED(?:\s+\w|\s*\[)', 'NCED'),  # NCED suivi de nom ou [hash]
        (r'^NCOP(?:\s+\w|\s*\[)', 'NCOP'),  # NCOP suivi de nom ou [hash]
        (r'^ED\s+Creditless', 'ED'),        # ED Creditless
        (r'^OP\s+Creditless', 'OP'),        # OP Creditless
        (r'^OVA(?:\s|$|\[)', 'OVA'),        # OVA seul
        (r'^OAD(?:\s|$|\[)', 'OAD'),        # OAD seul
        # Format dans le nom de fichier: titre.S02.OAV, titre.OVA, etc.
        (r'\.(OAV)\.', 'OAV'),              # .OAV. dans le nom
        (r'\.(OVA)\.', 'OVA'),              # .OVA. dans le nom  
        (r'\.(OAD)\.', 'OAD'),              # .OAD. dans le nom
        (r'\s(OAV)\s', 'OAV'),              # OAV avec espaces
        (r'\s(OVA)\s', 'OVA'),              # OVA avec espaces
        # Bonus/Extras avec différents noms
        (r'\s(BETISIER)(?:\s|$)', 'Bonus'), # Bêtisier/Bloopers
        (r'\s(BLOOPER)S?(?:\s|$)', 'Bonus'), # Bloopers
        (r'\s(GAG\s*REEL)(?:\s|$)', 'Bonus'), # Gag Reel
        (r'\s(MAKING\s*OF)(?:\s|$)', 'Bonus'), # Making Of
        (r'\s(BEHIND\s*THE\s*SCENES?)(?:\s|$)', 'Bonus'), # Behind the Scenes
        (r'\s(DELETED\s*SCENES?)(?:\s|$)', 'Bonus'), # Deleted Scenes
        (r'\s(FEATURETTE)S?(?:\s|$)', 'Bonus'), # Featurettes
        (r'\s(INTERVIEW)S?(?:\s|$)', 'Bonus'), # Interviews
    ]
    
    def __init__(self):
        self._special_counter = {}  # Pour numéroter les spéciaux sans numéro
    
    def _detect_special(self, filename: str) -> tuple[bool, Optional[int], Optional[str]]:
        """Détecte si c'est un fichier spécial et extrait le numéro.
        
        Returns:
            (is_special, episode_number, special_type)
        """
        # D'abord vérifier le format "S01 - NCOP 01" ou "S01 - NCED 02"
        special_with_season = re.search(r'S\d+\s*[-–]\s*(NCOP|NCED|OP|ED)\s*(\d+)', filename, re.IGNORECASE)
        if special_with_season:
            special_type = special_with_season.group(1).upper()
            num = int(special_with_season.group(2))
            return True, num, special_type
        
        for pattern, special_type in self.SPECIAL_PATTERNS:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                # Extraire le numéro s'il existe
                try:
                    if match.lastindex and match.group(1):
                        captured = match.group(1)
                        # Si c'est un nombre, l'utiliser comme épisode
                        if captured.isdigit():
                            num = int(captured)
                        else:
                            # C'est le type lui-même (OAV, OVA, etc.) - assigner 1
                            num = 1
                    else:
                        num = 1
                except (IndexError, ValueError):
                    num = 1
                return True, num, special_type
        return False, None, None
    
    def _preprocess_filename(self, filename: str) -> str:
        """Pré-traite le nom de fichier pour améliorer le parsing.
        
        - Supprime les indicateurs de version (v2, v3) collés aux épisodes
        - Normalise certains formats problématiques
        - Convertit les formats d'épisodes non standards
        """
        processed = filename
        
        # Convertir "S01 - 01" ou "S01 - 1" en "S01E01"
        # Ex: "Plunderer S01 - 01" -> "Plunderer S01E01"
        processed = re.sub(
            r'[Ss](\d{1,2})\s*[-–]\s*(\d{1,3})(?!\d)',
            r'S\1E\2',
            processed
        )
        
        # Convertir "S01.01" en "S01E01" (point comme séparateur)
        # Ex: "LA.CASA.DE.PAPEL.S01.02" -> "LA.CASA.DE.PAPEL.S01E02"
        processed = re.sub(
            r'[Ss](\d{1,2})\.(\d{1,3})(?!\d)',
            r'S\1E\2',
            processed
        )
        
        # Remplacer S01E01v2 par S01E01 (supprimer le suffixe de version)
        processed = re.sub(self.VERSION_PATTERN, r'\1', processed, flags=re.IGNORECASE)
        
        # Aussi gérer le format avec espace: "E01 v2" -> "E01"
        processed = re.sub(r'([Ee]\d{1,3})\s*v\d+', r'\1', processed)
        
        return processed
    
    def parse(self, filename: str) -> ParsedMedia:
        """Parse un nom de fichier et extrait les informations média."""
        # Pré-traiter le nom de fichier pour gérer les cas spéciaux (v2, etc.)
        processed_filename = self._preprocess_filename(filename)
        
        # Cas spécial: titre numérique suivi de S##E## (ex: "1923.S01E01", "1883.S01E01")
        # Ces nombres sont des titres de séries, pas des années
        numeric_title_match = re.match(r'^(\d{4})[.\s]S\d+E\d+', processed_filename, re.IGNORECASE)
        
        # Utiliser guessit pour le parsing initial
        result = guessit(processed_filename)
        
        parsed = ParsedMedia()
        
        # Extraire le titre
        if 'title' in result:
            parsed.title = str(result['title'])
        
        # Si c'est un titre numérique (ex: 1923, 1883, 1899), l'utiliser comme titre
        if numeric_title_match:
            numeric_title = numeric_title_match.group(1)
            # Si guessit n'a pas trouvé de titre ou l'a mis en année, utiliser le nombre comme titre
            if not parsed.title or parsed.title == numeric_title:
                parsed.title = numeric_title
        
        # Extraire l'année
        if 'year' in result:
            year = result['year']
            if isinstance(year, list):
                year = year[0]
            # Ne pas utiliser l'année si c'est en fait le titre numérique
            if numeric_title_match and str(year) == numeric_title_match.group(1):
                parsed.year = None  # Ce n'est pas une année, c'est le titre
            else:
                parsed.year = int(year)
        
        # Extraire la saison et l'épisode
        if 'season' in result:
            season = result['season']
            if isinstance(season, list):
                season = season[0]
            parsed.season = int(season)
        if 'episode' in result:
            ep = result['episode']
            if isinstance(ep, list):
                ep = ep[0]
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
    
    # Mots à supprimer du titre (collection, intégrale, etc.)
    TITLE_NOISE_WORDS = [
        r'\bInt[ée]grale\b',
        r'\bComplete\b',
        r'\bCollection\b',
        r'\bSaisons?\s*\d+[-–]?\d*\b',
        r'\bS\d+[-–]S\d+\b',
        r'\bS\d+\s*$',
        r'\bVOSTFR\b',
        r'\bMULTi\b',
        r'\bFRENCH\b',
        r'\bTRUEFRENCH\b',
    ]
    
    def _clean_title(self, title: str) -> str:
        """Nettoie un titre de ses artefacts."""
        cleaned = title
        
        # Remplacer les points et underscores par des espaces
        cleaned = cleaned.replace('.', ' ').replace('_', ' ')
        
        # Supprimer les mots de bruit (Intégrale, Complete, etc.)
        for pattern in self.TITLE_NOISE_WORDS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Supprimer les patterns de nettoyage
        for pattern in self.CLEAN_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Nettoyer les espaces multiples
        cleaned = ' '.join(cleaned.split())
        
        return cleaned.strip()
    
    def parse_path(self, file_path: Path) -> ParsedMedia:
        """Parse un chemin de fichier complet.
        
        Essaie d'abord avec le nom du fichier, puis avec le dossier parent
        si le parsing échoue ou si c'est une série avec un titre suspect.
        """
        # Vérifier d'abord si c'est un fichier spécial (NCED, NCOP, Bonus, OAV, OVA, etc.)
        is_special, special_ep, special_type = self._detect_special(file_path.stem)
        
        if is_special:
            # C'est un fichier spécial
            parsed = ParsedMedia()
            parsed.media_type = MediaType.TV
            parsed.season = 0  # Saison 0 = Specials (convention Plex/Jellyfin)
            parsed.episode = special_ep
            
            # Vérifier si le nom de fichier contient le titre (ex: "Akame ga Kill! S01 - NCOP 01")
            # Extraire tout ce qui précède "S\d+ -" ou le type spécial
            title_match = re.match(r'^(.+?)\s*S\d+\s*[-–]', file_path.stem, re.IGNORECASE)
            if title_match:
                parsed.title = self._clean_title(title_match.group(1))
            
            # Format: titre.S02.OAV ou titre.S02.OVA - extraire le titre avant S\d+
            if not parsed.title:
                oav_title_match = re.match(r'^(.+?)[.\s]S\d+[.\s](?:OAV|OVA|OAD)', file_path.stem, re.IGNORECASE)
                if oav_title_match:
                    parsed.title = self._clean_title(oav_title_match.group(1))
            
            # Format: titre.OVA ou titre.OAV sans saison
            if not parsed.title:
                simple_oav_match = re.match(r'^(.+?)[.\s](?:OAV|OVA|OAD)[.\s]', file_path.stem, re.IGNORECASE)
                if simple_oav_match:
                    parsed.title = self._clean_title(simple_oav_match.group(1))
            
            # Format: "Titre (Année) S01 BETISIER" ou "Titre S01 BLOOPER"
            if not parsed.title:
                bonus_title_match = re.match(
                    r'^(.+?)\s*(?:\(\d{4}\))?\s*S\d+\s*(?:BETISIER|BLOOPER|GAG\s*REEL|MAKING\s*OF|BEHIND|DELETED|FEATURETTE|INTERVIEW)',
                    file_path.stem, re.IGNORECASE
                )
                if bonus_title_match:
                    parsed.title = self._clean_title(bonus_title_match.group(1))
                    # Extraire l'année si présente
                    year_match = re.search(r'\((\d{4})\)', file_path.stem)
                    if year_match:
                        parsed.year = int(year_match.group(1))
            
            # Si pas de titre dans le fichier, obtenir depuis le dossier parent
            if not parsed.title and file_path.parent.name:
                parent_parsed = self.parse(file_path.parent.name)
                if parent_parsed.title:
                    parsed.title = parent_parsed.title
                    parsed.year = parent_parsed.year
            
            # Si toujours pas de titre, essayer le grand-parent (pour les sous-dossiers)
            if not parsed.title and file_path.parent.parent.name:
                grandparent_parsed = self.parse(file_path.parent.parent.name)
                if grandparent_parsed.title:
                    parsed.title = grandparent_parsed.title
                    parsed.year = grandparent_parsed.year
            
            return parsed
        
        # D'abord essayer avec le nom du fichier
        parsed = self.parse(file_path.stem)
        
        # Parser le dossier parent (souvent contient le titre de la série)
        parent_parsed = None
        if file_path.parent.name:
            parent_parsed = self.parse(file_path.parent.name)
        
        # Cas spécial: fichier avec juste un numéro d'épisode (E05, Episode 5, etc.)
        # Le titre est probablement le nom du dossier parent
        # Ex: "Kyoukai no Kanata/E05 - Chartreuse Light.mkv"
        if parsed.episode is not None and parsed.season is None:
            # Pas de saison explicite = probablement format anime/simple
            parsed.media_type = MediaType.TV
            
            # Si le fichier n'a pas de titre valide, utiliser celui du parent
            if not parsed.title and parent_parsed and parent_parsed.title:
                parsed.title = parent_parsed.title
                if parent_parsed.year:
                    parsed.year = parent_parsed.year
            
            # Assigner la saison (depuis le parent ou par défaut 1)
            if parent_parsed and parent_parsed.season is not None:
                parsed.season = parent_parsed.season
            else:
                # Par défaut saison 1 pour les anime sans numéro de saison
                parsed.season = 1
            
            return parsed
        
        # Pour les séries, le dossier parent contient souvent un meilleur titre
        # (ex: "Les.Simpson.S17" au lieu de "Les Simpson-Le fils a maman")
        should_use_parent = False
        
        if parsed.media_type == MediaType.TV and parent_parsed:
            # Utiliser le parent si:
            # 1. Le titre du fichier contient le titre du parent (probable nom d'épisode ajouté)
            # 2. Le titre du parent est plus court et plus propre
            if parent_parsed.title and parsed.title:
                parent_clean = parent_parsed.title.lower().replace(' ', '')
                file_clean = parsed.title.lower().replace(' ', '')
                
                # Si le titre parent est contenu dans le titre fichier, c'est probablement
                # que le titre fichier inclut le nom de l'épisode
                if parent_clean and file_clean.startswith(parent_clean[:min(10, len(parent_clean))]):
                    should_use_parent = True
                # Ou si le titre fichier est beaucoup plus long (inclut description épisode)
                elif len(parsed.title) > len(parent_parsed.title) * 1.5:
                    should_use_parent = True
            
            if should_use_parent and parent_parsed.title:
                # Garder saison/épisode du fichier mais titre du parent
                parsed.title = parent_parsed.title
                if parent_parsed.year:
                    parsed.year = parent_parsed.year
        
        # Si on n'a toujours pas de titre, essayer avec le dossier parent
        if not parsed.title and parent_parsed and parent_parsed.title:
            parsed.title = parent_parsed.title
            if parent_parsed.year:
                parsed.year = parent_parsed.year
        
        return parsed


# Instance globale
parser = MediaParser()
