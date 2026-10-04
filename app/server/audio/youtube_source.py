"""Single public YouTube audio source; shared with the bundled Colab worker."""
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

MAX_BYTES = 512 * 1024**2
MAX_SECONDS = 3 * 60 * 60
DOWNLOAD_TIMEOUT = 600
DOWNLOAD_ERROR = "Không tải được audio YouTube công khai. Video có thể yêu cầu đăng nhập, bị giới hạn hoặc Colab bị chặn; hãy upload media bạn có quyền sử dụng."


def canonical_youtube_url(value):
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port is not None
                or parsed.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
                or "list" in parse_qs(parsed.query, keep_blank_values=True)):
            raise ValueError
        if parsed.hostname == "youtu.be":
            video_id = parsed.path.removeprefix("/")
        elif parsed.path == "/watch":
            ids = parse_qs(parsed.query).get("v", [])
            video_id = ids[0] if len(ids) == 1 else ""
        else:
            match = re.fullmatch(r"/(?:shorts|embed)/([a-zA-Z0-9_-]{11})", parsed.path)
            video_id = match[1] if match else ""
        if not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Chỉ dùng HTTPS URL của một video YouTube; không dùng playlist hoặc URL khác.") from exc
    return "https://www.youtube.com/watch?v=" + video_id


def fetch_audio(url, output_dir, cancel_path):
    """Run in a timeout-bounded child; do not read cookies/config or invoke shell commands."""
    import yt_dlp
    url = canonical_youtube_url(url)
    output_dir = Path(output_dir)

    def bounded(info, *, incomplete=False):
        if incomplete:
            return None
        duration = info.get("duration")
        if (info.get("id") != url.rsplit("=", 1)[1] or info.get("is_live")
                or info.get("live_status") in ("is_live", "is_upcoming")
                or not isinstance(duration, (int, float)) or not math.isfinite(duration)
                or not 0 < duration <= MAX_SECONDS):
            return "YouTube: chỉ nhận video có thời lượng hợp lệ, tối đa 3 giờ, không phải livestream."
        if (info.get("filesize") or info.get("filesize_approx") or 0) > MAX_BYTES:
            return "Audio YouTube vượt 512 MiB."
        return None

    def progress(info):
        if Path(cancel_path).exists():
            raise RuntimeError("Đã hủy tải YouTube.")
        # Check actual fragments as well as reported bytes when a server omits Content-Length.
        if (info.get("downloaded_bytes", 0) > MAX_BYTES
                or sum(path.stat().st_size for path in output_dir.iterdir() if path.is_file()) > MAX_BYTES):
            raise RuntimeError("Audio YouTube vượt 512 MiB.")

    options = {"format": "bestaudio[protocol=https]/bestaudio[protocol=http]", "outtmpl": str(output_dir / "audio.%(ext)s"), "noplaylist": True,
               "allowed_extractors": ["youtube"], "max_filesize": MAX_BYTES, "match_filter": bounded,
               "progress_hooks": [progress], "socket_timeout": 20, "retries": 2, "fragment_retries": 2,
               "cachedir": False, "quiet": True, "no_warnings": True, "overwrites": False}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if info is None or bounded(info):
                raise RuntimeError("YouTube không trả về một audio hợp lệ trong giới hạn.")
            source = Path(downloader.prepare_filename(info))
        if (source.parent != output_dir or not source.is_file() or not 0 < source.stat().st_size <= MAX_BYTES
                or source.suffix.lower() not in (".m4a", ".webm", ".opus", ".ogg", ".mp3", ".aac", ".wav", ".flac")):
            raise RuntimeError("Không có file audio YouTube hợp lệ, tối đa 512 MiB.")
        return {"file": source.name, "source_url": url, "video_id": info["id"],
                "title": str(info.get("title", ""))[:500], "duration": info["duration"],
                "extractor": "youtube", "download_bytes": source.stat().st_size}
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(DOWNLOAD_ERROR) from exc


if __name__ == "__main__" and len(sys.argv) == 4:
    try:
        result = fetch_audio(*sys.argv[1:])
        (Path(sys.argv[2]) / "receipt.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else DOWNLOAD_ERROR
        (Path(sys.argv[2]) / "error.json").write_text(json.dumps({"error": message}, ensure_ascii=False), encoding="utf-8")
        sys.exit(1)
