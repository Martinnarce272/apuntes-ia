@echo off
chcp 65001 > nul
title ApuntesIA - Generador Inteligente de Apuntes
color 0B

echo ===================================================================
echo                     🧠 APUNTES-IA 🎓
echo       Generador Inteligente de Apuntes con Gemini y YouTube/PDF
echo ===================================================================
echo.

cd /d "%~dp0"

echo [1/3] Verificando entorno de Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] No se detecto Python instalado en el sistema.
    echo Por favor instala Python 3.10+ desde python.org y vuelve a intentar.
    pause
    exit /b 1
)

echo [2/3] Verificando e instalando dependencias requeridas...
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo [AVISO] Ocurrio un aviso al verificar paquetes, continuando...
)

echo [3/3] Iniciando servidor web en http://localhost:5001 ...
start "" http://localhost:5001

echo.
echo ===================================================================
echo   La aplicacion se ha abierto en tu navegador web.
echo   Para cerrar la aplicacion, cierra esta ventana.
echo ===================================================================
echo.

python app.py

pause
