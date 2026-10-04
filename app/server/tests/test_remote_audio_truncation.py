"""A valid checksum does not make an incomplete WAV safe for narration timing."""

import hashlib
import json

import pytest

from server.audio import remote
from server.audio.tts import TTSError
from server.tests.test_remote_audio import wav


def test_downloaded_truncated_pcm_is_rejected_before_cache_commit(tmp_path):
    key = "1" * 64
    content = wav()[:-4]
    with pytest.raises(TTSError, match="WAV"):
        remote.store_audio(tmp_path, key, content, hashlib.sha256(content).hexdigest())
    assert not remote.cache_path(tmp_path, key).exists()
    assert not remote.cache_path(tmp_path, key).with_suffix(".json").exists()
    assert not list((tmp_path / "audio" / "cache").glob("*.part"))


def test_existing_truncated_cache_cannot_report_false_combined_duration(tmp_path):
    key = "2" * 64
    path = remote.cache_path(tmp_path, key)
    path.parent.mkdir(parents=True)
    content = wav()[:-4]
    path.write_bytes(content)
    path.with_suffix(".json").write_text(json.dumps({"checksum": hashlib.sha256(content).hexdigest()}))
    assert remote.cached(tmp_path, key)
    destination = tmp_path / "previous.wav"
    previous = wav()
    destination.write_bytes(previous)
    with pytest.raises(TTSError, match="WAV"):
        remote.combine(tmp_path, [{"key": key}], destination)
    assert destination.read_bytes() == previous
    assert not destination.with_suffix(".part").exists()
