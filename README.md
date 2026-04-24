# MOV → MP4 Converter

Convierte videos `.mov` a `.mp4` con interfaz gráfica, reduciendo el peso significativamente sin pérdida visible de calidad. Maneja correctamente videos HDR del iPhone (HLG/Dolby Vision) para que se vean bien en cualquier reproductor de Windows.

## Uso

1. **Descargar el repo** → *Code* → *Download ZIP* → extraer la carpeta
2. **Doble click en `launch.bat`** → listo

La primera vez descarga ffmpeg automáticamente (~50 MB). Python es el único requisito previo.

> **¿No tenés Python?** → descargalo desde [python.org/downloads](https://www.python.org/downloads/) e instalalo. Después volvé al paso 2.

---

## ¿Qué hace?

1. Arrastrás archivos `.mov` o una carpeta
2. Elegís carpeta de destino (opcional, por defecto queda al lado del original)
3. Click **Convertir** — muestra progreso en tiempo real

Los archivos originales nunca se borran. Los logs quedan en `logs/`.

## Por qué se ve mejor y pesa menos

| Situación                       | Qué hace                                              |
|---------------------------------|-------------------------------------------------------|
| Video cualquier codec           | Re-encode **H.264 CRF 23** — compatible en todo Windows sin codecs extra |
| Video HDR (iPhone con HLG/PQ)   | Tone mapping BT.2020 HDR → BT.709 SDR para colores correctos |
| Audio AAC                       | Copia sin re-encode                                   |
| Audio PCM / otros               | Re-encode AAC 192 kbps                                |

## Requisitos

- Windows 10 / 11
- [Python 3.10+](https://www.python.org/downloads/)
- ffmpeg — **se descarga automáticamente** la primera vez

## Licencia

MIT
