@echo off
REM Drag & drop uno o varios .mov (o una carpeta) encima de este .bat.
REM Tambien se puede doble-clickear y pasar rutas como argumentos.

if "%~1"=="" (
    echo Arrastra archivos .mov o una carpeta sobre este .bat
    pause
    exit /b 1
)

python "%~dp0convert.py" %*
pause
