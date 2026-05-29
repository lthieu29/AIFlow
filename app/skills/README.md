# Skills — Style Packs for AIFlow

Skills are **data-only** packages that define visual style, character traits, and voice presets.

## Structure

Each skill is a folder with:
- `manifest.yaml` — metadata (name, version, author)
- `style.json` — Veo3 style lock (camera, lighting, color grading)
- `prefix.md` — prompt prefix for all scenes
- `character.md` — character description template
- `scene.md` — scene composition rules
- `motion.md` — camera motion presets
- `voice.yaml` — TTS voice mapping (narrator, characters)

## Base Rules

`_base/` contains shared rules applied to ALL skills:
- `camera_lock.md` — prevent camera drift
- `safety.md` — content safety guidelines
- `continuity.md` — continuity layer rules

## MVP Skill

`ecommerce-fashion/` — first skill for Phase 4.1 (product video generation)

## Phase Status

- **Phase 4.0**: Skill framework (not started)
- **Phase 4.1**: ecommerce-fashion skill (not started)
