"""API d'authentification."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Cookie, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.services.auth import auth_service, decode_token
from app.models import User


router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


# ============== Schemas ==============

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    password_changed: bool


class UserResponse(BaseModel):
    id: int
    username: str
    password_changed: bool
    created_at: str
    
    class Config:
        from_attributes = True


class CreateUserRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: Optional[str] = None  # Optionnel pour l'admin
    new_password: str


# ============== Dependency ==============

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_token: Optional[str] = Cookie(default=None)
) -> User:
    """Récupère l'utilisateur courant à partir du token."""
    token = None
    
    # Essayer d'abord le header Authorization
    if credentials:
        token = credentials.credentials
    # Sinon essayer le cookie
    elif auth_token:
        token = auth_token
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = int(payload.get("sub", 0))
    user = await auth_service.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur non trouvé",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


# ============== Endpoints ==============

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """Authentifie un utilisateur."""
    user = await auth_service.authenticate(request.username, request.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects"
        )
    
    token = auth_service.create_token_for_user(user)
    
    # Définir le cookie httpOnly pour plus de sécurité
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,  # 7 jours
        samesite="lax"
    )
    
    return LoginResponse(
        token=token,
        username=user.username,
        password_changed=user.password_changed
    )


@router.post("/logout")
async def logout(response: Response):
    """Déconnecte l'utilisateur."""
    response.delete_cookie(key="auth_token")
    return {"message": "Déconnecté"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Retourne les informations de l'utilisateur courant."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        password_changed=current_user.password_changed,
        created_at=current_user.created_at.isoformat()
    )


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user)
):
    """Change le mot de passe de l'utilisateur courant."""
    # Si le mot de passe actuel est fourni, le vérifier
    if request.current_password:
        user = await auth_service.authenticate(current_user.username, request.current_password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe actuel incorrect"
            )
    
    # Changer le mot de passe
    success = await auth_service.change_password(current_user.id, request.new_password)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors du changement de mot de passe"
        )
    
    return {"message": "Mot de passe changé avec succès"}


# ============== Gestion des utilisateurs ==============

@router.get("/users", response_model=list[UserResponse])
async def list_users(current_user: User = Depends(get_current_user)):
    """Liste tous les utilisateurs."""
    users = await auth_service.get_all_users()
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            password_changed=u.password_changed,
            created_at=u.created_at.isoformat()
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse)
async def create_user(
    request: CreateUserRequest,
    current_user: User = Depends(get_current_user)
):
    """Crée un nouvel utilisateur admin."""
    try:
        user = await auth_service.create_user(request.username, request.password)
        return UserResponse(
            id=user.id,
            username=user.username,
            password_changed=user.password_changed,
            created_at=user.created_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user)
):
    """Supprime un utilisateur."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas supprimer votre propre compte"
        )
    
    try:
        success = await auth_service.delete_user(user_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Utilisateur non trouvé"
            )
        return {"message": "Utilisateur supprimé"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user)
):
    """Réinitialise le mot de passe d'un utilisateur."""
    success = await auth_service.change_password(user_id, request.new_password)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    return {"message": "Mot de passe réinitialisé"}
