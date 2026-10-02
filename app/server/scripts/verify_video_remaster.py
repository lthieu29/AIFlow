"""End-to-end verification for the ``video_remaster`` flow (R7).

Runs the full URL->video chain for preset ``LIGHT`` (and optionally
``TRANSLATE_ONLY``):

    download (retry + timeout) -> get subtitles (extract -> transcribe) ->
    translate to Vietnamese (Gemini, optional) -> burn subtitles -> output file

Usage::

    # Live verification against a real Bilibili/Douyin URL (R7.6):
    python server/scripts/verify_video_remaster.py --url "https://www.bilibili.com/video/BVxxxx"

    # Local-file fallback when signing/download is blocked (R7.9):
    python server/scripts/verify_video_remaster.py --local-file path/to/clip.mp4

    # Choose preset (default: light):
    python server/scripts/verify_video_remaster.py --local-file clip.mp4 --preset translate_only

Behaviour:
- On download/signing failure for a real URL, prints a clear, human-readable
  error identifying the failure (R7.7) instead of producing empty output, and
  exits non-zero. The caller may then re-run with ``--local-file`` (R7.9).
- Writes a short acceptance report to ``--report`` (default
  ``docs/reviews/video-remaster-verification.md``) documenting the steps and
  outcome (R7.6).

Exit code 0 = verification passed; 1 = failed (download/signing or pipeline).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows so non-ASCII messages do not crash
# (Windows defaults to cp1252 which cannot encode characters such as the
# Unicode arrow).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover — best-effort
    pass

# ── Ensure project root is on sys.path when run as a script ──────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # app/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from server.content.base import AdapterError, AdapterInput  # noqa: E402
from server.content.crawlers.remaster import (  # noqa: E402
    RemasterConfig,
    RemasterPreset,
    VideoRemaster,
)
from server.content.adapters.video_remaster.adapter import (  # noqa: E402
    VideoRemasterAdapter,
    download_with_retry,
)
from server.content.crawlers.manager import DownloadManager  # noqa: E402


def _preset_from_str(value: str) -> RemasterPreset:
    return {
        "light": RemasterPreset.LIGHT,
        "translate_only": RemasterPreset.TRANSLATE_ONLY,
        "aggressive": RemasterPreset.AGGRESSIVE,
    }.get(value.lower(), RemasterPreset.LIGHT)


async def _verify_via_url(url: str, preset: str, workdir: Path) -> dict:
    """Run the full adapter flow against a real URL."""
    adapter = VideoRemasterAdapter()
    scene_list = await adapter.adapt(
        AdapterInput(
            source_type="video",
            raw_content=url,
            options={"preset": preset, "workdir": str(workdir)},
        )
    )
    return {
        "mode": "live-url",
        "source": url,
        "output_path": scene_list.metadata.get("output_path"),
        "translated_srt": scene_list.metadata.get("translated_srt"),
        "preset": scene_list.metadata.get("preset"),
    }


async def _verify_via_local_file(video: Path, preset: str, workdir: Path) -> dict:
    """Run the subtitle→translate→burn chain on a local file (skip download)."""
    cfg = RemasterConfig(preset=_preset_from_str(preset))
    remaster = VideoRemaster(cfg)
    result = await remaster.remaster(video, workdir)
    return {
        "mode": "local-file",
        "source": str(video),
        "output_path": str(result.output_path),
        "translated_srt": str(result.translated_srt),
        "preset": result.preset.value,
    }


def _write_report(report_path: Path, status: str, info: dict, error: str | None) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Video Remaster — End-to-End Verification (R7.6)",
        "",
        f"- Timestamp (UTC): {now}",
        f"- Status: {status}",
        f"- Mode: {info.get('mode', 'n/a')}",
        f"- Source: {info.get('source', 'n/a')}",
        f"- Preset: {info.get('preset', 'n/a')}",
        f"- Output video: {info.get('output_path', 'n/a')}",
        f"- Translated SRT: {info.get('translated_srt', 'n/a')}",
    ]
    if error:
        lines += ["", "## Failure detail", "", f"```\n{error}\n```"]
        lines += [
            "",
            "> Live download/signing failed (R7.7). Re-run with `--local-file` "
            "to verify the subtitle→translate→burn chain offline (R7.9).",
        ]
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


async def _main_async(args: argparse.Namespace) -> int:
    report_path = Path(args.report)

    if not args.url and not args.local_file:
        print("ERROR: provide --url (live) or --local-file (offline fallback).")
        return 2

    if args.workdir:
        workdir = Path(args.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        tmp_ctx = None
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="verify_remaster_")
        workdir = Path(tmp_ctx.name)

    try:
        if args.url:
            try:
                info = await _verify_via_url(args.url, args.preset, workdir)
            except AdapterError as exc:
                # R7.7 — clear, human-readable download/signing failure
                msg = f"{exc.code}: {exc.message} (details={exc.details})"
                print(f"DOWNLOAD/SIGNING FAILED — {msg}")
                _write_report(report_path, "FAILED (download/signing)", {"mode": "live-url", "source": args.url}, msg)
                print(
                    "Hint: re-run with --local-file <clip.mp4> to verify the "
                    "subtitle->translate->burn chain offline (R7.9)."
                )
                return 1
        else:
            video = Path(args.local_file)
            if not video.exists():
                print(f"ERROR: local file not found: {video}")
                return 2
            info = await _verify_via_local_file(video, args.preset, workdir)

        out = info.get("output_path")
        out_exists = bool(out) and Path(out).exists()
        if not out_exists and args.preset.lower() != "translate_only":
            print(f"FAILED — expected output video does not exist: {out}")
            _write_report(report_path, "FAILED (no output)", info, "Output video missing")
            return 1

        print("PASSED — video_remaster end-to-end chain completed.")
        for k, v in info.items():
            print(f"  {k}: {v}")
        _write_report(report_path, "PASSED", info, None)
        return 0
    finally:
        if tmp_ctx is not None and not args.keep:
            try:
                tmp_ctx.cleanup()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the video_remaster flow (R7).")
    parser.add_argument("--url", help="Real Bilibili/Douyin video URL (live verification).")
    parser.add_argument("--local-file", dest="local_file", help="Local video file (offline fallback).")
    parser.add_argument(
        "--preset",
        default="light",
        choices=["light", "translate_only", "aggressive"],
        help="Remaster preset (default: light).",
    )
    parser.add_argument("--workdir", help="Working directory (default: a temp dir).")
    parser.add_argument(
        "--report",
        default="docs/reviews/video-remaster-verification.md",
        help="Path to write the acceptance report.",
    )
    parser.add_argument("--keep", action="store_true", help="Keep the temp workdir.")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
