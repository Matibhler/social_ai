@echo off
title Social AI Server
cd /d "%~dp0"
set PYTHONUTF8=1
set PATH=C:\ffmpeg\ffmpeg-8.1.2-essentials_build\bin;%PATH%
call venv\Scripts\activate.bat

echo.
echo  ================================
echo   Social AI - Servidor iniciando
echo   http://127.0.0.1:8000
echo  ================================
echo.
echo  NO cierres esta ventana o el servidor se detendra.
echo.

python main.py

echo.
echo  El servidor se detuvo.
pause
