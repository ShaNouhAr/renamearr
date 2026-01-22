"""Service d'authentification."""
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, async_session

# Configuration JWT
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7 jours

# Utilisateur par défaut
DEFAULT_USERNAME = "root"
DEFAULT_PASSWORD = "root"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie un mot de passe."""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def hash_password(password: str) -> str:
    """Hash un mot de passe."""
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crée un token JWT."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """Décode un token JWT."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


class AuthService:
    """Service de gestion de l'authentification."""
    
    async def init_default_user(self):
        """Crée l'utilisateur par défaut s'il n'existe pas."""
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.username == DEFAULT_USERNAME)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(
                    username=DEFAULT_USERNAME,
                    password_hash=hash_password(DEFAULT_PASSWORD),
                    password_changed=False
                )
                session.add(user)
                await session.commit()
                print(f"Utilisateur par défaut créé: {DEFAULT_USERNAME}/{DEFAULT_PASSWORD}")
    
    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authentifie un utilisateur."""
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            user = result.scalar_one_or_none()
            
            if user and verify_password(password, user.password_hash):
                return user
            return None
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Récupère un utilisateur par son username."""
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            return result.scalar_one_or_none()
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Récupère un utilisateur par son ID."""
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    
    async def get_all_users(self) -> list[User]:
        """Récupère tous les utilisateurs."""
        async with async_session() as session:
            result = await session.execute(select(User))
            return list(result.scalars().all())
    
    async def create_user(self, username: str, password: str) -> User:
        """Crée un nouvel utilisateur."""
        async with async_session() as session:
            # Vérifier si l'utilisateur existe déjà
            result = await session.execute(
                select(User).where(User.username == username)
            )
            if result.scalar_one_or_none():
                raise ValueError(f"L'utilisateur {username} existe déjà")
            
            user = User(
                username=username,
                password_hash=hash_password(password),
                password_changed=True  # Pas le mot de passe par défaut
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
    
    async def change_password(self, user_id: int, new_password: str) -> bool:
        """Change le mot de passe d'un utilisateur."""
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return False
            
            user.password_hash = hash_password(new_password)
            user.password_changed = True
            await session.commit()
            return True
    
    async def delete_user(self, user_id: int) -> bool:
        """Supprime un utilisateur."""
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return False
            
            # Ne pas supprimer le dernier utilisateur
            count_result = await session.execute(select(User))
            users = list(count_result.scalars().all())
            if len(users) <= 1:
                raise ValueError("Impossible de supprimer le dernier utilisateur")
            
            await session.delete(user)
            await session.commit()
            return True
    
    def create_token_for_user(self, user: User) -> str:
        """Crée un token pour un utilisateur."""
        return create_access_token({
            "sub": str(user.id),
            "username": user.username,
            "password_changed": user.password_changed
        })


# Instance globale
auth_service = AuthService()
