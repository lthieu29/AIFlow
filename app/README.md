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

- **Phase 0** (Setup): ⚪ In progress
- **Phase 1** (Core video flow): ⚪ Not started
- **Phase 2** (Continuity engine): ⚪ Not started
- **Phase 3** (Audio + TTS): ⚪ Not started
- **Phase 4** (Content adapters): ⚪ Not started
- **Phase 5** (UI): ⚪ Not started

## License

Personal use only. See [`LICENSE`](LICENSE) for details.

Third-party components: see [`LICENSE_NOTICES.md`](LICENSE_NOTICES.md)
