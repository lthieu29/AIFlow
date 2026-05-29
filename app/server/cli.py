"""AIFlow CLI — Click-based command-line interface.

Entry point: ``aiflow`` (registered in pyproject.toml [project.scripts]).

Commands:
    gen-clip    Generate a video clip from a start image + text prompt.

Usage::

    aiflow gen-clip \\
        --prompt "A serene mountain lake at sunrise" \\
        --start-image path/to/frame.png \\
        --output storage/output/ \\
        --aspect 9:16 \\
        --model VEO3 \\
        --quality fast
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _run(coro):
    """Run an async coroutine from synchronous Click command."""
    return asyncio.run(coro)


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
def aiflow() -> None:
    """AIFlow — personal AI video generation tool."""
    pass


# ── gen-clip command ──────────────────────────────────────────────────────────


@aiflow.command("gen-clip")
@click.option(
    "--prompt",
    required=True,
    type=str,
    help="Text prompt for video generation.",
)
@click.option(
    "--start-image",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the start frame image.",
)
@click.option(
    "--output",
    default="storage/output/",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the generated video.",
)
@click.option(
    "--aspect",
    default="9:16",
    show_default=True,
    type=str,
    help="Aspect ratio (e.g. '9:16' or '16:9').",
)
@click.option(
    "--model",
    default="VEO3",
    show_default=True,
    type=str,
    help="Video model key (e.g. VEO3, VEO3_LITE, VEO3_QUALITY).",
)
@click.option(
    "--quality",
    default="fast",
    show_default=True,
    type=click.Choice(["lite", "fast", "quality"], case_sensitive=False),
    help="Quality level.",
)
def gen_clip(
    prompt: str,
    start_image: Path,
    output: Path,
    aspect: str,
    model: str,
    quality: str,
) -> None:
    """Generate a video clip from a start image and text prompt.

    Submits an async image-to-video request to Google Flow via the AIFlow
    Bridge extension, polls until complete, and downloads the result.

    Example::

        aiflow gen-clip \\
            --prompt "A serene mountain lake at sunrise" \\
            --start-image frame.png
    """
    _run(_gen_clip_async(prompt, start_image, output, aspect, model, quality))


async def _gen_clip_async(
    prompt: str,
    start_image: Path,
    output: Path,
    aspect: str,
    model: str,
    quality: str,
) -> None:
    """Async implementation of the gen-clip command."""
    try:
        from tqdm import tqdm
    except ImportError:
        click.echo("Error: tqdm is required. Install with: pip install tqdm>=4.66", err=True)
        sys.exit(1)

    # ── Step 1: Load settings ─────────────────────────────────────────────────
    click.echo("Loading settings...")
    try:
        from server.config import ConfigError, load_settings
        settings = load_settings()
    except Exception as exc:
        click.echo(f"Error loading settings: {exc}", err=True)
        sys.exit(1)

    # ── Step 2: Bootstrap DB schema ───────────────────────────────────────────
    click.echo("Bootstrapping database schema...")
    try:
        from server.db.session import bootstrap_schema
        bootstrap_schema(settings)
    except Exception as exc:
        click.echo(f"Error bootstrapping DB: {exc}", err=True)
        sys.exit(1)

    # ── Step 3: Create Project in DB ──────────────────────────────────────────
    from sqlmodel import Session

    from server.db.models.project import Project
    from server.db.session import get_engine
    from server.pipeline.job_manager import add_job_log, create_job, update_job_status

    engine = get_engine(settings)

    short_id = "p_" + uuid.uuid4().hex[:4]
    title = prompt[:80]  # truncate long prompts for the title

    with Session(engine) as session:
        project = Project(
            short_id=short_id,
            title=title,
            aspect=aspect,
            adapter="cli",
            status="draft",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id
        click.echo(f"Created project: {project.short_id} (id={project_id})")

    # ── Step 4: Create Job in DB ──────────────────────────────────────────────
    with Session(engine) as session:
        job = create_job(session, project_id=project_id, job_type="gen_video")
        job_id = job.id
        add_job_log(session, job_id, "INFO", f"CLI gen-clip started: prompt={prompt!r:.80}")
        click.echo(f"Created job: id={job_id} (type=gen_video, status=pending)")

    # ── Step 5: Wait for extension connected + token captured ─────────────────
    from server.flow.client import FlowClient

    client = FlowClient()

    click.echo("Waiting for AIFlow Bridge extension to connect...")
    try:
        with tqdm(
            total=None,
            desc="Extension",
            unit="s",
            bar_format="{desc}: {elapsed}s elapsed",
            dynamic_ncols=True,
        ) as pbar:
            # Poll with progress updates
            timeout = 120.0
            start = time.monotonic()
            while not client.is_connected():
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    raise TimeoutError(
                        f"Extension did not connect within {timeout:.0f}s. "
                        "Make sure the AIFlow Bridge extension is installed and enabled, "
                        "and that the AIFlow server is running."
                    )
                pbar.set_description(f"Extension (waiting {elapsed:.0f}s)")
                await asyncio.sleep(1.0)
            pbar.set_description("Extension connected ✓")
    except TimeoutError as exc:
        click.echo(f"\nError: {exc}", err=True)
        with Session(engine) as session:
            update_job_status(session, job_id, "failed", finished_at=_utcnow())
            add_job_log(session, job_id, "ERROR", f"Extension connection timeout: {exc}")
        sys.exit(1)

    click.echo("Waiting for Bearer token...")
    try:
        with tqdm(
            total=None,
            desc="Token",
            unit="s",
            bar_format="{desc}: {elapsed}s elapsed",
            dynamic_ncols=True,
        ) as pbar:
            timeout = 120.0
            start = time.monotonic()
            while client.get_token() is None:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    raise TimeoutError(
                        f"No Bearer token captured within {timeout:.0f}s. "
                        "Make sure you are logged in to labs.google in Chrome."
                    )
                pbar.set_description(f"Token (waiting {elapsed:.0f}s)")
                await asyncio.sleep(1.0)
            pbar.set_description("Token captured ✓")
    except TimeoutError as exc:
        click.echo(f"\nError: {exc}", err=True)
        with Session(engine) as session:
            update_job_status(session, job_id, "failed", finished_at=_utcnow())
            add_job_log(session, job_id, "ERROR", f"Token capture timeout: {exc}")
        sys.exit(1)

    # ── Step 6: Submit gen_video request ──────────────────────────────────────
    from server.flow.sdk import FlowSDK, extract_video_operations

    sdk = FlowSDK()

    click.echo(f"Submitting video generation request (model={model}, quality={quality}, aspect={aspect})...")
    try:
        operation_name = await sdk.gen_video(
            start_image=start_image,
            prompt=prompt,
            aspect=aspect,
            model=model,
            quality=quality,
        )
    except Exception as exc:
        click.echo(f"\nError submitting video request: {exc}", err=True)
        with Session(engine) as session:
            update_job_status(session, job_id, "failed", finished_at=_utcnow())
            add_job_log(session, job_id, "ERROR", f"gen_video submission failed: {exc}")
        sys.exit(1)

    click.echo(f"Submitted. Operation: {operation_name}")

    # ── Step 7: Update Job status to "running" ────────────────────────────────
    with Session(engine) as session:
        update_job_status(session, job_id, "running", started_at=_utcnow())
        add_job_log(session, job_id, "INFO", f"Video generation running. operation_name={operation_name}")

    # ── Step 8: Poll check_async every 5s with tqdm progress bar ─────────────
    from server.pipeline.poller import MAX_POLL_ATTEMPTS, POLL_INTERVAL_SECONDS

    click.echo("Polling for completion...")
    final_media_entries = None
    poll_error: Optional[str] = None

    with tqdm(
        total=MAX_POLL_ATTEMPTS,
        desc="Polling",
        unit="poll",
        dynamic_ncols=True,
    ) as pbar:
        for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
            pbar.set_description(f"Polling (attempt {attempt}/{MAX_POLL_ATTEMPTS})")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

            try:
                resp = await sdk.check_async(operation_name)
            except Exception as exc:
                pbar.write(f"  Poll error (attempt {attempt}): {exc} — retrying...")
                pbar.update(1)
                continue

            ops = extract_video_operations(resp, requested=[operation_name])
            if not ops:
                pbar.update(1)
                continue

            op_result = ops[0]
            done = op_result.get("done", False)
            error = op_result.get("error")
            media_entries = op_result.get("media_entries", [])

            pbar.update(1)

            if not done:
                status_str = op_result.get("status", "pending")
                pbar.set_postfix_str(status_str)
                continue

            # Done
            if error:
                poll_error = error
            else:
                final_media_entries = media_entries
            break
        else:
            poll_error = (
                f"Polling timeout: exceeded {MAX_POLL_ATTEMPTS} attempts "
                f"({MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s)"
            )

    # ── Step 9 & 10: Download video + update Job status ───────────────────────
    if poll_error or not final_media_entries:
        reason = poll_error or "Operation completed but no media entries returned"
        click.echo(f"\nError: Video generation failed — {reason}", err=True)
        with Session(engine) as session:
            update_job_status(session, job_id, "failed", finished_at=_utcnow())
            add_job_log(session, job_id, "ERROR", f"Video generation failed: {reason}")
        sys.exit(1)

    entry = final_media_entries[0]
    signed_url = entry.get("url")
    if not signed_url:
        reason = "Operation completed but no signed URL in media entry"
        click.echo(f"\nError: {reason}", err=True)
        with Session(engine) as session:
            update_job_status(session, job_id, "failed", finished_at=_utcnow())
            add_job_log(session, job_id, "ERROR", reason)
        sys.exit(1)

    # Ensure output directory exists
    output.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    out_path = output / f"video_{short_id}_{timestamp}.mp4"

    click.echo(f"Downloading video to {out_path}...")
    try:
        from server.flow.downloader import download_video
        saved_path = await download_video(signed_url, out_path)
    except RuntimeError as exc:
        click.echo(f"\nError downloading video: {exc}", err=True)
        with Session(engine) as session:
            update_job_status(session, job_id, "failed", finished_at=_utcnow())
            add_job_log(session, job_id, "ERROR", f"Video download failed: {exc}")
        sys.exit(1)

    # ── Step 10: Update Job to success ────────────────────────────────────────
    with Session(engine) as session:
        update_job_status(session, job_id, "success", finished_at=_utcnow())
        add_job_log(
            session,
            job_id,
            "INFO",
            f"Video generation completed. Saved to: {saved_path}",
        )

    # ── Step 11: Print result path ────────────────────────────────────────────
    click.echo(f"\n✅ Done! Video saved to: {saved_path}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Package entry point registered in pyproject.toml [project.scripts]."""
    aiflow()


if __name__ == "__main__":
    main()
