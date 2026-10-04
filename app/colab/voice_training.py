"""Colab-only selected-R2 dataset, reviewed LoRA training, and saved voice serving."""

import gc
import hashlib
import json
import math
import os
import re
import runpy
import shutil
import subprocess
import sys
import unicodedata
import uuid
from pathlib import Path

UPSTREAM_COMMIT = "c1390abbdb2eedcdf58eafb546966c06ce27af71"
UPSTREAM = Path("/content/VieNeu-TTS")
ROOT = Path("/content/drive/MyDrive/AIFlow/voice-training")
BASE_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
BASE_PATTERNS = ["update/*", "onnx_update/*", "config.json", "speaker_encoder.onnx", "denoiser.onnx", "voices_v3_turbo.json"]
MEDIA_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus", ".mp4", ".mov", ".mkv", ".webm"}
UPLOAD_CHUNK_BYTES = 8 * 1024**2
ASR_CHUNK_SECONDS = 600
RECOVERY_REPO = "Systran/faster-whisper-large-v3"
RECOVERY_POLICY = {"version": 2, "mode": "original_clip", "compute_type": "float16",
                   "decode": {"vad_filter": False, "word_timestamps": False, "condition_on_previous_text": False,
                              "beam_size": 5, "temperature": 0.0, "no_speech_threshold": None,
                              "log_prob_threshold": None, "compression_ratio_threshold": None}}
INFERENCE_POLICY = {"version": "v3turbo-chronological-v1", "max_chars": 256,
                    "batch_size": 1, "chunk_order": "text", "seed_scope": "request"}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)

def onnx_cli(script, args):
    """Pinned upstream ONNX CLIs need an explicit graph directory for a local snapshot."""
    if script not in ("prepare_dataset.py", "make_voice.py"):
        raise ValueError("Không có CLI ONNX này.")
    import vieneu
    original_factory, original_argv = vieneu.Vieneu, sys.argv
    def local_factory(*factory_args, **kwargs):
        base = Path(kwargs.get("backbone_repo", ""))
        if kwargs.get("backend") == "onnx" and base.is_dir() and not kwargs.get("onnx_dir"):
            kwargs["onnx_dir"] = str(base / "onnx_update")
        return original_factory(*factory_args, **kwargs)
    try:
        vieneu.Vieneu = local_factory
        sys.argv = [str(UPSTREAM / "finetune" / script), *args]
        runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        vieneu.Vieneu, sys.argv = original_factory, original_argv


def gpu():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("Chọn GPU runtime trước khi chạy bước này.")
    return torch


def probe_media(path):
    """Read bounded metadata; FFmpeg decodes the media later, never Python whole-file PCM."""
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                             "stream=duration,sample_rate,channels:format=duration", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=60)
    metadata = json.loads(result.stdout)
    audio = metadata.get("streams", [])
    if not audio:
        raise ValueError("File không có stream âm thanh.")
    duration_value = audio[0].get("duration")
    if duration_value in (None, "N/A"):
        duration_value = metadata.get("format", {}).get("duration", 0)
    duration = float(duration_value)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Không xác định được thời lượng âm thanh hợp lệ.")
    return {"duration": duration, "sample_rate": int(audio[0]["sample_rate"]), "channels": int(audio[0]["channels"])}


def normalize_audio(source, output, start, duration):
    run("ffmpeg", "-v", "error", "-y", "-ss", start, "-i", source, "-t", duration,
        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", output)

def signal_metrics(path):
    """PCM signal checks describe the clip; they do not establish speaker identity or listening."""
    import wave
    from array import array
    with wave.open(str(path), "rb") as audio:
        samples = array("h", audio.readframes(audio.getnframes()))
    if not samples:
        raise ValueError("Đoạn WAV không có mẫu âm thanh.")
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
    peak = max(abs(sample) for sample in samples) / 32768
    return {"rms_dbfs": round(20 * math.log10(max(rms, 1e-6)), 3),
            "peak_dbfs": round(20 * math.log10(max(peak, 1e-6)), 3),
            "clipped_fraction": sum(abs(sample) >= 32760 for sample in samples) / len(samples),
            "near_silence_fraction": sum(abs(sample) < 164 for sample in samples) / len(samples)}


def open_selection(path):
    manifest = read_json(path)
    if (manifest.get("schema_version") != 1 or manifest.get("mode") != "finetune"
            or not manifest.get("same_speaker_confirmed")
            or not re.fullmatch(r"[a-f0-9]{32}", manifest.get("job_id", ""))
            or manifest.get("language") not in ("vi", "en")):
        raise ValueError("Gói lựa chọn không hợp lệ. Tạo lại từ AIFlow.")
    source_type = manifest.get("source_type", "r2")
    if source_type not in ("r2", "local", "youtube"):
        raise ValueError("Nguồn dữ liệu không hợp lệ.")
    if source_type == "r2" and not re.fullmatch(r"https://[a-fA-F0-9]{32}(?:\.(?:eu|fedramp))?\.r2\.cloudflarestorage\.com", manifest["endpoint"]):
        raise ValueError("Endpoint không phải R2.")
    files = manifest["files"]
    if not 1 <= len(files) <= 5000 or len({f["id"] for f in files}) != len(files):
        raise ValueError("Danh sách file trống, trùng hoặc quá lớn.")
    for file in files:
        if source_type == "youtube":
            from youtube_source import canonical_youtube_url
            url = canonical_youtube_url(manifest.get("source_url", ""))
            if len(files) != 1 or file["key"] != url or manifest["source_url"] != url or file["size"] != 0:
                raise ValueError("Lựa chọn YouTube phải chứa đúng một URL video chuẩn hóa.")
        if file["id"] != hashlib.sha256(file["key"].encode()).hexdigest() or (source_type != "youtube" and not 0 < file["size"] <= 2 * 1024**3):
            raise ValueError("File trong manifest không hợp lệ.")
        if source_type == "local":
            if (Path(file["key"]).name != file["key"] or "\\" in file["key"]
                    or Path(file["key"]).suffix.lower() not in MEDIA_EXTENSIONS):
                raise ValueError("Tên/định dạng media local không hợp lệ.")
            if manifest.get("upload_protocol") != "chunks-v1" and (Path(file["key"]).suffix.lower() != ".wav"
                    or file["size"] > 32 * 1024**2 or not re.fullmatch(r"[a-f0-9]{64}", file.get("sha256", ""))):
                raise ValueError("WAV local/checksum không hợp lệ.")
    if sum(f["size"] for f in files) > 20 * 1024**3:
        raise ValueError("Bộ dữ liệu vượt 20 GiB.")
    job = ROOT / manifest["job_id"]
    existing = job / "selection.json"
    if existing.exists() and read_json(existing) != manifest:
        raise ValueError("Job ID đã có manifest khác. Tạo một lựa chọn mới.")
    write_json(existing, manifest)
    print(f"Giọng: {manifest['voice_name']} | {len(files)} file. Chưa tải media.")
    return job


def download_selected(job):
    manifest = read_json(job / "selection.json")
    if manifest.get("source_type") == "youtube":
        return download_youtube(job)
    if manifest.get("source_type") == "local":
        raise RuntimeError("Dữ liệu local được upload từ AIFlow. Gửi lại cùng lựa chọn nếu còn thiếu file.")
    import boto3
    from botocore.config import Config
    def secret(name):
        if os.environ.get(name):
            return os.environ[name]
        from google.colab import userdata
        return userdata.get(name)
    client = boto3.client("s3", endpoint_url=manifest["endpoint"], region_name="auto",
                          aws_access_key_id=secret("R2_ACCESS_KEY_ID"),
                          aws_secret_access_key=secret("R2_SECRET_ACCESS_KEY"),
                          config=Config(signature_version="s3v4", connect_timeout=15, read_timeout=60,
                                        retries={"max_attempts": 3}, s3={"addressing_style": "path"}))
    raw = job / "source"
    raw.mkdir(exist_ok=True)
    receipts = read_json(job / "downloads.json") if (job / "downloads.json").exists() else {}
    try:
        for index, file in enumerate(manifest["files"], 1):
            if (job / "cancel.request").exists():
                raise RuntimeError("Đã dừng tải giữa các file; có thể chạy tiếp.")
            target = raw / (file["id"] + Path(file["key"]).suffix.lower())
            old = receipts.get(file["id"])
            if old and target.exists() and target.stat().st_size == file["size"] and sha256(target) == old["sha256"]:
                print(f"{index}/{len(manifest['files'])}: dùng bản đã tải đúng checksum")
                continue
            head = client.head_object(Bucket=manifest["bucket"], Key=file["key"])
            if head["ETag"] != file["etag"] or head["ContentLength"] != file["size"] or head["LastModified"].isoformat() != file["modified"]:
                raise RuntimeError("File R2 đã thay đổi sau lúc quét. Quay lại AIFlow để quét và chọn lại.")
            if shutil.disk_usage(raw).free < file["size"] + 1024**3:
                raise RuntimeError("Drive không đủ dung lượng tải file tiếp theo.")
            response = client.get_object(Bucket=manifest["bucket"], Key=file["key"], IfMatch=file["etag"])
            part = target.with_suffix(".part")
            try:
                total = 0
                with part.open("wb") as output:
                    for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                        total += len(chunk)
                        if total > file["size"]:
                            raise RuntimeError("Kích thước object khác manifest.")
                        output.write(chunk)
                if total != file["size"]:
                    raise RuntimeError("Tải chưa đủ dữ liệu. Chạy lại ô tải.")
                part.replace(target)
            finally:
                response["Body"].close()
                part.unlink(missing_ok=True)
            receipts[file["id"]] = {"sha256": sha256(target), "file": target.name}
            write_json(job / "downloads.json", receipts)
            print(f"Đã tải {index}/{len(manifest['files'])}")
    finally:
        client.close()
    return receipts


def download_youtube(job):
    import tempfile
    import youtube_source
    manifest = read_json(job / "selection.json")
    url = youtube_source.canonical_youtube_url(manifest["source_url"])
    file_id = manifest["files"][0]["id"]
    raw = job / "source"
    raw.mkdir(exist_ok=True)
    receipt_path = job / "downloads.json"
    receipts = read_json(receipt_path) if receipt_path.exists() else {}
    old = receipts.get(file_id)
    if old and Path(old["file"]).name == old["file"]:
        source = raw / old["file"]
        if (source.is_file() and source.stat().st_size == old["download_bytes"]
                and old.get("source_url") == url and sha256(source) == old["sha256"]):
            print("Dùng audio YouTube đã tải đúng checksum.")
            return receipts
    if (job / "cancel.request").exists():
        raise RuntimeError("Đã hủy tải YouTube.")
    with tempfile.TemporaryDirectory(prefix="aiflow-youtube-") as scratch:
        scratch = Path(scratch)
        if min(shutil.disk_usage(raw).free, shutil.disk_usage(scratch).free) < youtube_source.MAX_BYTES + 1024**3:
            raise RuntimeError("Không đủ dung lượng lưu audio YouTube.")
        try:
            subprocess.run([sys.executable, "-u", youtube_source.__file__, url, str(scratch), str(job / "cancel.request")],
                           check=True, timeout=youtube_source.DOWNLOAD_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Tải YouTube vượt 10 phút. Hãy thử lại hoặc upload media có sẵn.") from exc
        except subprocess.CalledProcessError as exc:
            error = scratch / "error.json"
            raise RuntimeError(read_json(error)["error"] if error.exists() else youtube_source.DOWNLOAD_ERROR) from exc
        receipt = read_json(scratch / "receipt.json")
        source = scratch / receipt["file"]
        try:
            media = probe_media(source)
        except (ValueError, KeyError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Không xác minh được stream audio YouTube. Hãy thử lại hoặc upload media có sẵn.") from exc
        if media["duration"] > youtube_source.MAX_SECONDS:
            raise RuntimeError("Audio YouTube vượt thời lượng 3 giờ.")
        if (job / "cancel.request").exists():
            raise RuntimeError("Đã hủy tải YouTube.")
        target = raw / (file_id + source.suffix.lower())
        part = target.with_suffix(target.suffix + ".part")
        try:
            shutil.copyfile(source, part)
            receipt.update(file=target.name, sha256=sha256(part), media=media)
            part.replace(target)
            receipts[file_id] = receipt
            write_json(receipt_path, receipts)
        finally:
            part.unlink(missing_ok=True)
    print("Đã lưu audio YouTube/checksum trên Drive. Chưa tách đoạn hoặc duyệt dataset.")
    return receipts


def prepare_audio_chunk(model, normalized, clips, file, source_checksum, chunk_index, chunk_start, chunk_duration, has_next, language):
    segments, info = model.transcribe(str(normalized), language=language, vad_filter=True,
                                     word_timestamps=True, condition_on_previous_text=False)
    rows, skipped, boundaries = [], 0, []
    for segment in segments:
        groups, current = [], []
        for word in list(segment.words or []):
            if current and word.end - current[0].start > 15:
                groups.append(current)
                current = []
            current.append(word)
        if current:
            groups.append(current)
        for group in groups:
            text = "".join(word.word for word in group).strip()
            # No overlap: reject words near artificial cuts rather than duplicate or guess them.
            if ((chunk_start > 0 and group[0].start < 1) or (has_next and group[-1].end > chunk_duration - 1)
                    or group[-1].end > chunk_duration + 0.01):
                skipped += 1
                boundaries.append({"source": file["key"], "start": chunk_start + group[0].start,
                                   "text": text, "reason": "artificial_chunk_boundary"})
                continue
            start = max(0, group[0].start - 0.08)
            duration = min(chunk_duration, group[-1].end + 0.08) - start
            if not 1 <= duration <= 20 or not text:
                skipped += 1
                continue
            name = f"{file['id'][:20]}_c{chunk_index:05d}_{len(rows)+1:05d}.wav"
            run("ffmpeg", "-v", "error", "-y", "-ss", start, "-i", normalized, "-t", duration,
                "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", clips / name)
            def metric(value):
                return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None
            probabilities = [value for word in group if (value := metric(getattr(word, "probability", None))) is not None]
            asr = {"avg_logprob": metric(getattr(segment, "avg_logprob", None)),
                   "no_speech_prob": metric(getattr(segment, "no_speech_prob", None)),
                   "compression_ratio": metric(getattr(segment, "compression_ratio", None)),
                   "mean_word_probability": sum(probabilities) / len(probabilities) if probabilities else None,
                   "language_probability": metric(getattr(info, "language_probability", None))}
            rows.append({"file": name, "text": text, "duration": duration, "source": file["key"],
                         "source_sha256": source_checksum, "start": chunk_start + start, "chunk_start": chunk_start,
                         "include": True, "reviewed": False, "review_method": "manual_listening", "asr": asr,
                         "signal": signal_metrics(clips / name), "sha256": sha256(clips / name)})
    return rows, skipped, boundaries


def prepare_clips(job):
    """Normalize/ASR bounded chunks on Colab; preserve edits and source provenance."""
    import tempfile
    torch = gpu()
    from faster_whisper import WhisperModel
    from huggingface_hub import HfApi, snapshot_download
    manifest = read_json(job / "selection.json")
    receipts = read_json(job / "downloads.json")
    review_path = job / "review.json"
    if review_path.exists():
        print("Dataset đã có: mở trình duyệt dataset để sửa/duyệt; không ghi đè bản sửa.")
        return
    pin = job / "asr-revision.json"
    if not pin.exists():
        write_json(pin, {"repo": RECOVERY_REPO, "revision": HfApi().model_info(RECOVERY_REPO).sha,
                         "compute_type": "float16"})
    pinned = read_json(pin)
    model_repo = pinned.get("repo", "Systran/faster-whisper-small")
    legacy_config = {"format": 1, "asr_revision": pinned["revision"], "language": manifest["language"]}
    if model_repo != "Systran/faster-whisper-small":
        legacy_config["asr_repo"] = model_repo
    if "compute_type" in pinned:
        legacy_config["compute_type"] = pinned["compute_type"]
    checkpoint_config = {**legacy_config, "format": 2, "chunk_seconds": ASR_CHUNK_SECONDS,
                         "normalization": "mono-24000-pcm_s16le", "boundary_guard_seconds": 1}
    checkpoint_dir = job / "prepare-checkpoints"
    model_path = snapshot_download(model_repo, revision=read_json(pin)["revision"], cache_dir=str(ROOT / "model-cache"))
    model = WhisperModel(model_path, device="cuda", compute_type=pinned.get("compute_type", "int8_float16"))
    clips = job / "dataset" / "raw_audio"
    clips.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], 0
    try:
        for file in manifest["files"]:
            if (job / "cancel.request").exists():
                raise RuntimeError("Đã dừng chuẩn bị giữa các chunk/file; chạy lại để tiếp tục checkpoint.")
            receipt = receipts.get(file["id"])
            if not receipt or Path(receipt["file"]).name != receipt["file"]:
                raise RuntimeError("Chưa tải đủ file đã chọn. Chạy ô tải trước.")
            source = job / "source" / receipt["file"]
            if sha256(source) != receipt["sha256"]:
                raise RuntimeError("File nguồn trên Drive đã đổi. Chạy lại ô tải.")
            legacy_path = checkpoint_dir / f"{file['id']}.json"
            if legacy_path.exists():
                if legacy_path.stat().st_size > 2 * 1024**2:
                    raise RuntimeError("Checkpoint file vượt giới hạn 2 MiB.")
                checkpoint = read_json(legacy_path)
                if checkpoint["config"] != legacy_config or checkpoint["source_sha256"] != receipt["sha256"]:
                    raise RuntimeError("Nguồn hoặc ASR đã đổi; tạo lựa chọn mới để không trộn dataset.")
                if all((clips / row["file"]).is_file() and sha256(clips / row["file"]) == row["sha256"] for row in checkpoint["rows"]):
                    rows.extend(checkpoint["rows"])
                    skipped += checkpoint["skipped"]
                    print(f"Dùng checkpoint file đã xác minh: {file['key']}")
                    continue
            media = probe_media(source)
            chunk_count = math.ceil(media["duration"] / ASR_CHUNK_SECONDS)
            for chunk_index in range(chunk_count):
                if (job / "cancel.request").exists():
                    raise RuntimeError("Đã dừng giữa các chunk; checkpoint giữ nguyên để tiếp tục.")
                chunk_start = chunk_index * ASR_CHUNK_SECONDS
                chunk_duration = min(ASR_CHUNK_SECONDS, media["duration"] - chunk_start)
                checkpoint_path = checkpoint_dir / f"{file['id']}_c{chunk_index:05d}.json"
                if checkpoint_path.exists():
                    if checkpoint_path.stat().st_size > 2 * 1024**2:
                        raise RuntimeError("Checkpoint chunk vượt giới hạn 2 MiB.")
                    checkpoint = read_json(checkpoint_path)
                    if checkpoint["config"] != checkpoint_config or checkpoint["source_sha256"] != receipt["sha256"]:
                        raise RuntimeError("Nguồn, ASR hoặc chuẩn hóa đã đổi; tạo lựa chọn mới để không trộn dataset.")
                    if all((clips / row["file"]).is_file() and sha256(clips / row["file"]) == row["sha256"] for row in checkpoint["rows"]):
                        rows.extend(checkpoint["rows"])
                        skipped += checkpoint["skipped"]
                        print(f"Dùng checkpoint: {file['key']} chunk {chunk_index+1}/{chunk_count}")
                        continue
                # Runtime-local scratch is at most ten minutes PCM, independent of source length.
                with tempfile.TemporaryDirectory(prefix="aiflow-normalized-") as scratch:
                    normalized = Path(scratch) / f"{file['id']}_normalized.wav"
                    normalize_audio(source, normalized, chunk_start, chunk_duration)
                    file_rows, file_skipped, boundaries = prepare_audio_chunk(
                        model, normalized, clips, file, receipt["sha256"], chunk_index, chunk_start, chunk_duration,
                        chunk_index + 1 < chunk_count, manifest["language"])
                checkpoint = {"config": checkpoint_config, "source_sha256": receipt["sha256"],
                              "chunk_start": chunk_start, "rows": file_rows, "skipped": file_skipped,
                              "boundary_rejected": boundaries}
                if len(json.dumps(checkpoint, ensure_ascii=False, indent=2).encode("utf-8")) > 2 * 1024**2:
                    raise RuntimeError("Checkpoint chunk vượt giới hạn 2 MiB.")
                write_json(checkpoint_path, checkpoint)
                rows.extend(file_rows)
                skipped += file_skipped
                print(f"Đã tách {len(file_rows)} đoạn: {file['key']} chunk {chunk_index+1}/{chunk_count}; loại sát biên={len(boundaries)}")
                if (job / "cancel.request").exists():
                    raise RuntimeError("Đã dừng sau chunk đã lưu checkpoint; chạy lại để tiếp tục.")
        if not rows:
            raise RuntimeError("Không có đoạn hợp lệ. Kiểm tra file có giọng rõ và đúng ngôn ngữ.")
        write_json(review_path, rows)
        print(f"{len(rows)} đoạn, {sum(row['duration'] for row in rows)/60:.1f} phút; bỏ {skipped} đoạn ngoài 1–20 giây/sát biên. Chưa duyệt.")
    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()


def verification_inputs(job):
    path = job / "review.json"
    if not path.is_file():
        raise RuntimeError("Chuẩn bị dataset trước khi đối chiếu transcript.")
    rows = read_json(path)
    selected = [row for row in rows if row.get("include")]
    if not selected:
        raise RuntimeError("Chọn ít nhất một đoạn để đối chiếu transcript.")
    for row in selected:
        name = row["file"]
        clip = job / "dataset" / "raw_audio" / name
        if Path(name).name != name or not name.endswith(".wav") or not clip.is_file() or sha256(clip) != row.get("sha256"):
            raise RuntimeError("Clip đã đổi hoặc thiếu; kiểm tra dataset trước khi đối chiếu.")
    return rows, selected


def verify_transcripts(job):
    rows, selected = verification_inputs(job)
    if (job / "cancel.request").exists():
        raise RuntimeError("Đã dừng đối chiếu transcript.")
    torch = gpu()
    from faster_whisper import WhisperModel
    from huggingface_hub import HfApi, snapshot_download
    repo = "Systran/faster-whisper-large-v3"
    pin = job / "verification-revision.json"
    if not pin.exists():
        write_json(pin, {"repo": repo, "revision": HfApi().model_info(repo).sha})
    revision = read_json(pin)["revision"]
    model_path = snapshot_download(repo, revision=revision, cache_dir=str(ROOT / "model-cache"))
    model = WhisperModel(model_path, device="cuda", compute_type="int8_float16")
    manifest = read_json(job / "selection.json")
    try:
        for index, row in enumerate(selected, 1):
            if (job / "cancel.request").exists():
                raise RuntimeError("Đã dừng giữa các clip; chạy lại để tiếp tục đối chiếu.")
            previous = row.get("verification", {})
            if previous.get("repo") == repo and previous.get("revision") == revision and previous.get("clip_sha256") == row["sha256"]:
                continue
            clip = job / "dataset" / "raw_audio" / row["file"]
            segments, info = model.transcribe(str(clip), language=manifest["language"], vad_filter=True,
                                             word_timestamps=True, condition_on_previous_text=False)
            segments = list(segments)
            def values(name, items):
                return [float(value) for item in items if isinstance(value := getattr(item, name, None), (int, float)) and math.isfinite(value)]
            words = [word for segment in segments for word in (segment.words or [])]
            metrics = {}
            for name in ("avg_logprob", "no_speech_prob", "compression_ratio"):
                data = values(name, segments)
                metrics[name] = sum(data) / len(data) if data else None
            probabilities = values("probability", words)
            metrics["mean_word_probability"] = sum(probabilities) / len(probabilities) if probabilities else None
            language = values("language_probability", [info])
            metrics["language_probability"] = language[0] if language else None
            row["verification"] = {"text": " ".join(segment.text.strip() for segment in segments).strip(),
                                   "asr": metrics, "repo": repo, "revision": revision, "clip_sha256": row["sha256"]}
            row["reviewed"] = False
            (job / "dataset-approved.json").unlink(missing_ok=True)
            write_json(job / "review.json", rows)
            print(f"Đã đối chiếu {index}/{len(selected)}: {row['file']}; chưa duyệt, giữ lời gốc.")
    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()


def recovery_identity(row, language):
    return {"clip_sha256": row.get("sha256"), "source_sha256": row.get("source_sha256"),
            "source": row.get("source"), "original_text": row.get("text", ""),
            "start": row.get("start"), "duration": row.get("duration"), "language": language,
            "policy": RECOVERY_POLICY}


def valid_recovery_row(row):
    name, start, duration = row.get("file", ""), row.get("start"), row.get("duration")
    return (isinstance(name, str) and Path(name).name == name and "\\" not in name and name.endswith(".wav")
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                    for value in (start, duration)) and start >= 0 and 1 <= duration <= 20
            and all(isinstance(row.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", row[key])
                    for key in ("sha256", "source_sha256")) and isinstance(row.get("source"), str))


def transcript_key(text):
    # Punctuation/case differences are not grounds for rejecting mixed language or numbers.
    return " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", text).casefold()).split())


def review_assessments(job, rows):
    manifest = read_json(job / "selection.json")
    path = job / "recovery-proposals.json"
    proposals = read_json(path).get("rows", {}) if path.exists() else {}
    pin = job / "recovery-revision.json"
    pinned = read_json(pin) if pin.exists() else {}
    revision = pinned.get("revision") if pinned.get("repo") == RECOVERY_REPO else None
    result = []
    summary = {"total_count": len(rows), "included_count": 0, "excluded_count": 0, "reviewed_count": 0,
               "total_seconds": 0, "included_seconds": 0, "excluded_seconds": 0, "reviewed_seconds": 0,
               "recoverable_count": 0, "status_counts": dict.fromkeys(
                   ("ready", "needs_review", "transcript_disagreement", "acoustic_issue"), 0)}
    for row in rows:
        candidate, candidate_source, complete = None, None, True
        proposal = proposals.get(row.get("file"), {})
        if (revision and proposal.get("repo") == RECOVERY_REPO and proposal.get("revision") == revision
                and proposal.get("identity") == recovery_identity(row, manifest.get("language"))):
            candidate, candidate_source = proposal.get("text", ""), "clip_large_v3"
            complete = proposal.get("complete", False)
        else:
            verification = row.get("verification", {})
            if (verification.get("repo") == RECOVERY_REPO and verification.get("clip_sha256") == row.get("sha256")
                    and verification.get("text")):
                candidate, candidate_source = verification["text"], "clip_large_v3"
        reasons = []
        duration = row.get("duration", 0)
        valid_duration = isinstance(duration, (int, float)) and math.isfinite(duration) and 1 <= duration <= 20
        signal = row.get("signal", {})
        acoustic = False
        if not valid_duration:
            reasons.append("Thời lượng ngoài khoảng 1–20 giây hoặc không hợp lệ.")
            acoustic = True
        start, name = row.get("start"), row.get("file", "")
        if (not isinstance(name, str) or Path(name).name != name or "\\" in name or not name.endswith(".wav")
                or (start is not None and (not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0))):
            reasons.append("Tên clip hoặc mốc thời gian nguồn không hợp lệ.")
            acoustic = True
        for key, limit, label in (("clipped_fraction", 0.05, "Tín hiệu có nhiều mẫu clipping; cần kiểm tra audio."),
                                   ("near_silence_fraction", 0.95, "Tín hiệu gần như im lặng; cần kiểm tra audio.")):
            value = signal.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value) and value >= limit:
                acoustic = True
                reasons.append(label)
        disagreement = candidate is not None and transcript_key(candidate) != transcript_key(row.get("text", ""))
        if disagreement:
            reasons.append("Hai transcript khác nhau; đây là bất đồng ASR, chưa chứng minh audio lỗi.")
        if candidate is not None and not complete:
            reasons.append("Đề xuất có timestamp/nội dung bất thường; giữ toàn bộ lời để kiểm tra audio trước khi áp dụng.")
        if not row.get("include"):
            reasons.append("Đoạn đang bị loại; có thể xem lại và chọn bằng quyết định thủ công.")
        if not row.get("reviewed"):
            reasons.append("Chưa có xác nhận kiểm tra của người dùng.")
        if candidate is None:
            reasons.append("Chưa có transcript đối chiếu hợp lệ.")
        status = ("acoustic_issue" if acoustic else "transcript_disagreement" if disagreement else
                  "needs_review" if not row.get("include") or not row.get("reviewed") or not complete else "ready")
        recoverable = valid_recovery_row(row) and (not row.get("include") or not row.get("reviewed") or disagreement or not complete or acoustic)
        assessment = {"status": status, "reasons": reasons, "candidate_text": candidate,
                      "candidate_source": candidate_source, "candidate_complete": complete if candidate is not None else None,
                      "recoverable": recoverable}
        result.append({**row, "review_assessment": assessment})
        seconds = float(duration) if isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0 else 0
        bucket = "included" if row.get("include") else "excluded"
        summary[f"{bucket}_count"] += 1
        summary[f"{bucket}_seconds"] += seconds
        summary["total_seconds"] += seconds
        if row.get("reviewed"):
            summary["reviewed_count"] += 1
            summary["reviewed_seconds"] += seconds
        summary["recoverable_count"] += int(recoverable)
        summary["status_counts"][status] += 1
    return result, summary


def recovery_inputs(job):
    if not (job / "review.json").is_file():
        raise RuntimeError("Chuẩn bị dataset trước khi khôi phục transcript.")
    rows = read_json(job / "review.json")
    assessed, _ = review_assessments(job, rows)
    selected = [row for row in assessed if row["review_assessment"]["recoverable"]]
    if not selected:
        raise RuntimeError("Không có đoạn hợp lệ cần khôi phục transcript.")
    manifest = read_json(job / "selection.json")
    receipts = read_json(job / "downloads.json")
    files = {file["key"]: file for file in manifest.get("files", [])}
    for row in selected:
        clip = job / "dataset/raw_audio" / row["file"]
        if not clip.is_file() or sha256(clip) != row["sha256"]:
            raise RuntimeError("Clip đã đổi hoặc thiếu; kiểm tra dataset trước khi khôi phục.")
        file = files.get(row["source"])
        receipt = receipts.get(file["id"]) if file else None
        name = receipt.get("file", "") if receipt else ""
        if (not name or Path(name).name != name or "\\" in name
                or receipt.get("sha256") != row["source_sha256"] or not (job / "source" / name).is_file()):
            raise RuntimeError("Nguồn gốc audio không khớp hoặc nguồn chưa tải.")
    return selected


def recover_transcripts(job):
    """Recover full-clip proposals; segment anomalies are advisory and never trim labels."""
    selected = recovery_inputs(job)
    if (job / "cancel.request").exists():
        raise RuntimeError("Đã dừng khôi phục transcript.")
    manifest, receipts = read_json(job / "selection.json"), read_json(job / "downloads.json")
    sources = {}
    for row in selected:
        if row["source"] in sources:
            source, checksum, media = sources[row["source"]]
        else:
            file = next((file for file in manifest["files"] if file["key"] == row["source"]), None)
            receipt = receipts.get(file["id"]) if file else None
            if not receipt or Path(receipt.get("file", "")).name != receipt.get("file") or "\\" in receipt["file"]:
                raise RuntimeError("Thiếu nguồn gốc audio hợp lệ để khôi phục.")
            source = job / "source" / receipt["file"]
            checksum = sha256(source)
            if checksum != receipt.get("sha256"):
                raise RuntimeError("Checksum nguồn đã đổi; tải lại nguồn trước khi khôi phục.")
            media = probe_media(source)
            sources[row["source"]] = source, checksum, media
        if checksum != row["source_sha256"] or row["start"] + row["duration"] > media["duration"] + 0.01:
            raise RuntimeError("Nguồn hoặc thời gian clip không khớp nguồn đã khóa.")
    torch = gpu()
    from faster_whisper import WhisperModel
    from huggingface_hub import HfApi, snapshot_download
    pin = job / "recovery-revision.json"
    if not pin.exists():
        write_json(pin, {"repo": RECOVERY_REPO, "revision": HfApi().model_info(RECOVERY_REPO).sha})
    pinned = read_json(pin)
    if pinned.get("repo") != RECOVERY_REPO or not pinned.get("revision"):
        raise RuntimeError("Phiên bản model khôi phục không hợp lệ.")
    revision = pinned["revision"]
    path = job / "recovery-proposals.json"
    saved = read_json(path) if path.exists() else {"rows": {}}
    if any(proposal.get("identity", {}).get("policy") != RECOVERY_POLICY for proposal in saved.get("rows", {}).values()):
        archive = job / f"recovery-proposals-{sha256(path)}.json"
        if not archive.exists():
            temporary = archive.with_suffix(".tmp")
            shutil.copyfile(path, temporary)
            temporary.replace(archive)
        saved = {"rows": {}}
    saved["progress"] = {"total": len(selected), "completed": 0}
    write_json(path, saved)
    model = None
    try:
        for index, row in enumerate(selected, 1):
            if (job / "cancel.request").exists():
                raise RuntimeError("Đã dừng giữa các clip; chạy lại để tiếp tục khôi phục.")
            identity = recovery_identity(row, manifest["language"])
            previous = saved["rows"].get(row["file"], {})
            if not (previous.get("identity") == identity and previous.get("repo") == RECOVERY_REPO
                    and previous.get("revision") == revision):
                if model is None:
                    model_path = snapshot_download(RECOVERY_REPO, revision=revision, cache_dir=str(ROOT / "model-cache"))
                    model = WhisperModel(model_path, device="cuda", compute_type=RECOVERY_POLICY["compute_type"])
                clip = job / "dataset/raw_audio" / row["file"]
                segments, info = model.transcribe(str(clip), language=manifest["language"], **RECOVERY_POLICY["decode"])
                segments = list(segments)
                text = " ".join(segment.text.strip() for segment in segments).strip()
                issues, timestamps, last_end = [], [], -1
                for segment in segments:
                    a, b = getattr(segment, "start", None), getattr(segment, "end", None)
                    finite = [isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                              for value in (a, b)]
                    timestamps.append({"start": a if finite[0] else None, "end": b if finite[1] else None,
                                       "text": segment.text})
                    if not all(finite) or a < 0 or b <= a or b > row["duration"] + 0.1 or a < last_end:
                        issues.append("invalid_segment_timestamps")
                    if all(finite):
                        last_end = b
                    if not segment.text.strip():
                        issues.append("empty_segment")
                tokens = transcript_key(text).split()
                if any(tokens[index:index+size] == tokens[index+size:index+size*2] == tokens[index+size*2:index+size*3]
                       for size in range(2, min(9, len(tokens)//3 + 1)) for index in range(len(tokens)-size*3 + 1)):
                    issues.append("repeated_text")
                if not text:
                    issues.append("empty_transcript")
                metrics = {}
                for name in ("avg_logprob", "no_speech_prob", "compression_ratio"):
                    values = [float(value) for segment in segments if isinstance(value := getattr(segment, name, None), (int, float))
                              and math.isfinite(value)]
                    metrics[name] = sum(values) / len(values) if values else None
                language = getattr(info, "language_probability", None)
                metrics["language_probability"] = float(language) if isinstance(language, (int, float)) and math.isfinite(language) else None
                saved["rows"][row["file"]] = {"identity": identity, "repo": RECOVERY_REPO, "revision": revision,
                    "method": "recovered_full_clip", "text": text, "complete": bool(text) and not issues,
                    "issues": sorted(set(issues)), "segments": timestamps, "asr": metrics}
            saved["progress"]["completed"] = index
            write_json(path, saved)
            print(f"Gợi ý khôi phục {index}/{len(selected)}: {row['file']}; giữ nguyên lời/duyệt/lựa chọn.")
        if (job / "cancel.request").exists():
            raise RuntimeError("Đã dừng sau clip đã lưu; chạy lại để tiếp tục khôi phục.")
    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()


def review_dataset(job):
    import ipywidgets as widgets
    from IPython.display import Audio, display, clear_output
    rows = read_json(job / "review.json")
    picker = widgets.Dropdown(options=[(f"{i+1}. {r['source']} @ {r['start']:.1f}s", i) for i, r in enumerate(rows)], layout={"width": "95%"})
    transcript = widgets.Textarea(layout={"width": "95%", "height": "100px"})
    include = widgets.Checkbox(description="Dùng đoạn này")
    save = widgets.Button(description="Lưu / đã nghe đoạn")
    approve = widgets.Button(description="Duyệt dataset")
    output = widgets.Output()
    status = widgets.Output()

    def show(_=None):
        row = rows[picker.value]
        transcript.value = row["text"]
        include.value = row["include"]
        with output:
            clear_output(wait=True)
            display(Audio(filename=str(job / "dataset" / "raw_audio" / row["file"])))

    def save_row(_):
        row = rows[picker.value]
        row.update(text=" ".join(transcript.value.replace("|", " ").split()), include=include.value,
                   reviewed=True, review_method="manual_listening")
        write_json(job / "review.json", rows)
        (job / "dataset-approved.json").unlink(missing_ok=True)
        with status:
            clear_output()
            print(f"Đã lưu. Đã xem {sum(r['reviewed'] for r in rows)}/{len(rows)} đoạn.")
        if picker.value + 1 < len(rows):
            picker.value += 1

    def approve_rows(_):
        with status:
            clear_output()
            included = [r for r in rows if r["include"]]
            if not included or any(not r["reviewed"] or not r["text"] for r in included):
                print("Nghe và lưu mọi đoạn được dùng trước khi duyệt. Bỏ đoạn sai người, có nhạc hoặc transcript không sửa được.")
                return
            if len(included) < 20:
                print("Cần ít nhất 20 đoạn được duyệt. Nên chuẩn bị khoảng 10–30 phút audio sạch.")
                return
            write_json(job / "dataset-approved.json", {"review_sha256": sha256(job / "review.json")})
            print("Đã duyệt dataset. Có thể chạy fine-tune.")

    picker.observe(show, names="value")
    save.on_click(save_row)
    approve.on_click(approve_rows)
    show()
    display(widgets.VBox([picker, output, transcript, include, save, approve, status]))


def train(job, epochs=3, resume_run=None):
    gpu()
    if not 1 <= epochs <= 20:
        raise ValueError("epochs phải từ 1 đến 20.")
    approved = job / "dataset-approved.json"
    if not approved.exists() or read_json(approved)["review_sha256"] != sha256(job / "review.json"):
        raise RuntimeError("Dataset chưa duyệt hoặc đã thay đổi; duyệt lại trước khi train.")
    rows = [r for r in read_json(job / "review.json") if r["include"]]
    for row in rows:
        if not row["reviewed"] or sha256(job / "dataset" / "raw_audio" / row["file"]) != row["sha256"]:
            raise RuntimeError("Audio đã thay đổi hoặc chưa được duyệt. Chuẩn bị dataset mới.")
    from huggingface_hub import HfApi, snapshot_download
    pin = job / "base-revision.json"
    if not pin.exists():
        write_json(pin, {"repo": BASE_REPO, "revision": HfApi().model_info(BASE_REPO).sha, "code_commit": UPSTREAM_COMMIT})
    base = snapshot_download(BASE_REPO, revision=read_json(pin)["revision"], cache_dir=str(ROOT / "model-cache"),
                             allow_patterns=BASE_PATTERNS)
    dataset = job / "dataset"
    (dataset / "metadata.csv").write_text("\n".join(f"{r['file']}|{r['text']}" for r in rows), encoding="utf-8")
    if resume_run:
        if not re.fullmatch(r"[a-f0-9]{32}", resume_run):
            raise ValueError("Run ID không hợp lệ.")
        run_dir = job / "runs" / resume_run
        if not (run_dir / "trainer-state.pt").exists() or (run_dir / "profile.json").exists():
            raise RuntimeError("Chỉ resume run bị ngắt có checkpoint đầy đủ và chưa đóng gói model.")
        if sha256(job / "review.json") != sha256(run_dir / "review.json"):
            raise RuntimeError("Dataset đã sửa. Tạo run mới, không resume bản cũ.")
    else:
        run(sys.executable, Path(__file__), "--onnx-cli", "prepare_dataset.py", "--dataset-dir", dataset, "--base", base)
    import pyarrow.parquet as pq
    parquet = run_dir / "train.parquet" if resume_run else dataset / "train.parquet"
    if pq.read_table(parquet).num_rows != len(rows):
        raise RuntimeError("Bộ mã hóa đã bỏ một số đoạn. Xem log và sửa dataset trước khi train.")
    run_id = resume_run or uuid.uuid4().hex
    run_dir = job / "runs" / run_id
    write_json(run_dir / "status.json", {"status": "training", "review_sha256": sha256(job / "review.json")})
    # Snapshot reviewed inputs for this run; later edits cannot change its provenance.
    if not resume_run:
        shutil.copy2(job / "review.json", run_dir / "review.json")
        shutil.copy2(dataset / "train.parquet", run_dir / "train.parquet")
    command = [sys.executable, Path(__file__).with_name("train_resumable.py"), "--run-dir", run_dir,
               "--base", base, "--epochs", epochs]
    try:
        run(*command)
        reference = next((r for r in rows if 3 <= r["duration"] <= 8), None)
        if reference is None:
            reference = rows[0]
        manifest = read_json(job / "selection.json")
        run(sys.executable, Path(__file__), "--onnx-cli", "make_voice.py", "--audio", dataset / "raw_audio" / reference["file"],
            "--name", manifest["voice_name"], "--description", "AIFlow fine-tuned voice", "--base", base,
            "--out", run_dir / "merged" / "voices_v3_turbo.json", "--default")
        profile = {"id": f"ft_{run_id}", "name": manifest["voice_name"], "language": manifest["language"],
                   "status": "awaiting_review", "job_id": job.name, "run_id": run_id,
                   "base": read_json(pin), "review_sha256": sha256(job / "review.json"),
                   "review_methods": {method: sum(row.get("review_method", "manual_listening") == method for row in rows)
                                      for method in ("manual_listening", "text_acoustic_review")},
                   "weights_sha256": sha256(run_dir / "merged/update/model.safetensors"),
                   "voices_sha256": sha256(run_dir / "merged/voices_v3_turbo.json")}
        write_json(run_dir / "profile.json", profile)
        write_json(run_dir / "status.json", {"status": "awaiting_review"})
        return run_dir
    except BaseException:
        write_json(run_dir / "status.json", {"status": "interrupted_or_failed"})
        raise


def saved_voices(approved_only=True):
    result = []
    for path in ROOT.glob("*/runs/*/profile.json"):
        profile = read_json(path)
        if not approved_only or profile["status"] == "approved":
            result.append((f"{profile['name']} · {profile['language']} · {profile['run_id'][:8]} · {profile['status']}", str(path.parent)))
    return result


def load_voice(run_dir, require_approved=True):
    gpu()
    from vieneu import Vieneu
    run_dir = Path(run_dir)
    profile = read_json(run_dir / "profile.json")
    if require_approved and profile["status"] != "approved":
        raise RuntimeError("Nghe và duyệt giọng trước khi bật API.")
    if (sha256(run_dir / "merged/update/model.safetensors") != profile["weights_sha256"]
            or sha256(run_dir / "merged/voices_v3_turbo.json") != profile["voices_sha256"]):
        raise RuntimeError("Model/giọng đã thay đổi sau huấn luyện. Không load bản không khớp.")
    tts = Vieneu(mode="v3turbo", backbone_repo=str(run_dir / "merged"), backend="pytorch", device="cuda")
    return tts, profile


def preview_options(temperature=0.8, seed=42):
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or not 0.1 <= temperature <= 1.5:
        raise ValueError("Temperature phải từ 0.1 đến 1.5.")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 4294967295:
        raise ValueError("Seed phải là số nguyên từ 0 đến 4294967295.")
    return {"temperature": float(temperature), "seed": seed}


def infer_preview_options(tts, text, voice, options):
    import inspect
    import random

    import numpy as np
    import torch
    from vieneu_utils.phonemize_text import normalize_to_chunks_v3_with_gaps
    from vieneu_utils.core_utils import gaps_to_silence, join_audio_chunks

    chunks, gaps = normalize_to_chunks_v3_with_gaps(text, max_chars=INFERENCE_POLICY["max_chars"])
    random.seed(options["seed"])
    np.random.seed(options["seed"])
    torch.manual_seed(options["seed"])
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(options["seed"])
    if len(chunks) <= 1:
        return tts.infer(text, voice=voice, temperature=options["temperature"], batch_size=INFERENCE_POLICY["batch_size"])
    # VieNeu otherwise length-sorts chunks even at batch_size=1, changing RNG order.
    defaults = inspect.signature(tts.infer).parameters
    sampling = {name: defaults[name].default for name in
                ("top_k", "top_p", "max_new_frames", "repetition_penalty", "repetition_window")}
    sampling["temperature"] = options["temperature"]
    speaker_emb, ref_codes = tts._resolve_ref(voice, None, True, True)
    wavs = [tts._infer_chunks([chunk], speaker_emb, ref_codes, True,
                             INFERENCE_POLICY["batch_size"], sampling)[0] for chunk in chunks]
    audio = join_audio_chunks(wavs, tts.sample_rate, silence_ps=gaps_to_silence(gaps))
    return tts._apply_watermark(audio)


def sample_voice(run_dir, text, temperature=0.8, seed=42):
    options = preview_options(temperature, seed)
    torch = gpu()
    import soundfile as sf
    from IPython.display import Audio, display
    tts, profile = load_voice(run_dir, require_approved=False)
    try:
        # Any newly generated audio requires a fresh listening decision.
        profile["status"] = "awaiting_review"
        profile.pop("approved_sample_sha256", None)
        write_json(Path(run_dir) / "profile.json", profile)
        write_json(Path(run_dir) / "status.json", {"status": "awaiting_review"})
        audio = infer_preview_options(tts, text, profile["name"], options)
        sf.write(str(Path(run_dir) / "sample.wav"), audio, tts.sample_rate)
        write_json(Path(run_dir) / "sample.json", {"text": text, "weights_sha256": profile["weights_sha256"],
                   "voices_sha256": profile["voices_sha256"], "inference_options": options,
                   "inference_policy": INFERENCE_POLICY,
                   "sample_sha256": sha256(Path(run_dir) / "sample.wav")})
        display(Audio(audio, rate=tts.sample_rate))
    finally:
        del tts
        gc.collect()
        torch.cuda.empty_cache()


def approve_voice(run_dir):
    run_dir = Path(run_dir)
    profile = read_json(run_dir / "profile.json")
    sample = read_json(run_dir / "sample.json")
    sample_hash = sha256(run_dir / "sample.wav") if (run_dir / "sample.wav").exists() else ""
    if (not sample_hash or sample["weights_sha256"] != profile["weights_sha256"]
            or sample.get("voices_sha256", profile["voices_sha256"]) != profile["voices_sha256"]
            or sample.get("sample_sha256", sample_hash) != sample_hash):
        raise RuntimeError("Tạo và nghe mẫu của lượt train này trước.")
    profile["inference_options"] = preview_options(**sample.get("inference_options", {}))
    profile["approved_sample_sha256"] = sample_hash
    profile["status"] = "approved"
    write_json(run_dir / "profile.json", profile)
    write_json(run_dir / "status.json", {"status": "approved"})
    print("Đã duyệt và lưu trên My Drive. Có thể load lại mà không train.")


def configure_worker(run_dir):
    import audio_worker as worker
    import librosa
    import soxr
    if worker.PIPELINE is not None or worker.ACTIVE:
        raise RuntimeError("Worker đã load model. Dừng runtime trước khi đổi giọng.")
    tts, profile = load_voice(run_dir)
    options = preview_options(**profile.get("inference_options", {}))

    def pipeline(text, voice, speed=1.0):
        audio = infer_preview_options(tts, text, voice, options)
        audio = soxr.resample(audio, tts.sample_rate, 24000)
        if speed != 1:
            audio = librosa.effects.time_stretch(audio, rate=speed)
        yield None, None, audio

    worker.ENGINE = "vieneu-v3turbo-finetune"
    worker.LANGUAGES = [profile["language"]]
    worker.VOICES = (profile["id"],)
    worker.VOICE_FILES = {profile["id"]: profile["name"]}
    worker.VOICE_METADATA = [{"id": profile["id"], "name": profile["name"], "language": profile["language"],
                              "backend": "remote", "gender": "unknown", "is_custom": True,
                              "description": "VieNeu LoRA · đã fine-tune và duyệt", "demo_audio_path": None}]
    worker.REVISION = worker.digest({"weights": profile["weights_sha256"], "voices": profile["voices_sha256"],
                                     "code": UPSTREAM_COMMIT, "inference_options": options,
                                     "inference_policy": INFERENCE_POLICY})
    worker.PIPELINE = pipeline
    return worker

if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--onnx-cli":
    onnx_cli(sys.argv[2], sys.argv[3:])
