# K-Drama Romance — Character template

> Template used by the EPUB adapter to describe a recurring character.
> Each character gets a hard identity anchor reused across every scene and
> episode so Veo3 i2v keeps the face consistent.

## Identity anchor (hard pin)

- **Name / alias**: {{NAME}}  (list aliases: {{ALIASES}})
- **Role**: {{ROLE}}  (lead / love interest / supporting)
- **Age range**: {{AGE}}
- **Build**: {{BUILD}}
- **Hair**: {{HAIR}}  (style + color)
- **Signature wardrobe**: {{WARDROBE}}
- **Defining feature**: {{FEATURE}}  (one memorable trait for recognisability)

## Emotional palette

- Default expression: {{DEFAULT_EXPRESSION}}  (e.g. "reserved, wistful")
- Emotional range: tender, longing, conflicted, joyful, heartbroken

## Framing per emotion

- Dialogue: medium close-up, soft key light
- Reaction / turning point: extreme close-up, shallow focus on eyes
- Establishing: medium-wide showing wardrobe + setting

## Hard constraints

- No real identifiable persons; original fictional likeness only
- Live-action drama look — no anime, cartoon, or illustration
- Keep identity consistent across all scenes and episodes (frontal neutral
  reference frame is the canonical anchor)
- Max characters per episode is capped by the manifest
  (`max_characters_per_episode`)
