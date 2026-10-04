"""Verified PCM16 tails may fit scene timing without changing original speech files."""

import json
import math
import wave
from array import array

import pytest
from sqlmodel import Session

from server.db.models.job import Job
from server.db.models.production import ProductionMedia, ProductionOutput
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.production import render as renderer
from server.production.media import ffmpeg, probe, sha256
from server.tests.test_production import client as client


def wav(path, tail_frames=1920, tail=(90,), sample_width=2):
    rate, channels = 24000, len(tail)
    samples = array("h", [1000] * (8 * rate * channels) + list(tail) * tail_frames)
    payload = samples.tobytes() if sample_width == 2 else b"".join(
        int(sample).to_bytes(sample_width, "little", signed=True) for sample in samples
    )
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(sample_width)
        stream.setframerate(rate)
        stream.writeframes(payload)
    return 8 + tail_frames / rate


@pytest.mark.parametrize("tail,tail_frames,width,accepted", [
    ((103, -103), 1920, 2, True),
    ((0, 104), 1920, 2, False),
    ((-104,), 1920, 2, False),
    ((90,), 2400, 2, True),
    ((90,), 2401, 2, False),
    ((90,), 1920, 3, False),
    ((90,), 1920, 4, False),
    ((90,), 0, 2, False),
])
def test_fit_reads_all_pcm16_channels_and_preserves_original(tmp_path, tail, tail_frames, width, accepted):
    path = tmp_path / "speech.wav"
    duration = wav(path, tail_frames, tail, width)
    original = sha256(path)
    fit = renderer._fit_narration_tail(path, duration, 8)
    assert sha256(path) == original
    assert fit["source_duration"] == duration
    assert fit["used_duration"] == (8 if accepted else duration)
    assert fit["trimmed_tail_seconds"] == pytest.approx(tail_frames / 24000 if accepted else 0)
    assert fit["trim_peak_dbfs_threshold"] == -50
    if accepted:
        assert fit["trim_reason"] == "verified_pcm16_near_silent_tail"
        assert fit["trim_tail_peak_pcm16"] == max(abs(sample) for sample in tail)
    else:
        assert fit["trim_reason"] is None


def test_one_loud_sample_anywhere_in_tail_prevents_fit(tmp_path):
    path = tmp_path / "speech.wav"
    duration = wav(path)
    with path.open("r+b") as stream:
        stream.seek(-2, 2)
        stream.write((104).to_bytes(2, "little", signed=True))
    original = sha256(path)
    fit = renderer._fit_narration_tail(path, duration, 8)
    assert fit["used_duration"] == duration
    assert fit["trimmed_tail_seconds"] == 0
    assert sha256(path) == original


def test_float_wav_and_truncated_pcm_tail_fail_closed(tmp_path):
    float_path = tmp_path / "float.wav"
    ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "8.08", "-c:a", "pcm_f32le", str(float_path)])
    assert renderer._fit_narration_tail(float_path, 8.08, 8)["used_duration"] == 8.08
    truncated = tmp_path / "truncated.wav"
    wav(truncated)
    with truncated.open("r+b") as stream:
        stream.truncate(truncated.stat().st_size - 2)
    original = sha256(truncated)
    assert renderer._fit_narration_tail(truncated, 8.08, 8)["used_duration"] == 8.08
    assert sha256(truncated) == original


def test_invalid_wav_sample_rate_fails_closed(tmp_path):
    path = tmp_path / "invalid-rate.wav"
    wav(path)
    with path.open("r+b") as stream:
        stream.seek(24)
        stream.write(b"\0" * 4)
    original = sha256(path)
    assert renderer._fit_narration_tail(path, 8.08, 8)["used_duration"] == 8.08
    assert sha256(path) == original


def project_with_audio(client, tail_frames=1920, tail=(90,), sample_width=2):
    speech, visual = client.root / "speech.wav", client.root / "visual.mp4"
    duration = wav(speech, tail_frames, tail, sample_width)
    ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=64x64:rate=24:duration=8", "-c:v", "libx264", str(visual)])
    with Session(client.engine) as session:
        project = Project(title="Tail fixture", short_id="tail", kind="video", aspect="16:9")
        session.add(project)
        session.flush()
        scene = Scene(project_id=project.id, order=0, prompt="Moving pattern", narration="Keep all spoken content.",
                      duration=8, audio_path=str(speech))
        session.add(scene)
        session.flush()
        session.add(ProductionMedia(
            project_id=project.id, scene_id=scene.id, role="visual", path=str(visual), mime="video/mp4",
            width=64, height=64, duration=8, sha256=sha256(visual), approved=True,
            review_json=json.dumps({"scene_content": {"prompt": scene.prompt, "narration": scene.narration}}),
        ))
        session.commit()
        return project.id, scene.id, speech, duration


def test_snapshot_and_real_render_fit_only_verified_eighty_ms(client):
    project_id, scene_id, speech, duration = project_with_audio(client)
    original = sha256(speech)
    with Session(client.engine) as session:
        manifest = renderer.snapshot(session, session.get(Project, project_id), client.root)
        scene = manifest["scenes"][0]
        assert scene["script_duration"] == scene["duration"] == 8
        audio = scene["audio"]
        assert audio["duration"] == audio["source_duration"] == duration == 8.08
        assert audio["used_duration"] == 8
        assert audio["trimmed_tail_seconds"] == 0.08
        assert audio["trim_tail_peak_dbfs"] == pytest.approx(20 * math.log10(90 / 32768))
        job = Job(project_id=project_id, type="production_render", status="pending")
        session.add(job)
        session.flush()
        output = ProductionOutput(project_id=project_id, job_id=job.id, kind="video", status="rendering",
                                  manifest_json=json.dumps(manifest), folder=str(client.root / "output"))
        session.add(output)
        session.commit()
        output_id = output.id
    renderer.render(client.engine, client.root, output_id)
    with Session(client.engine) as session:
        output = session.get(ProductionOutput, output_id)
        assert output.status == "awaiting_review", output.manifest_json
        delivered = json.loads(output.manifest_json)
        assert delivered["scenes"][0]["duration"] == 8
        assert delivered["scenes"][0]["audio"]["sha256"] == original
        assert session.get(Scene, scene_id).duration == 8
        assert session.get(Scene, scene_id).audio_path == str(speech)
    video_info = probe(client.root / "output/video.mp4")
    video_stream = next(stream for stream in video_info["streams"] if stream["codec_type"] == "video")
    assert int(video_stream["nb_frames"]) == 192
    assert float(video_stream["duration"]) == 8
    assert sha256(speech) == original


@pytest.mark.parametrize("tail_frames,tail,width", [
    (1920, (104,), 2),
    (2880, (90,), 2),
    (1920, (90,), 3),
])
def test_unverified_tail_keeps_existing_short_clip_rejection(client, tail_frames, tail, width):
    project_id, _, speech, duration = project_with_audio(client, tail_frames, tail, width)
    original = sha256(speech)
    with Session(client.engine) as session:
        project = session.get(Project, project_id)
        with pytest.raises(ValueError, match="ngắn hơn lời đọc"):
            renderer.snapshot(session, project, client.root)
        allowed = renderer.snapshot(session, project, client.root, allow_loop=True)
        assert allowed["scenes"][0]["duration"] == duration
        assert allowed["scenes"][0]["audio"]["used_duration"] == duration
        assert allowed["scenes"][0]["audio"]["trimmed_tail_seconds"] == 0
    assert sha256(speech) == original
