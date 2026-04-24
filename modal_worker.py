"""
Modal worker: recibe un .mov como bytes, convierte a .mp4, devuelve progress + resultado.

Cambios vs versión anterior:
- memory=4096  → no más OOM con archivos de iPhone
- Generator     → yield progress cada 5% mientras ffmpeg corre
- Monta convert.py → lógica única, sin duplicación que pueda divergir
- ffmpeg stderr → capturado y devuelto en el payload de error
Deploy: python -m modal deploy modal_worker.py
"""

from __future__ import annotations

from pathlib import Path
import modal

app = modal.App("mov-to-mp4-converter")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .add_local_python_source("convert")   # empaqueta convert.py como módulo importable
)


@app.function(
    image=image,
    cpu=4,
    memory=4096,   # 4 GB — necesario para archivos iPhone de varios GB en RAM
    timeout=3600,
)
def convert(video_bytes: bytes, filename: str):
    """
    Generator que yield-ea dicts de progreso y al final el resultado.

    Mensajes posibles:
      {"type": "info",     "vstrat": str, "astrat": str, "duration": float}
      {"type": "progress", "pct": int, "speed": float, "eta": float}
      {"type": "done",     "result": bytes, "stats": dict}
      {"type": "error",    "message": str, "stderr": str}
    """
    import subprocess
    import tempfile
    import time

    from convert import build_args, build_ffmpeg_cmd, duration_seconds, probe_full

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / filename
        dst = Path(tmp) / (Path(filename).stem + ".mp4")

        src.write_bytes(video_bytes)

        # ── Probe ──────────────────────────────────────────────────────────────
        try:
            info = probe_full(src)
        except subprocess.CalledProcessError as e:
            yield {"type": "error", "message": "ffprobe falló", "stderr": e.stderr or ""}
            return

        streams = info.get("streams", [])
        map_args, codec_args, vstrat, astrat = build_args(streams)
        total = duration_seconds(info)

        yield {"type": "info", "vstrat": vstrat, "astrat": astrat, "duration": total}

        # ── Encode ─────────────────────────────────────────────────────────────
        cmd = build_ffmpeg_cmd(src, dst, map_args, codec_args)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        started = time.monotonic()
        last_pct = -5

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("out_time_ms=") or total <= 0:
                continue
            try:
                sec = int(line.split("=", 1)[1]) / 1_000_000
            except (ValueError, IndexError):
                continue

            pct = min(int(sec / total * 100), 99)
            if pct < last_pct + 5:
                continue

            elapsed = time.monotonic() - started
            speed = sec / elapsed if elapsed > 0 else 0
            eta = (total - sec) / speed if speed > 0 else 0
            yield {"type": "progress", "pct": pct, "speed": round(speed, 2), "eta": round(eta, 1)}
            last_pct = pct

        proc.wait()
        stderr_text = (proc.stderr.read() or "").strip() if proc.stderr else ""

        if proc.returncode != 0:
            yield {
                "type": "error",
                "message": f"ffmpeg exit {proc.returncode}",
                "stderr": stderr_text[-2000:],
            }
            return

        src_size = src.stat().st_size
        dst_size = dst.stat().st_size
        elapsed = time.monotonic() - started

        yield {
            "type": "done",
            "result": dst.read_bytes(),
            "stats": {
                "src_size": src_size,
                "dst_size": dst_size,
                "ratio": round((1 - dst_size / src_size) * 100, 1),
                "elapsed": round(elapsed, 1),
                "speed": round(total / elapsed, 2) if elapsed > 0 else 0,
                "vstrat": vstrat,
                "astrat": astrat,
                "stderr": stderr_text,
            },
        }
