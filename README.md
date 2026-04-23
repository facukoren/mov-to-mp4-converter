# MOV → MP4 Converter

Convertidor simple con interfaz gráfica que transforma videos `.mov` a `.mp4` optimizando peso sin pérdida visible de calidad. Maneja correctamente videos HDR del iPhone (HLG/Dolby Vision) haciendo tone mapping a SDR BT.709 para que se vean bien en cualquier reproductor de Windows.

## Instalación (3 pasos)

1. **Descargar el repo**
   Click verde *Code* → *Download ZIP* → extraerlo donde quieras.

2. **Doble click en `install.bat`**
   Instala automáticamente Python y ffmpeg (si no los tenés).
   Cuando termine, **cerrá la ventana**.

3. **Doble click en `ui.bat`**
   Se abre la interfaz. Listo.

> Si es la primera vez que instalás algo con `winget`, Windows puede pedir permisos de administrador. Aceptá.

## Cómo usar

1. Click en **Agregar archivos…** (o **Agregar carpeta…** para procesar varios a la vez).
2. Opcional: elegir **carpeta de destino** (por defecto queda al lado del original).
3. Click en **Convertir**.

Los archivos originales nunca se borran. Los logs de cada sesión quedan en `logs/`.

## Qué hace por dentro

| Entrada                     | Qué hace                                                |
|-----------------------------|---------------------------------------------------------|
| Video (cualquier codec)     | Re-encode a **H.264 CRF 23**, profile High 4.1, yuv420p |
| Video HDR (HLG / PQ)        | Tone mapping BT.2020 HDR → BT.709 SDR 8-bit             |
| Audio AAC                   | Copy (sin re-encode)                                    |
| Audio PCM/otros             | Re-encode a AAC 192 kbps                                |

Resultado: reproduce en cualquier Windows sin instalar codecs, con peso mucho menor y calidad indistinguible a ojo.

## Requisitos

- Windows 10 o 11
- Python 3.10+ (se instala automáticamente)
- ffmpeg (se instala automáticamente)

## Troubleshooting

- **"ffmpeg no encontrado"** al abrir la UI: cerrá la app, ejecutá `install.bat` y después abrí una terminal nueva antes de relanzar.
- **No se abre nada al hacer doble click en `ui.bat`**: abrí una consola en la carpeta y ejecutá `python ui.py` para ver el error.
- **El video se ve con colores raros**: el tone mapping HDR → SDR ya está activado. Si persiste, abrí un issue con el archivo de origen.

## Licencia

MIT
