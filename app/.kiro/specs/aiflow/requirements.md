# AIFlow — Requirements

> **Spec source**: [docs/PLAN.md](../../../docs/PLAN.md)
> **Status**: Approved (v1.3)
> **Detail specs**: [docs/00-11](../../../docs/)

## Overview

AIFlow is a personal AI video generation tool that transforms inputs (images, scripts, articles, novels, video URLs) into polished videos using Google Veo3 + Gemini + TTS. It combines 8 reference projects into one cohesive Windows-native pipeline.

## Core Requirements

### R1 — Personal use only
- No public deployment, no commercial use
- Single-user local install on Windows

### R2 — Native Windows, no WSL
- Runs directly on Windows 10/11
- Chrome extension on Windows host (no proxy needed)

### R3 — Stack constraints
- Python 3.12+ (required for LMDeploy GPU fast mode in TTS)
- React 18 + Vite for UI (Phase 5)
- Chrome MV3 extension (Edge compatible)
- SQLite as only datastore

### R4 — Cost ceiling
- Google Flow Pro plan: $20/month
- Gemini API: free tier (AI Studio)
- All other components free/local (TTS, Whisper, FFmpeg)

### R5 — Input adapters (6 total)
- `script-direct`: existing SceneList JSON
- `ecommerce-product`: product image → TikTok video
- `narrative-script`: markdown script → video
- `blog-article`: URL → explainer video
- `storyboard-manual`: JSON storyboard → video
- `video-remaster`: Bilibili/Douyin URL → re-cut with VN sub
- `epub-novel`: EPUB → multi-episode drama (Phase 6)

### R6 — Continuity guarantees (4 layers)
- Style lock (camera, lighting, color)
- Asset lock (character, product, location ref images)
- Scene chain (start_frame from previous scene's last frame)
- Audio continuity (BGM mood, voice tone)

### R7 — Quality gates (G1-G6)
- G1: SceneList structure validation
- G2: Asset ref user approval (with G2.8 SLA timeout)
- G3: Per-scene quality (auto retry max 2)
- G4: Audio quality
- G5: Subtitle quality
- G6: Final video QA

### R8 — TTS dual backend
- VieNeu-TTS local (primary, voice cloning support)
- edge_tts online (fallback)
- Auto detect GPU/CPU
- Default voice: `Binh` (VieNeu Vietnamese male)

### R9 — Custom voice training
- Hybrid approach: LoRA fine-tune (≥30 min data) OR persistent embedding (3-15s ref)
- Colab notebook with GPU presets (T4/L4/A100/H100)
- Voice package zip schema for import

### R10 — Visual layer (mini-hyperframes)
- HTML+GSAP templates rendered via Playwright
- 5 templates: intro, outro, lower-third, chapter, product-card
- Overlay on Veo3 video with alpha channel

### R11 — Output formats
- Primary: MP4 (final.mp4 in storage/output/)
- Secondary: CapCut draft (Phase 7)
- Subtitle: SRT export

### R12 — Skills as data
- Skills are folders with YAML/JSON/MD files (no Python code)
- MVP skill: `ecommerce-fashion`
- Phase 6+ skills: `kdrama-romance`, `explainer-tech`, `cinematic-action`

## Non-functional requirements

### NFR1 — Resume after crash
- Job state machine persisted in SQLite
- Pipeline can resume from last successful gate

### NFR2 — Re-gen single scene
- Without re-rendering all previous scenes
- Maintains continuity chain

### NFR3 — Bounded cascade
- Max 2 retries per scene
- Max 5 retries per project
- Recovery path documented

### NFR4 — Fail-fast configuration
- Missing required env vars → raise on startup
- No silent defaults for secrets

### NFR5 — Friendly errors
- Gemini quota errors → user-readable message
- Extension disconnect → actionable popup hint
- DB bootstrap fail → clear instruction

### NFR6 — Audit trail
- Every Job has JobLog entries
- Every TTS attempt tracked (which backend, RTF)
- Every Veo3 call has prompt + response saved

## Out of scope

- Multi-user / cloud deployment
- Real-time collaboration
- Mobile app
- Voice models other than Vietnamese (Phase 1-5; multi-language is post-v1.0)

## Reference projects (read-only)

8 reference projects in `D:\Project\AIFlow\` provide code to lift/port:
- `flowboard` — Veo3 extension + flow_client
- `hyperframes` — visual layer concept
- `MoneyPrinterTurbo` — TTS + Whisper
- `daihuo-jianshou` — prompts + composer
- `VectCutAPI` — CapCut export
- `Toonflow-app` — EPUB extraction
- `Galaxy-*` — yt-dlp/aria2c patterns
- `Douyin_TikTok_Download_API` — Bilibili/Douyin crawlers
- `downkyi-2.0.x` — Bilibili URL parser
