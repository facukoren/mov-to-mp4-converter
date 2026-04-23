@echo off
setlocal
title Instalador - MOV to MP4 Converter

echo ===============================================
echo  Instalador de dependencias
echo ===============================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [!] Python no esta instalado.
    echo     Instalando Python via winget...
    winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo [ERROR] No se pudo instalar Python automaticamente.
        echo Descargalo manualmente desde: https://www.python.org/downloads/
        pause
        exit /b 1
    )
) else (
    echo [OK] Python ya esta instalado.
)

echo.

REM --- Check ffmpeg ---
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [!] ffmpeg no esta instalado.
    echo     Instalando ffmpeg via winget...
    winget install --id Gyan.FFmpeg --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo [ERROR] No se pudo instalar ffmpeg automaticamente.
        echo Descargalo manualmente desde: https://www.gyan.dev/ffmpeg/builds/
        pause
        exit /b 1
    )
) else (
    echo [OK] ffmpeg ya esta instalado.
)

echo.
echo ===============================================
echo  Instalacion completa
echo ===============================================
echo.
echo IMPORTANTE: cerra esta ventana y abri una NUEVA
echo terminal / ventana antes de ejecutar ui.bat,
echo para que Windows vea los nuevos comandos.
echo.
pause
