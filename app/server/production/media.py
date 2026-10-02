import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def probe(path: Path) -> dict:
    binary = shutil.which("ffprobe")
    if not binary:
        raise ValueError("Cần cài FFmpeg/ffprobe và thêm vào PATH.")
    result = subprocess.run([binary, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError("Không đọc được media; file hỏng hoặc định dạng không hỗ trợ.")
    info = json.loads(result.stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0 or duration > 3600:
        raise ValueError("Thời lượng media phải trong khoảng 0–3600 giây.")
    return {"duration": duration, "streams": info["streams"]}


def image_info(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        if image.width * image.height > 40_000_000 or min(image.size) < 32:
            raise ValueError("Ảnh phải có cạnh từ 32px, tối đa 40 megapixel.")
        image.verify()
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).size


def ffmpeg(arguments: list[str], timeout: int = 300) -> None:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise ValueError("Cần cài FFmpeg và thêm vào PATH.")
    result = subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-y", *arguments],
                            capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError("FFmpeg không xử lý được media; kiểm tra file nguồn và dung lượng đĩa.")


def contained(root: Path, value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("File không tồn tại trong storage của AIFlow.")
    return path


def srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def align_narration(scenes, folder: Path):
    """Pad each scene's audio independently so later narration never shifts into silent gaps."""
    folder.mkdir(parents=True, exist_ok=True)
    subtitles, cursor = [], 0.0
    for index, scene in enumerate(scenes):
        audio = Path(scene.audio_path) if scene.audio_path else None
        speech_duration = probe(audio)["duration"] if audio and audio.is_file() else 0
        if scene.narration.strip() and not speech_duration:
            raise ValueError(f"Missing narration audio for scene {scene.order + 1}")
        scene.duration = max(float(scene.duration), speech_duration)
        args = ["-i", str(audio)] if speech_duration else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        ffmpeg(args + ["-af", "apad", "-t", str(scene.duration), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(folder / f"audio-{index:03}.wav")])
        if speech_duration and scene.narration.strip():
            subtitles.append({"text": scene.narration.replace("\n", " "), "start_sec": cursor, "end_sec": cursor + speech_duration})
        cursor += scene.duration
    listing = folder / "audio-concat.txt"
    listing.write_text("\n".join(f"file 'audio-{index:03}.wav'" for index in range(len(scenes))), encoding="utf-8")
    destination = folder / "narration.wav"
    ffmpeg(["-f", "concat", "-safe", "1", "-i", str(listing), "-c", "copy", str(destination)])
    (folder / "subtitle.srt").write_text("\n".join(f"{i+1}\n{srt_timestamp(s['start_sec'])} --> {srt_timestamp(s['end_sec'])}\n{s['text']}\n" for i, s in enumerate(subtitles)), encoding="utf-8")
    return destination, subtitles
