#!/bin/bash
set -e

echo "============================================================"
echo "  Social AI — Setup de instalación (Linux/macOS)"
echo "============================================================"

# Verificar Python 3.11+
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 no encontrado"
    exit 1
fi
echo "[OK] Python: $(python3 --version)"

# Crear entorno virtual
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# Actualizar pip
pip install -q --upgrade pip

# Instalar dependencias
echo "Instalando dependencias Python..."
pip install -r requirements.txt

# Playwright
echo "Instalando Playwright + Chromium..."
playwright install chromium

# .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "[!] Archivo .env creado. Edita las claves de API."
fi

# Directorios
mkdir -p data/db data/media data/exports data/reports logs

echo ""
echo "============================================================"
echo "  Instalación completada!"
echo ""
echo "  Siguientes pasos:"
echo "  1. Edita .env con tus claves de API"
echo "  2. Instala Ollama:   curl -fsSL https://ollama.ai/install.sh | sh"
echo "  3. Descarga modelo:  ollama pull llama3"
echo "  4. Instala FFmpeg:   sudo apt install ffmpeg"
echo "  5. Inicia el sistema: python main.py"
echo "  6. Abre:             http://localhost:8000"
echo "============================================================"
