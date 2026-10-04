"""Download variants for rendered videos; the original render stays intact."""

import subprocess
from pathlib import Path
from uuid import uuid4

from server.audio.ffmpeg_utils import find_ffmpeg


def export_video(source: Path, quality: str, video_format: str) -> Path:
    if quality == "original" and video_format == "mp4":
        return source
    stamp = source.stat()
    destination = source.with_name(f"export-{stamp.st_mtime_ns}-{stamp.st_size}-{quality}.{video_format}")
    if destination.is_file():
        return destination
    temporary = destination.with_name(f"{destination.stem}-{uuid4().hex}.tmp.{video_format}")
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
               "-map", "0:v:0", "-map", "0:a?"]
    if quality != "original":
        edge = int(quality[:-1])
        command += ["-vf", f"scale=w='if(gte(iw,ih),-2,{edge})':h='if(gte(iw,ih),{edge},-2)'"]
    if video_format == "webm":
        command += ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-cpu-used", "4",
                    "-c:a", "libopus", "-b:a", "128k"]
    else:
        command += ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    try:
        subprocess.run(command + [str(temporary)], capture_output=True, check=True, timeout=600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
