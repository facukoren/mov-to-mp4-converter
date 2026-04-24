@echo off
setlocal enabledelayedexpansion
title MOV to MP4 Converter
cd /d "%~dp0"

REM ── 1. Python ──────────────────────────────────────────────────────────────
where python >nul 2>&1
if not errorlevel 1 goto :check_ffmpeg

echo.
echo  [!] Python no esta instalado. Descargando e instalando...
echo      Esto solo ocurre la primera vez (~25 MB).
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "$tmp = [System.IO.Path]::GetTempPath() + 'python_installer.exe';" ^
  "$url = 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe';" ^
  "Write-Host '  Descargando Python...';" ^
  "Invoke-WebRequest $url -OutFile $tmp;" ^
  "Write-Host '  Instalando Python (sin necesidad de hacer nada)...';" ^
  "Start-Process $tmp -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1' -Wait;" ^
  "Remove-Item $tmp;" ^
  "Write-Host '  Python instalado.'"

REM Refrescar PATH desde el registro para que python sea visible sin reiniciar
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USERPATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "SYSPATH=%%B"
set "PATH=%SYSPATH%;%USERPATH%"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] No se pudo instalar Python automaticamente.
    echo  Descargalo manualmente desde https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ── 2. ffmpeg (bin/ local primero, luego PATH, sino descarga) ──────────────
:check_ffmpeg
if exist "%~dp0bin\ffmpeg.exe" (
    set "PATH=%~dp0bin;%PATH%"
    goto :launch
)

where ffmpeg >nul 2>&1
if not errorlevel 1 goto :launch

echo.
echo  [!] ffmpeg no encontrado. Descargando automaticamente (~50 MB)...
echo      Esto solo ocurre la primera vez.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "$tmp = [System.IO.Path]::GetTempPath() + 'ffmpeg_dl.zip';" ^
  "$url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip';" ^
  "Write-Host '  Descargando ffmpeg...';" ^
  "Invoke-WebRequest $url -OutFile $tmp;" ^
  "Write-Host '  Extrayendo...';" ^
  "$bin = '%~dp0bin';" ^
  "New-Item -ItemType Directory -Force -Path $bin | Out-Null;" ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$zip = [System.IO.Compression.ZipFile]::OpenRead($tmp);" ^
  "foreach ($e in $zip.Entries) {" ^
  "  if ($e.Name -eq 'ffmpeg.exe' -or $e.Name -eq 'ffprobe.exe') {" ^
  "    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, \"$bin\$($e.Name)\", $true)" ^
  "  }" ^
  "};" ^
  "$zip.Dispose();" ^
  "Remove-Item $tmp;" ^
  "Write-Host '  ffmpeg listo.'"

if not exist "%~dp0bin\ffmpeg.exe" (
    echo.
    echo  [ERROR] No se pudo descargar ffmpeg. Revisa tu conexion a internet.
    pause
    exit /b 1
)

set "PATH=%~dp0bin;%PATH%"
echo.

REM ── 3. Dependencias Python ─────────────────────────────────────────────────
python -c "import modal" >nul 2>&1
if errorlevel 1 (
    echo  Instalando modal SDK...
    python -m pip install modal --quiet
)

REM ── 4. Lanzar UI ───────────────────────────────────────────────────────────
:launch
start "" pythonw "%~dp0ui.py"
