"""
Configuración central del sistema Social AI.
Lee variables de entorno desde .env y expone un objeto Config singleton.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # ── Rutas ──────────────────────────────────────────────────────────────
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    MEDIA_DIR: Path = DATA_DIR / "media"
    EXPORTS_DIR: Path = DATA_DIR / "exports"
    DB_DIR: Path = DATA_DIR / "db"
    LOGS_DIR: Path = BASE_DIR / "logs"

    # ── Base de datos ──────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR}/social_ai.db")

    # ── IA local (Ollama) ──────────────────────────────────────────────────
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")
    OLLAMA_VISION_MODEL: str = os.getenv("OLLAMA_VISION_MODEL", "llava")

    # ── TTS ────────────────────────────────────────────────────────────────
    TTS_ENGINE: str = os.getenv("TTS_ENGINE", "edge-tts")   # edge-tts | coqui
    TTS_VOICE: str = os.getenv("TTS_VOICE", "es-MX-DaliaNeural")

    # ── APIs de medios gratuitos ───────────────────────────────────────────
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
    PIXABAY_API_KEY: str = os.getenv("PIXABAY_API_KEY", "")
    UNSPLASH_ACCESS_KEY: str = os.getenv("UNSPLASH_ACCESS_KEY", "")

    # ── Redes sociales ─────────────────────────────────────────────────────
    # Instagram (Meta Graph API)
    INSTAGRAM_ACCESS_TOKEN: str = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    INSTAGRAM_ACCOUNT_ID: str = os.getenv("INSTAGRAM_ACCOUNT_ID", "")

    # YouTube
    YOUTUBE_CLIENT_SECRETS: str = os.getenv(
        "YOUTUBE_CLIENT_SECRETS", str(BASE_DIR / "youtube_secrets.json")
    )

    # TikTok (Business API)
    TIKTOK_ACCESS_TOKEN: str = os.getenv("TIKTOK_ACCESS_TOKEN", "")
    TIKTOK_ADVERTISER_ID: str = os.getenv("TIKTOK_ADVERTISER_ID", "")

    # ── Web UI ─────────────────────────────────────────────────────────────
    WEB_HOST: str = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT: int = int(os.getenv("WEB_PORT", "8000"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")

    # ── Nicho / Marca ──────────────────────────────────────────────────────
    NICHE: str = os.getenv("NICHE", "finanzas personales")
    BRAND_VOICE: str = os.getenv(
        "BRAND_VOICE",
        "Educativo, cercano, motivador. Usamos lenguaje claro y ejemplos prácticos.",
    )
    BRAND_NAME: str = os.getenv("BRAND_NAME", "MiMarca")

    # ── Video ──────────────────────────────────────────────────────────────
    VIDEO_WIDTH: int = 1080
    VIDEO_HEIGHT: int = 1920   # vertical (9:16)
    VIDEO_FPS: int = 30
    MAX_VIDEO_DURATION: int = 60  # segundos


settings = Config()
