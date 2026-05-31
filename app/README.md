# AIFlow

Personal AI video generation tool — combines Veo3, Gemini, and TTS into a seamless pipeline.

## What is this?

AIFlow transforms ideas into videos:
- **Input**: Product images, scripts, articles, or even novels
- **Output**: Polished video with AI-generated visuals, voiceover, and subtitles

Built for personal use, integrating 8 reference projects into one cohesive system.

## Quick Start

### Prerequisites

- **Python 3.12+** (required for LMDeploy GPU fast mode)
- **Chrome browser** (for Veo3 token capture)
- **Google Flow Pro plan** ($20/month) at [labs.google/fx/tools/flow](https://labs.google/fx/tools/flow)
- **Gemini API key** (free tier) from [aistudio.google.com](https://aistudio.google.com)

### Setup

1. **Clone and setup environment**:
```powershell
cd D:\Project\AIFlow\app
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

2. **Configure secrets**:
```powershell
copy .env.example .env
# Edit .env and fill in:
# - AIFLOW_GEMINI_API_KEY
# - AIFLOW_FLOW_PLAN=Pro
```

3. **Load Chrome extension**:
   - Open `chrome://extensions`
   - Enable "Developer mode"
   - Click "Load unpacked"
   - Select `D:\Project\AIFlow\app\extension`

4. **Start agent**:
```powershell
python -m server.main
```

5. **Open Flow tab**:
   - Navigate to [labs.google/fx/tools/flow](https://labs.google/fx/tools/flow)
   - Extension will capture your Bearer token automatically

6. **Run smoke test**:
```powershell
python scripts/smoke_phase0.py
```

Expected: `🎉 Phase 0 PASSED (6/6 checks)`

## Documentation

Full specs and design docs: [`docs/PLAN.md`](docs/PLAN.md)

## Project Status

- **Phase 0** (Setup): ✅ Done
- **Phase 1–4.5** (Core flow + continuity + audio + adapters): ✅ Done
- **Phase 5** (UI): ⚪ Not started
- **Phase 6** (EPUB novel): ⚪ Not started
- **Phase 7** (CapCut export): ✅ Done

### Active spec — `content-expansion`

Three orthogonal expansion axes are complete (no pipeline-core changes):

- **Adapter axis** — 7 new adapters auto-discovered: `script_direct`,
  `video_remaster`, `document_summary`, `lyric_video`, `news_bulletin`,
  `podcast_caption`, `photo_slideshow`.
- **Skill axis** — 4 new data-only skills: `explainer-tech`,
  `cinematic-action`, `ecommerce-tech`, `ecommerce-food`.
- **Visual-layer axis** — 4 new HTML+GSAP overlay templates: `quote_card`,
  `stat_card`, `news_ticker`, `lyric_line`.

Test suite: 1939 passed, 1 skipped (Playwright render — opt-in heavy test).

The live `video_remaster` end-to-end verification (R7.6) is deferred — see
[`docs/reviews/video-remaster-verification.md`](docs/reviews/video-remaster-verification.md).
The remaining download → extract → translate → burn chain is verified offline
by [`server/tests/test_remaster_e2e.py`](server/tests/test_remaster_e2e.py).

## License

Personal use only. See [`LICENSE`](LICENSE) for details.

Third-party components: see [`LICENSE_NOTICES.md`](LICENSE_NOTICES.md)
