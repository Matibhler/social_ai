@echo off
echo ============================================================
echo   Social AI — Setup de instalacion (Windows)
echo ============================================================

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.11+ desde python.org
    pause
    exit /b 1
)
echo [OK] Python encontrado

:: Crear entorno virtual
if not exist "venv" (
    echo Creando entorno virtual...
    python -m venv venv
)
call venv\Scripts\activate.bat

:: Instalar dependencias
echo Instalando dependencias Python...
pip install -r requirements.txt

:: Instalar Playwright + Chromium
echo Instalando Playwright + Chromium...
playwright install chromium

:: Copiar .env
if not exist ".env" (
    copy .env.example .env
    echo [!] Archivo .env creado. Edita las claves de API antes de continuar.
)

:: Crear directorios
mkdir data\db data\media data\exports data\reports logs 2>nul

echo.
echo ============================================================
echo   Instalacion completada!
echo.
echo   Siguientes pasos:
echo   1. Edita .env con tus claves de API
echo   2. Instala FFmpeg: https://ffmpeg.org/download.html
echo   3. Ejecuta: start.bat
echo   6. Abre: http://localhost:8000
echo ============================================================
pause
