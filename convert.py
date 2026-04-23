#!/usr/bin/env python3
"""
MOV -> MP4 converter optimizado.

Estrategia:
  Video:
    - h264  -> copy si ya esta en MP4-friendly bitrate, sino re-encode H.264 CRF 23
    - hevc / prores / dnxhd / otros -> H.264 CRF 23 preset slow
      (compatible con todo Windows sin extensiones, gran reduccion de peso)
  Audio:
    - aac  -> copy
    - pcm / otros -> aac 192k (compatible, calidad transparente)

Uso:
    python convert.py archivo1.mov [archivo2.mov ...]
    python convert.py carpeta/         (procesa todos los .mov dentro)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

AUDIO_COPY_CODECS = {"aac"}

HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}  # HLG y PQ

H264_BASE_ARGS = [
    "-c:v", "libx264",
    "-crf", "23",
    "-preset", "slow",
    "-profile:v", "high",
    "-level:v", "4.1",
]

SDR_COLOR_TAGS = [
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-colorspace", "bt709",
    "-color_range", "tv",
]

# Tone mapping HDR -> SDR BT.709 usando zscale + tonemap (incluido en builds Gyan)
HDR_TONEMAP_FILTER = (
    "zscale=t=linear:npl=203,"
    "format=gbrpf32le,"
    "zscale=p=bt709,"
    "tonemap=tonemap=mobius:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,"
    "format=yuv420p"
)


def check_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit(
            "ERROR: ffmpeg/ffprobe no estan en el PATH.\n"
            "Instalalo con:  winget install Gyan.FFmpeg\n"
            "Luego abri una nueva terminal y volve a correr el script."
        )


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def build_args(streams: list[dict]) -> tuple[list[str], list[str], str, str]:
    """Returns (map_args, codec_args, video_strategy, audio_strategy)."""
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)

    map_args: list[str] = []
    codec_args: list[str] = []
    video_strategy = "sin video"
    audio_strategy = "sin audio"

    if video:
        idx = video["index"]
        map_args += ["-map", f"0:{idx}"]
        vcodec = video.get("codec_name", "").lower()
        color_trc = video.get("color_transfer", "").lower()
        is_hdr = color_trc in HDR_TRANSFERS

        codec_args += list(H264_BASE_ARGS)
        if is_hdr:
            codec_args += ["-vf", HDR_TONEMAP_FILTER]
            video_strategy = (
                f"video {vcodec} HDR ({color_trc}) -> H.264 CRF 23 "
                f"+ tone map a SDR BT.709"
            )
        else:
            codec_args += ["-pix_fmt", "yuv420p"]
            video_strategy = (
                f"video {vcodec} -> H.264 CRF 23 (compatible + optimizado)"
            )
        codec_args += SDR_COLOR_TAGS

    if audio:
        idx = audio["index"]
        map_args += ["-map", f"0:{idx}"]
        acodec = audio.get("codec_name", "").lower()
        if acodec in AUDIO_COPY_CODECS:
            codec_args += ["-c:a", "copy"]
            audio_strategy = f"audio {acodec} -> copy"
        else:
            codec_args += ["-c:a", "aac", "-b:a", "192k"]
            audio_strategy = f"audio {acodec} -> AAC 192k"

    return map_args, codec_args, video_strategy, audio_strategy


def duration_seconds(info: dict) -> float:
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and s.get("duration"):
            try:
                return float(s["duration"])
            except (TypeError, ValueError):
                pass
    fmt = info.get("format", {})
    try:
        return float(fmt.get("duration", 0))
    except (TypeError, ValueError):
        return 0.0


def probe_full(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def build_ffmpeg_cmd(
    src: Path, dst: Path, map_args: list[str], codec_args: list[str]
) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-y",
        "-i", str(src),
        *map_args,
        "-map_metadata", "0",
        "-movflags", "+faststart",
        *codec_args,
        "-progress", "pipe:1",
        str(dst),
    ]


def convert(src: Path, dst_dir: Path | None = None) -> None:
    out_dir = dst_dir if dst_dir else src.parent
    dst = out_dir / (src.stem + ".mp4")
    if dst.exists() and dst.resolve() != src.resolve():
        print(f"  [SKIP] ya existe: {dst}")
        return

    info = probe_full(src)
    map_args, codec_args, vstrat, astrat = build_args(info["streams"])

    print(f"  {vstrat}")
    print(f"  {astrat}")

    cmd = build_ffmpeg_cmd(src, dst, map_args, codec_args)
    # quitar -progress para modo CLI simple
    cmd = [c for c in cmd if c != "pipe:1"]
    cmd = [c for c in cmd if c != "-progress"]
    cmd = [c if c != "-nostats" else "-stats" for c in cmd]

    subprocess.run(cmd, check=True)

    src_size = src.stat().st_size
    dst_size = dst.stat().st_size
    ratio = (1 - dst_size / src_size) * 100
    print(
        f"  {human_size(src_size)} -> {human_size(dst_size)} "
        f"({ratio:+.1f}%)\n"
    )


def collect_inputs(args: list[str]) -> list[Path]:
    files: list[Path] = []
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.mov")))
            files.extend(sorted(p.rglob("*.MOV")))
        elif p.is_file() and p.suffix.lower() == ".mov":
            files.append(p)
        else:
            print(f"  [SKIP] no es .mov ni carpeta: {p}")
    # dedupe preservando orden
    seen = set()
    unique = []
    for f in files:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def main() -> None:
    check_ffmpeg()

    if len(sys.argv) < 2:
        sys.exit(__doc__)

    files = collect_inputs(sys.argv[1:])
    if not files:
        sys.exit("No se encontraron archivos .mov.")

    print(f"Procesando {len(files)} archivo(s)...\n")
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}")
        try:
            convert(f)
        except subprocess.CalledProcessError as e:
            print(f"  ERROR en {f.name}: ffmpeg exit {e.returncode}\n")


if __name__ == "__main__":
    main()
