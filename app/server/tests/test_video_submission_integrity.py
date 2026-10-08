"""Remote generation is not replayed after local failures or file collisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.db.models.scene import Scene
from server.pipeline.orchestrator import PipelineOrchestrator
from server.pipeline.poller import VideoPoller, _PendingOp


def make_orchestrator(tmp_path, monkeypatch):
    import server.pipeline.orchestrator as module

    monkeypatch.setattr(module, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(module, "_MAX_POLL_ATTEMPTS", 1)
    sdk = SimpleNamespace(gen_video=AsyncMock(return_value="operations/original"),
                          check_async=AsyncMock(return_value={"data": {"operations": [{
                              "operation": {"name": "operations/original", "done": True,
                                  "metadata": {"video": {"mediaId": "video-id", "fifeUrl": "https://example.test/video"}}},
                              "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
                          }]}}))
    settings = SimpleNamespace(data_dir=tmp_path)
    orch = PipelineOrchestrator(settings, sdk)
    orch._flow_project_id = "remote-project"
    return orch, sdk


@pytest.mark.parametrize("failure", ["submit", "poll", "download"])
async def test_remote_submission_is_not_replayed_after_failure(tmp_path, monkeypatch, failure):
    orch, sdk = make_orchestrator(tmp_path, monkeypatch)
    image = tmp_path / "start.png"
    image.write_bytes(b"fixture")
    if failure == "submit":
        sdk.gen_video.side_effect = TimeoutError("response lost after acceptance")
    elif failure == "poll":
        sdk.check_async.side_effect = ConnectionError("bridge disconnected")
    else:
        failed_download = AsyncMock(side_effect=RuntimeError("download failed"))
        monkeypatch.setattr("server.flow.downloader.download_video", failed_download)
    scene = Scene(project_id=1, order=0, prompt="A forest", narration="")
    lock = MagicMock()
    lock.inject.side_effect = lambda prompt: prompt
    chain = MagicMock()
    chain.get_last_frame.return_value = image

    assert not await orch._run_scene(scene, 1, lock, lock, [], chain, [scene])
    assert sdk.gen_video.await_count == 1
    if failure == "download":
        failed_download.assert_awaited_once()


async def test_definitively_unsent_request_can_retry(tmp_path, monkeypatch):
    from server.flow.rpc import FlowRPCError

    orch, sdk = make_orchestrator(tmp_path, monkeypatch)
    image = tmp_path / "start.png"
    image.write_bytes(b"fixture")
    sdk.gen_video.side_effect = FlowRPCError({"error": "FLOW_UI_BUSY", "requestSent": False})
    scene = Scene(project_id=1, order=0, prompt="A forest", narration="")
    lock = MagicMock()
    lock.inject.side_effect = lambda prompt: prompt
    chain = MagicMock()
    chain.get_last_frame.return_value = image

    assert not await orch._run_scene(scene, 1, lock, lock, [], chain, [scene])
    assert sdk.gen_video.await_count == 2


async def test_download_paths_are_distinct_for_multiple_completions(tmp_path, monkeypatch):
    orch, _ = make_orchestrator(tmp_path, monkeypatch)
    paths = []

    async def download(url, path):
        paths.append(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(url.encode())
        return path

    monkeypatch.setattr("server.flow.downloader.download_video", download)
    for _ in range(2):
        await orch._poll_until_done("operations/original", "remote-project", tmp_path)
    poller = VideoPoller(SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(poller, "_db_mark_success", lambda *args: None)
    for job in (1, 2):
        await poller._download_and_complete(_PendingOp("op", "remote-project", job, tmp_path),
                                            f"https://example.test/video/{job}")

    assert len(set(paths)) == 4
    assert paths[2].read_bytes() == b"https://example.test/video/1"
    assert paths[3].read_bytes() == b"https://example.test/video/2"


async def test_failed_small_download_preserves_previous_video(tmp_path, monkeypatch):
    import httpx
    from server.flow.downloader import download_video

    response = httpx.Response(200, content=b"bad", request=httpx.Request("GET", "https://example.test/video"))
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    monkeypatch.setattr("server.flow.downloader.httpx.AsyncClient", lambda **kwargs: client)
    path = tmp_path / "video.mp4"
    path.write_bytes(b"previous valid bytes")

    with pytest.raises(RuntimeError, match="too small"):
        await download_video("https://example.test/video", path)
    assert path.read_bytes() == b"previous valid bytes"


async def test_download_error_does_not_expose_signed_url(tmp_path, monkeypatch):
    import httpx
    from server.flow.downloader import download_video

    url = "https://example.test/video?signed=private-fixture"
    response = httpx.Response(403, request=httpx.Request("GET", url))
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    monkeypatch.setattr("server.flow.downloader.httpx.AsyncClient", lambda **kwargs: client)

    with pytest.raises(RuntimeError) as error:
        await download_video(url, tmp_path / "video.mp4")
    assert "private-fixture" not in str(error.value)
    assert "HTTPStatusError" in str(error.value)
    assert error.value.__suppress_context__
