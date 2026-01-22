"""Modèles de données SQLAlchemy et Pydantic."""
from datetime import datetime
from enum import Enum
from typing import Optional
from pathlib import Path

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum as SQLEnum, Text
from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pydantic import BaseModel, Field

from app.config import settings


# SQLAlchemy Base
class Base(AsyncAttrs, DeclarativeBase):
    pass


# Enums
class MediaType(str, Enum):
    MOVIE = "movie"
    TV = "tv"
    UNKNOWN = "unknown"


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    MATCHED = "matched"
    LINKED = "linked"
    FAILED = "failed"
    IGNORED = "ignored"
    MANUAL = "manual"  # En attente de correction manuelle


# SQLAlchemy Models
class User(Base):
    """Utilisateur administrateur."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    password_changed = Column(Boolean, default=False)  # True si le mdp par défaut a été changé
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MediaFile(Base):
    """Fichier média dans la base de données."""
    __tablename__ = "media_files"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Fichier source
    source_path = Column(String(1024), unique=True, nullable=False)
    source_filename = Column(String(512), nullable=False)
    file_size = Column(Integer, default=0)
    
    # Parsing initial
    parsed_title = Column(String(512))
    parsed_year = Column(Integer)
    parsed_season = Column(Integer)
    parsed_episode = Column(Integer)
    media_type = Column(SQLEnum(MediaType), default=MediaType.UNKNOWN)
    
    # Correspondance TMDB
    tmdb_id = Column(Integer)
    tmdb_title = Column(String(512))
    tmdb_year = Column(Integer)
    tmdb_poster = Column(String(512))
    
    # Destination
    destination_path = Column(String(1024))
    
    # Statut
    status = Column(SQLEnum(ProcessingStatus), default=ProcessingStatus.PENDING)
    error_message = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = Column(DateTime)


# Pydantic Schemas
class MediaFileBase(BaseModel):
    """Schema de base pour un fichier média."""
    source_path: str
    source_filename: str
    file_size: int = 0
    media_type: MediaType = MediaType.UNKNOWN


class MediaFileCreate(MediaFileBase):
    """Schema pour créer un fichier média."""
    parsed_title: Optional[str] = None
    parsed_year: Optional[int] = None
    parsed_season: Optional[int] = None
    parsed_episode: Optional[int] = None


class MediaFileUpdate(BaseModel):
    """Schema pour mettre à jour un fichier média."""
    tmdb_id: Optional[int] = None
    tmdb_title: Optional[str] = None
    tmdb_year: Optional[int] = None
    media_type: Optional[MediaType] = None
    parsed_season: Optional[int] = None
    parsed_episode: Optional[int] = None
    status: Optional[ProcessingStatus] = None


class MediaFileResponse(MediaFileBase):
    """Schema de réponse pour un fichier média."""
    id: int
    parsed_title: Optional[str]
    parsed_year: Optional[int]
    parsed_season: Optional[int]
    parsed_episode: Optional[int]
    tmdb_id: Optional[int]
    tmdb_title: Optional[str]
    tmdb_year: Optional[int]
    tmdb_poster: Optional[str]
    destination_path: Optional[str]
    status: ProcessingStatus
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class TMDBSearchResult(BaseModel):
    """Résultat de recherche TMDB."""
    id: int
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    release_date: Optional[str] = None
    overview: Optional[str] = None
    poster_path: Optional[str] = None
    media_type: MediaType
    popularity: float = 0.0


class ManualMatchRequest(BaseModel):
    """Requête pour correspondance manuelle."""
    file_id: int
    tmdb_id: int
    media_type: MediaType
    season: Optional[int] = None
    episode: Optional[int] = None


class ScanRequest(BaseModel):
    """Requête pour scanner un dossier."""
    path: Optional[str] = None


class StatsResponse(BaseModel):
    """Statistiques du système."""
    total_files: int
    pending: int
    matched: int
    linked: int
    failed: int
    manual: int
    ignored: int


# Database setup
engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    """Initialise la base de données."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session():
    """Retourne une session de base de données."""
    async with async_session() as session:
        yield session
