# Base skill prefix — Veo 8-element foundation

This base prefix is prepended to every skill that declares `extends: _base`.
It sets the default Veo3 prompt skeleton that child skills refine.

## 1. Shot framing & motion
Locked-off static camera by default. Use deliberate shot framing — extreme
wide, wide, medium, close-up, or extreme close-up — chosen to serve the
beat. No handheld shake, no dolly, no pan, no tilt unless the scene motion
hint explicitly says so.

## 2. Style
Match the named style of the scene. State the style explicitly
(photorealistic, cinematic, documentary, anime, ink-wash, claymation,
film noir, Wes Anderson, etc.) — never leave it implicit.

## 3. Lighting
Name a concrete light source: golden hour sunlight, neon spill, soft
window light, hard key light, overcast diffuser, candlelight, tungsten
lamp, fluorescent overhead, volumetric beam. Avoid generic phrases like
"dramatic lighting" alone.

## 4. Character
Describe the subject before the action: "a mid-30s woman with short dark
hair and a navy coat" — not "a woman walks". Anchor identity early so
downstream Veo3 frames stay consistent.

## 5. Location
Bind the scene to a real, specific place: "bustling NYC street at noon",
"empty marble bathroom under skylight", "rural ramen stall at twilight".
Specificity stabilises lighting and prop logic.

## 6. Action
One primary action per 8-second clip, resolved cleanly. Multiple
micro-motions must read as a single beat — choose the lead motion and let
the rest support it.

## 7. Dialogue (only when the scene calls for it)
Keep dialogue under 8 seconds (one or two short lines). Place it on its
own line prefixed `Dialogue:` so Veo3 can parse it precisely.

## 8. Audio (always present when the scene has sound)
Layer environmental sound + directional sfx + optional music on its own
line prefixed `Audio:`. Be specific: not "ambient noise" but "wind through
grass, distant gull cries, soft jazz piano".

## Hard constraints (always)
- No watermark.
- No logo.
- No subtitle or text overlay.
- Subjects fully clothed unless the artistic context requires otherwise.
- Photorealistic or named illustration style only — no real identifiable
  persons, no copyrighted characters, no NSFW content, no weapons.

## Continuity
Maintain consistent lighting direction, color temperature, and background
across consecutive scenes within the same location. When location changes,
introduce a new visual style block but keep it internally consistent.
