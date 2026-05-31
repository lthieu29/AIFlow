# Video Remaster — End-to-End Verification (R7.6)

- Timestamp (UTC): 2026-05-31T09:09:44.374677+00:00
- Status: FAILED (download/signing)
- Mode: live-url
- Source: https://www.bilibili.com/video/BV1xx411c7mD
- Preset: n/a
- Output video: n/a
- Translated SRT: n/a

## Failure detail

```
ADAPTER_DOWNLOAD_FAILED: Download failed after 3 attempt(s): yt-dlp not found. Place yt-dlp.exe in vendor/ or install via pip. (details={'url': 'https://www.bilibili.com/video/BV1xx411c7mD', 'code': 'YTDLP_NOT_FOUND'})
```

> Live download/signing failed (R7.7). Re-run with `--local-file` to verify the subtitle->translate->burn chain offline (R7.9).

## What this run already proves

Even though the live download did not complete, this run already verifies
two acceptance criteria of R7:

- **R7.7** — A clear, human-readable error message identifies the failure
  (``ADAPTER_DOWNLOAD_FAILED`` with ``code=YTDLP_NOT_FOUND`` and the offending
  URL) instead of silently producing empty output.
- **R7.10** — The bounded retry policy fires exactly ``retries + 1 = 3``
  attempts before raising; each attempt is logged. The pipeline does not
  hang.

## Live verification deferred to follow-up (per R7.9)

This environment does not have ``yt-dlp`` (Python package or binary), the
vendored ``ffmpeg.exe``, or ``faster-whisper`` installed. Per R7.9, the live
URL run is therefore deferred to a follow-up task; the remaining chain
(``subtitle extraction -> translate -> burn``) is verified offline by the
mocked integration tests in ``server/tests/test_remaster_e2e.py``:

- ``test_light_chain_runs_on_local_video`` — LIGHT preset E2E on a local file.
- ``test_translate_only_returns_original_video`` — TRANSLATE_ONLY preset E2E.
- ``test_empty_srt_fallback_continues_without_crash`` — R7.3 graceful empty SRT.
- ``test_local_fallback_chain_via_adapter`` — full adapter flow via local file
  (R7.9), proving extract -> translate -> burn runs without the download step.

## How to complete the live run later

```powershell
# 1) Install the optional 'remaster' extras (or place yt-dlp.exe in vendor/)
pip install -e .[remaster]

# 2) Place ffmpeg.exe in vendor/ (or add it to PATH)

# 3) Re-run against a real Bilibili / Douyin URL
python server/scripts/verify_video_remaster.py `
    --url "https://www.bilibili.com/video/BVxxxx" `
    --preset light `
    --report docs/reviews/video-remaster-verification.md
```

Expected output: ``PASSED — video_remaster end-to-end chain completed.`` plus
the path to the remastered video and the translated ``_vi.srt``.

## R7.5 — AGGRESSIVE preset behaviour

Independently verified by ``server/tests/test_remaster.py::TestRemasterVideo::
test_aggressive_preset_emits_clear_warning_R7_5``: the AGGRESSIVE preset
emits a WARNING-level log message that "TTS audio replacement is not yet
implemented", does **not** invoke any audio substitution (FFmpeg command uses
``-c:a copy``), and falls back to LIGHT-style subtitle burn-in.
