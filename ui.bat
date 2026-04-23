@echo off
setlocal

where python >nul 2>&1
if errorlevel 1 (
    echo Python no esta instalado.
    echo Ejecuta primero install.bat para configurar todo.
    pause
    exit /b 1
)

start "" pythonw "%~dp0ui.py"
