"""Application principale FastAPI."""
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import init_db
from app.api import router as api_router
from app.auth_api import router as auth_router
from app.services.auth import auth_service, decode_token
from app.services.auto_scanner import auto_scanner


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application."""
    # Startup
    # Créer le dossier data si nécessaire
    data_dir = Path("./data")
    data_dir.mkdir(exist_ok=True)
    
    # Créer les dossiers de destination
    settings.movies_path.mkdir(parents=True, exist_ok=True)
    settings.tv_path.mkdir(parents=True, exist_ok=True)
    
    # Initialiser la base de données
    await init_db()
    
    # Créer l'utilisateur par défaut
    await auth_service.init_default_user()
    
    # Démarrer l'auto-scanner
    await auto_scanner.start()
    
    yield
    
    # Shutdown
    await auto_scanner.stop()


# Créer l'application
app = FastAPI(
    title="Renamearr",
    description="Organisateur de fichiers médias pour les setups Plex avec debrideurs (AllDebrid, RealDebrid, etc.)",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router)
app.include_router(auth_router)

# Static files and templates
static_dir = Path(__file__).parent / "static"
templates_dir = Path(__file__).parent / "templates"

# Créer les dossiers s'ils n'existent pas
static_dir.mkdir(exist_ok=True)
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))


def is_authenticated(auth_token: Optional[str]) -> bool:
    """Vérifie si le token est valide."""
    if not auth_token:
        return False
    payload = decode_token(auth_token)
    return payload is not None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, auth_token: Optional[str] = Cookie(default=None)):
    """Page principale (protégée)."""
    if not is_authenticated(auth_token):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, auth_token: Optional[str] = Cookie(default=None)):
    """Page de connexion."""
    # Si déjà connecté, rediriger vers la page principale
    if is_authenticated(auth_token):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
