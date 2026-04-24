@echo off
setlocal enabledelayedexpansion
title MOV to MP4 Converter
cd /d "%~dp0"

REM ── 1. Python ──────────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!] Python no esta instalado.
    echo      Abriendo descarga de Python...
    echo      Instala Python, reinicia y vuelve a ejecutar este archivo.
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

REM ── 2. ffmpeg (local primero, luego PATH, sino descarga) ───────────────────
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
  "Write-Host '  Descargando...';" ^
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
  "Write-Host '  listo.'"

if not exist "%~dp0bin\ffmpeg.exe" (
    echo.
    echo  [ERROR] No se pudo descargar ffmpeg. Revisa tu conexion a internet.
    pause
    exit /b 1
)

set "PATH=%~dp0bin;%PATH%"
echo.

REM ── 3. Lanzar la UI ────────────────────────────────────────────────────────
:launch
start "" pythonw "%~dp0ui.py"
