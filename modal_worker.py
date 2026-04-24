"""
Modal worker: recibe un .mov como bytes, convierte a .mp4, devuelve bytes.
Deploy: python -m modal deploy modal_worker.py
"""

import modal

app = modal.App("mov-to-mp4-converter")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
)

HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}

HDR_TONEMAP_FILTER = (
    "zscale=t=linear:npl=203,"
    "format=gbrpf32le,"
    "zscale=p=bt709,"
    "tonemap=tonemap=mobius:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,"
    "format=yuv420p"
)

SDR_COLOR_TAGS = [
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-colorspace", "bt709",
    "-color_range", "tv",
]

H264_BASE_ARGS = [
    "-c:v", "libx264",
    "-crf", "23",
    "-preset", "slow",
    "-profile:v", "high",
    "-level:v", "4.1",
]


def _build_cmd(src: str, dst: str, streams: list[dict]) -> list[str]:
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)

    map_args: list[str] = []
    codec_args: list[str] = []

    if video:
        map_args += ["-map", f"0:{video['index']}"]
        color_trc = video.get("color_transfer", "").lower()
        codec_args += list(H264_BASE_ARGS)
        if color_trc in HDR_TRANSFERS:
            codec_args += ["-vf", HDR_TONEMAP_FILTER]
        else:
            codec_args += ["-pix_fmt", "yuv420p"]
        codec_args += SDR_COLOR_TAGS

    if audio:
        map_args += ["-map", f"0:{audio['index']}"]
        if audio.get("codec_name", "").lower() == "aac":
            codec_args += ["-c:a", "copy"]
        else:
            codec_args += ["-c:a", "aac", "-b:a", "192k"]

    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", src,
        *map_args,
        "-map_metadata", "0",
        "-movflags", "+faststart",
        *codec_args,
        dst,
    ]


@app.function(
    image=image,
    cpu=4,
    timeout=3600,
)
def convert(video_bytes: bytes, filename: str) -> tuple[bytes, dict]:
    import json
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        src = str(Path(tmp) / filename)
        dst = str(Path(tmp) / (Path(filename).stem + ".mp4"))

        Path(src).write_bytes(video_bytes)

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", src,
            ],
            capture_output=True, text=True, check=True,
        )
        info = json.loads(probe.stdout)
        streams = info.get("streams", [])

        cmd = _build_cmd(src, dst, streams)
        subprocess.run(cmd, check=True)

        src_size = Path(src).stat().st_size
        dst_size = Path(dst).stat().st_size
        stats = {
            "src_size": src_size,
            "dst_size": dst_size,
            "ratio": round((1 - dst_size / src_size) * 100, 1),
        }
        return Path(dst).read_bytes(), stats
