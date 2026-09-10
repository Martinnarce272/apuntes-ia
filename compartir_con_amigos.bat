@echo off
chcp 65001 > nul
title ApuntesIA - Compartir con Amigos (Túnel Público Cloudflare)
color 0A

echo ===================================================================
echo               🌐 APUNTES-IA - MODO COMPARTIR PÚBLICO 🚀
echo ===================================================================
echo.

cd /d "%~dp0"

echo [1/3] Verificando servidor local en puerto 5001...
netstat -ano | findstr :5001 > nul
if %errorlevel% neq 0 (
    echo [INFO] Iniciando servidor local en segundo plano...
    start /b python app.py > nul 2>&1
    timeout /t 2 /nobreak > nul
) else (
    echo [INFO] El servidor local ya está en ejecución en puerto 5001.
)

echo.
echo [2/3] Conectando con la red global de Cloudflare...
echo.
echo ===================================================================
echo   COPIA EL ENLACE QUE TERMINA EN: .trycloudflare.com
echo   Y compártelo con tus amigos por WhatsApp o cualquier red.
echo   Funciona desde celulares y computadoras sin importar la red WiFi.
echo ===================================================================
echo.

cloudflared.exe tunnel --url http://localhost:5001

pause
