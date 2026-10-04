"""Reviewed images/clips + measured narration -> reproducible local delivery bundles."""

import json
import math
import sys
import wave
from array import array
import zipfile
import uuid
from pathlib import Path

from PIL import Image, ImageOps
from sqlmodel import Session, select

from server.db.models.job import Job
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.models.production import ProductionMedia, ProductionOutput
from server.production.media import contained, ffmpeg, probe, sha256, srt_timestamp, validate_video_timing
from server.text.workflow import assert_project_approved


def reconcile_interrupted(engine):
    with Session(engine) as session:
        for output in session.exec(select(ProductionOutput).where(ProductionOutput.status == "rendering")).all():
            output.status = "interrupted"
            job = session.get(Job, output.job_id)
            if job:
                job.status = "needs_attention"
                session.add(job)
            project = session.get(Project, output.project_id)
            if project:
                project.status = "ready"
                session.add(project)
            session.add(output)
        session.commit()


def _fit_narration_tail(path: Path, source_duration: float, nominal_duration: float) -> dict:
    """Fit only a bounded, fully verified near-silent PCM16 WAV tail; keep source bytes."""
    fit = {"source_duration": source_duration, "used_duration": source_duration,
           "trimmed_tail_seconds": 0.0, "trim_reason": None,
           "trim_limit_seconds": 0.10, "trim_peak_dbfs_threshold": -50.0}
    excess = source_duration - nominal_duration
    if nominal_duration <= 0 or not 0 < excess <= 0.10 + 1e-9:
        return fit
    try:
        with wave.open(str(path), "rb") as stream:
            if stream.getcomptype() != "NONE" or stream.getsampwidth() != 2:
                return fit
            rate, channels, total_frames = stream.getframerate(), stream.getnchannels(), stream.getnframes()
            if rate <= 0 or channels <= 0:
                return fit
            if abs(total_frames / rate - source_duration) > 1 / rate:
                return fit
            cut_frame = int(nominal_duration * rate)
            removed_frames = total_frames - cut_frame
            if not 0 < removed_frames / rate <= 0.10:
                return fit
            stream.setpos(cut_frame)
            tail = stream.readframes(removed_frames)
            if len(tail) != removed_frames * channels * 2:
                return fit
    except (OSError, EOFError, wave.Error):
        return fit
    samples = array("h", tail)
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max(abs(sample) for sample in samples)
    if peak > 32768 * 10 ** (-50 / 20):
        return fit
    fit.update(used_duration=nominal_duration, trimmed_tail_seconds=round(excess, 9),
               trim_reason="verified_pcm16_near_silent_tail", trim_tail_peak_pcm16=peak,
               trim_tail_peak_dbfs=20 * math.log10(peak / 32768) if peak else None)
    return fit

def snapshot(session: Session, project: Project, root: Path, allow_loop: bool = False) -> dict:
    if project.kind not in ("portrait", "video"):
        raise ValueError("Chọn loại dự án legacy trước khi sản xuất.")
    media = session.exec(select(ProductionMedia).where(ProductionMedia.project_id == project.id).order_by(ProductionMedia.id)).all()
    def record(item):
        path = contained(root, item.path)
        if sha256(path) != item.sha256:
            raise ValueError("File tài nguyên đã thay đổi sau khi nhập; nhập lại và duyệt.")
        if item.mime == "video/mp4":
            validate_video_timing(path)
        return {"id": item.id, "sha256": item.sha256, "width": item.width, "height": item.height,
                "mime": item.mime, "duration": item.duration}
    result = {"project_id": project.id, "project_short_id": project.short_id, "title": project.title,
              "kind": project.kind, "aspect": project.aspect, "brief": json.loads(project.production_brief),
              "allow_loop": allow_loop, "subtitle_alignment": "scene-level, measured audio duration; not word-aligned STT"}
    if project.kind == "portrait":
        references = [item for item in media if item.role == "reference"]
        portraits = [item for item in media if item.role == "portrait"]
        if not references or not portraits or not portraits[-1].approved:
            raise ValueError("Cần ảnh tham chiếu và ảnh thành phẩm đã duyệt độ giống.")
        result.update(references=[record(item) for item in references], portrait=record(portraits[-1]))
        return result
    assert_project_approved(session, project.id)
    scenes = session.exec(select(Scene).where(Scene.project_id == project.id).order_by(Scene.order)).all()
    if not scenes:
        raise ValueError("Dự án chưa có cảnh.")
    result["scenes"] = []
    for scene in scenes:
        visuals = [item for item in media if item.role == "visual" and item.scene_id == scene.id]
        if not visuals or not visuals[-1].approved:
            raise ValueError(f"Cảnh {scene.order + 1} cần ảnh/clip được duyệt.")
        if json.loads(visuals[-1].review_json).get("scene_content") != {"prompt": scene.prompt, "narration": scene.narration}:
            raise ValueError(f"Nội dung cảnh {scene.order + 1} đã đổi; duyệt lại ảnh/clip cho bản hiện tại.")
        visual = record(visuals[-1])
        audio = None
        duration = float(scene.duration)
        if scene.narration.strip():
            if not scene.audio_path:
                raise ValueError(f"Cảnh {scene.order + 1} chưa có giọng đọc. Mở Colab & giọng đọc, tạo audio trước.")
            path = contained(root, scene.audio_path)
            info = probe(path)
            if not any(s.get("codec_type") == "audio" for s in info["streams"]):
                raise ValueError("File lời đọc không có audio stream.")
            audio = {"path": str(path), "sha256": sha256(path), "duration": info["duration"],
                     **_fit_narration_tail(path, info["duration"], duration)}
            duration = max(duration, audio["used_duration"])
        if visual["mime"] == "video/mp4" and visual["duration"] + 0.05 < duration and not allow_loop:
            raise ValueError(f"Clip cảnh {scene.order + 1} ngắn hơn lời đọc; chọn cho phép loop hoặc nhập clip dài hơn.")
        result["scenes"].append({"id": scene.id, "order": scene.order, "prompt": scene.prompt,
            "narration": scene.narration, "script_duration": scene.duration, "duration": duration,
            "visual": visual, "audio": audio})
    return result


def public_manifest(value: dict) -> dict:
    data = json.loads(json.dumps(value))
    for scene in data.get("scenes", []):
        if scene.get("audio"):
            scene["audio"].pop("path", None)
    return data


def render(engine, root: Path, output_id: int) -> None:
    """Runs once per user request; no model calls and no replay on restart."""
    with Session(engine) as session:
        output = session.get(ProductionOutput, output_id)
        job = session.get(Job, output.job_id)
        if job.status == "cancel_requested":
            job.status = "cancelled"
            output.status = "cancelled"
            project = session.get(Project, output.project_id)
            if project:
                project.status = "ready"
                session.add(project)
            session.add(job)
            session.add(output)
            session.commit()
            return
        if job.status != "pending":
            return
        job.status = "running"
        session.add(job)
        session.commit()
        data = json.loads(output.manifest_json)
        folder = Path(output.folder)
        def checkpoint():
            session.refresh(job)
            if job.status == "cancel_requested":
                raise InterruptedError("Đã hủy giữa các công đoạn; giữ file trung gian.")
        def source(item):
            media = session.get(ProductionMedia, item["id"])
            path = contained(root, media.path)
            if sha256(path) != item["sha256"]:
                raise ValueError("Tài nguyên đã thay đổi sau snapshot.")
            return path
        try:
            checkpoint()
            folder.mkdir(parents=True, exist_ok=True)
            if data["kind"] == "portrait":
                with Image.open(source(data["portrait"])) as image:
                    picture = ImageOps.exif_transpose(image).convert("RGB")
                    picture.save(folder / "portrait.png")
                    picture.save(folder / "portrait.jpg", quality=95)
                    preview = ImageOps.contain(picture, (1200, 1200))
                    preview.save(folder / "preview.jpg", quality=90)
                data["delivery_pixels"] = {"width": picture.width, "height": picture.height}
                data["upscaled"] = False
                (folder / "listing-draft.txt").write_text(
                    f"{data['title']}\nPersonalized pet portrait digital files.\n"
                    f"PNG and JPEG: {picture.width} x {picture.height} pixels. No physical product.\n"
                    "Draft only: review description, licensing and shop requirements before publishing.\n", encoding="utf-8")
            else:
                size = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}
                width, height = size[data["aspect"]]
                subtitles, time_cursor = [], 0.0
                for index, scene in enumerate(data["scenes"]):
                    checkpoint()
                    duration = scene["duration"]
                    visual = scene["visual"]
                    path = source(visual)
                    # Input looping is explicit for video and bounded by -t for every clip.
                    args = (["-stream_loop", "-1"] if visual["mime"] == "video/mp4" else ["-loop", "1"])
                    args += ["-i", str(path)]
                    if scene["audio"]:
                        audio = contained(root, scene["audio"]["path"])
                        if sha256(audio) != scene["audio"]["sha256"]:
                            raise ValueError("Giọng đọc đã thay đổi sau snapshot.")
                        args += ["-i", str(audio)]
                    else:
                        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                    video_filter = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24")
                    if data.get("still_motion") and visual["mime"] != "video/mp4":
                        video_filter += (f",zoompan=z='min(1+on*0.05/{max(1, round(duration * 24))},1.05)'"
                                         f":x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps=24")
                    ffmpeg(args + ["-map", "0:v:0", "-map", "1:a:0", "-vf", video_filter,
                        "-af", "apad", "-t", f"{duration:.6f}", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                        "-movflags", "+faststart", str(folder / f"clip-{index:03}.mp4")])
                    if scene["narration"].strip():
                        if data.get("subtitle_mode") == "remote_stt":
                            from server.production.transcribe import transcribe
                            segments = transcribe(audio, data["language"], root, checkpoint)
                            if any(float(s["end"]) > scene["audio"]["duration"] + .25 for s in segments):
                                raise ValueError("Mốc STT vượt thời lượng lời đọc; kiểm tra Colab.")
                        else:
                            segments = [{"start": 0, "end": scene["audio"]["duration"], "text": scene["narration"]}]
                        for segment in segments:
                            text = segment["text"].replace("\r", " ").replace("\n", " ")
                            start = time_cursor + float(segment["start"])
                            end = time_cursor + min(float(segment["end"]), duration)
                            subtitles.append(f"{len(subtitles) + 1}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text}\n")
                    time_cursor += duration
                checkpoint()
                concat = folder / "concat.txt"
                concat.write_text("\n".join(f"file 'clip-{index:03}.mp4'" for index in range(len(data["scenes"]))), encoding="utf-8")
                ffmpeg(["-f", "concat", "-safe", "1", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(folder / "video.mp4")])
                actual = probe(folder / "video.mp4")
                if abs(actual["duration"] - time_cursor) > max(0.5, len(data["scenes"]) / 24):
                    raise ValueError("Video xuất lệch thời lượng dự kiến; chưa cho duyệt.")
                (folder / "subtitles.srt").write_text("\n".join(subtitles), encoding="utf-8")
                (folder / "script.txt").write_text("\n\n".join(s["narration"] for s in data["scenes"]), encoding="utf-8")
                (folder / "publishing-draft.txt").write_text(f"{data['title']}\nOriginal fictional story.\nReview title, description, thumbnail and disclosure before publishing.\n", encoding="utf-8")
                ffmpeg(["-i", str(folder / "video.mp4"), "-frames:v", "1", str(folder / "thumbnail.jpg")])
                data["actual_duration"] = actual["duration"]
            checkpoint()
            data["files"] = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in folder.iterdir()
                             if p.is_file() and not p.name.startswith("clip-") and p.name != "concat.txt"}
            output.manifest_json = json.dumps(data, ensure_ascii=False)
            output.status = "awaiting_review"
            job.status = "success"
        except Exception as exc:
            output.status = "cancelled" if isinstance(exc, InterruptedError) else "failed"
            job.status = output.status
            data["error"] = str(exc) if isinstance(exc, (ValueError, InterruptedError)) else "Không hoàn tất xuất file. Kiểm tra tài nguyên/FFmpeg rồi tạo lượt xuất mới."
            output.manifest_json = json.dumps(data, ensure_ascii=False)
        project = session.get(Project, output.project_id)
        if project:
            project.status = "ready"
            session.add(project)
        session.add(output)
        session.add(job)
        session.commit()


def package(output: ProductionOutput, root: Path) -> Path:
    if output.status != "approved":
        raise ValueError("Duyệt thành phẩm trước khi tải gói giao hàng.")
    folder = Path(output.folder)
    manifest = json.loads(output.manifest_json)
    path = folder / "delivery.zip"
    temporary = folder / f"delivery-{uuid.uuid4().hex}.tmp"
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in manifest["files"]:
                archive.write(output_file_path(output, name, root), name)
            archive.writestr("manifest.json", json.dumps({**public_manifest(manifest), "review": json.loads(output.review_json)}, ensure_ascii=False, indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def output_file_path(output: ProductionOutput, name: str, root: Path) -> Path:
    """Preview, approval and delivery must use the same rendered file bytes."""
    info = json.loads(output.manifest_json)["files"][name]
    source = contained(root, str(Path(output.folder) / name))
    if sha256(source) != info["sha256"]:
        raise ValueError("Thành phẩm đã thay đổi sau khi render; cần xuất lại.")
    return source
