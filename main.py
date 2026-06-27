"""
Punto de entrada principal del sistema Social AI.
Ejecutar con: python main.py
"""

import uvicorn
from core.config import settings
from core.database import init_db
from core.logger import get_logger

log = get_logger("main")


def main():
    log.info("=" * 60)
    log.info("  Social AI — Sistema de Automatización Local")
    log.info("  Marca: %s | Nicho: %s", settings.BRAND_NAME, settings.NICHE)
    log.info("=" * 60)

    # Inicializar base de datos
    init_db()
    log.info("Base de datos inicializada: %s", settings.DATABASE_URL)

    # Verificar dependencias críticas
    _check_dependencies()

    # Iniciar servidor web
    log.info("Iniciando servidor en http://%s:%d", settings.WEB_HOST, settings.WEB_PORT)
    uvicorn.run(
        "web.app:app",
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        reload=False,
        log_level="warning",
    )


def _check_dependencies():
    import shutil
    import subprocess

    # FFmpeg
    if shutil.which("ffmpeg"):
        log.info("✅ FFmpeg disponible")
    else:
        log.warning("⚠️  FFmpeg no encontrado. La producción de video no funcionará.")

    # Ollama
    try:
        import httpx
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            log.info("✅ Ollama disponible. Modelos: %s", ", ".join(models[:3]))
            if settings.OLLAMA_MODEL not in " ".join(models):
                log.warning(
                    "⚠️  Modelo '%s' no encontrado. Instala con: ollama pull %s",
                    settings.OLLAMA_MODEL, settings.OLLAMA_MODEL
                )
        else:
            log.warning("⚠️  Ollama no responde correctamente")
    except Exception:
        log.warning("⚠️  Ollama no disponible en %s", settings.OLLAMA_BASE_URL)

    # Playwright
    try:
        import playwright
        log.info("✅ Playwright disponible")
    except ImportError:
        log.warning("⚠️  Playwright no instalado: pip install playwright && playwright install chromium")

    # APIs de medios
    if settings.PEXELS_API_KEY:
        log.info("✅ Pexels API configurada")
    else:
        log.warning("⚠️  PEXELS_API_KEY no configurada (media gratuita no disponible)")


if __name__ == "__main__":
    main()
