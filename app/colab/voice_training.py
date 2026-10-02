"""Colab-only selected-R2 dataset, reviewed LoRA training, and saved voice serving."""

import gc
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

UPSTREAM_COMMIT = "c1390abbdb2eedcdf58eafb546966c06ce27af71"
UPSTREAM = Path("/content/VieNeu-TTS")
ROOT = Path("/content/drive/MyDrive/AIFlow/voice-training")
BASE_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"


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


def gpu():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("Chọn GPU runtime trước khi chạy bước này.")
    return torch


def open_selection(path):
    manifest = read_json(path)
    if (manifest.get("schema_version") != 1 or manifest.get("mode") != "finetune"
            or not manifest.get("same_speaker_confirmed")
            or not re.fullmatch(r"[a-f0-9]{32}", manifest.get("job_id", ""))
            or manifest.get("language") not in ("vi", "en")):
        raise ValueError("Gói lựa chọn không hợp lệ. Tạo lại từ AIFlow.")
    if not re.fullmatch(r"https://[a-fA-F0-9]{32}(?:\.(?:eu|fedramp))?\.r2\.cloudflarestorage\.com", manifest["endpoint"]):
        raise ValueError("Endpoint không phải R2.")
    files = manifest["files"]
    if not 1 <= len(files) <= 5000 or len({f["id"] for f in files}) != len(files):
        raise ValueError("Danh sách file trống, trùng hoặc quá lớn.")
    for file in files:
        if file["id"] != hashlib.sha256(file["key"].encode()).hexdigest() or not 0 < file["size"] <= 2 * 1024**3:
            raise ValueError("File trong manifest không hợp lệ.")
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
    import boto3
    from botocore.config import Config
    def secret(name):
        if os.environ.get(name):
            return os.environ[name]
        from google.colab import userdata
        return userdata.get(name)
    manifest = read_json(job / "selection.json")
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


def prepare_clips(job):
    """ASR runs on Colab. Never classify people from filenames or auto-approve text."""
    torch = gpu()
    from faster_whisper import WhisperModel
    from huggingface_hub import HfApi, snapshot_download
    manifest = read_json(job / "selection.json")
    receipts = read_json(job / "downloads.json")
    review_path = job / "review.json"
    if review_path.exists():
        print("Dataset đã có: mở trình duyệt dataset để sửa/duyệt; không ghi đè bản sửa.")
        return
    model_repo = "Systran/faster-whisper-small"
    pin = job / "asr-revision.json"
    if not pin.exists():
        write_json(pin, {"repo": model_repo, "revision": HfApi().model_info(model_repo).sha})
    model_path = snapshot_download(model_repo, revision=read_json(pin)["revision"], cache_dir=str(ROOT / "model-cache"))
    model = WhisperModel(model_path, device="cuda", compute_type="int8_float16")
    clips = job / "dataset" / "raw_audio"
    clips.mkdir(parents=True, exist_ok=True)
    rows = []
    skipped = 0
    try:
        for file in manifest["files"]:
            receipt = receipts.get(file["id"])
            if not receipt:
                raise RuntimeError("Chưa tải đủ file đã chọn. Chạy ô tải trước.")
            source = job / "source" / receipt["file"]
            if sha256(source) != receipt["sha256"]:
                raise RuntimeError("File nguồn trên Drive đã đổi. Chạy lại ô tải.")
            segments, _ = model.transcribe(str(source), language=manifest["language"], vad_filter=True,
                                           word_timestamps=True, condition_on_previous_text=False)
            index = 0
            for segment in segments:
                words = list(segment.words or [])
                groups = []
                current = []
                for word in words:
                    if current and word.end - current[0].start > 15:
                        groups.append(current)
                        current = []
                    current.append(word)
                if current:
                    groups.append(current)
                for group in groups:
                    start = max(0, group[0].start - 0.08)
                    duration = group[-1].end + 0.08 - start
                    text = "".join(w.word for w in group).strip()
                    if not 1 <= duration <= 20 or not text:
                        skipped += 1
                        continue
                    index += 1
                    name = f"{file['id'][:20]}_{index:05d}.wav"
                    run("ffmpeg", "-v", "error", "-y", "-ss", start, "-i", source, "-t", duration,
                        "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", clips / name)
                    rows.append({"file": name, "text": text, "duration": duration,
                                 "source": file["key"], "start": start, "include": True, "reviewed": False,
                                 "sha256": sha256(clips / name)})
            print(f"Đã tách {index} đoạn từ {file['key']}")
        if not rows:
            raise RuntimeError("Không có đoạn hợp lệ. Kiểm tra file có giọng rõ và đúng ngôn ngữ.")
        write_json(review_path, rows)
        print(f"{len(rows)} đoạn, {sum(r['duration'] for r in rows)/60:.1f} phút; bỏ {skipped} đoạn ngoài 1–20 giây. Chưa duyệt.")
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
        row.update(text=" ".join(transcript.value.replace("|", " ").split()), include=include.value, reviewed=True)
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
    base = snapshot_download(BASE_REPO, revision=read_json(pin)["revision"], cache_dir=str(ROOT / "model-cache"))
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
        run(sys.executable, UPSTREAM / "finetune/prepare_dataset.py", "--dataset-dir", dataset, "--base", base)
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
        run(sys.executable, UPSTREAM / "finetune/make_voice.py", "--audio", dataset / "raw_audio" / reference["file"],
            "--name", manifest["voice_name"], "--description", "AIFlow fine-tuned voice", "--base", base,
            "--out", run_dir / "merged" / "voices_v3_turbo.json", "--default")
        profile = {"id": f"ft_{run_id}", "name": manifest["voice_name"], "language": manifest["language"],
                   "status": "awaiting_review", "job_id": job.name, "run_id": run_id,
                   "base": read_json(pin), "review_sha256": sha256(job / "review.json"),
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


def sample_voice(run_dir, text):
    torch = gpu()
    import soundfile as sf
    from IPython.display import Audio, display
    tts, profile = load_voice(run_dir, require_approved=False)
    try:
        audio = tts.infer(text, voice=profile["name"])
        sf.write(str(Path(run_dir) / "sample.wav"), audio, tts.sample_rate)
        write_json(Path(run_dir) / "sample.json", {"text": text, "weights_sha256": profile["weights_sha256"]})
        display(Audio(audio, rate=tts.sample_rate))
    finally:
        del tts
        gc.collect()
        torch.cuda.empty_cache()


def approve_voice(run_dir):
    run_dir = Path(run_dir)
    profile = read_json(run_dir / "profile.json")
    if not (run_dir / "sample.wav").exists() or read_json(run_dir / "sample.json")["weights_sha256"] != profile["weights_sha256"]:
        raise RuntimeError("Tạo và nghe mẫu của lượt train này trước.")
    profile["status"] = "approved"
    write_json(run_dir / "profile.json", profile)
    print("Đã duyệt và lưu trên My Drive. Có thể load lại mà không train.")


def configure_worker(run_dir):
    import audio_worker as worker
    import librosa
    import soxr
    if worker.PIPELINE is not None or worker.ACTIVE:
        raise RuntimeError("Worker đã load model. Dừng runtime trước khi đổi giọng.")
    tts, profile = load_voice(run_dir)

    def pipeline(text, voice, speed=1.0):
        audio = tts.infer(text, voice=voice)
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
    worker.REVISION = worker.digest({"weights": profile["weights_sha256"], "voices": profile["voices_sha256"], "code": UPSTREAM_COMMIT})
    worker.PIPELINE = pipeline
    return worker
