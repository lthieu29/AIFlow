# Scripts — Dev Tools & Smoke Tests

Utility scripts for development and testing.

## Phase 0 Scripts

- `smoke_phase0.py` — Phase 0 acceptance test (6 checks)

## Future Scripts

- `test_gemini.py` — Gemini API smoke test (Phase 0.3)
- `test_gen_image.py` — Veo3 image gen test (Phase 0.5)
- `seed_db.py` — Seed database with sample data (Phase 1+)
- `check_upstream_updates.py` — Monitor Douyin_TikTok_API for signing changes (Phase 4.5)

## Usage

```powershell
# Run smoke test
python scripts/smoke_phase0.py

# Expected: 🎉 Phase 0 PASSED (6/6 checks)
```
