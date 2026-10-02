# Explainer-tech — Scene template

> Template the adapter fills per shot. Each scene maps to one ~8s Veo3 clip.
> Camera is static for this skill (manifest inherits camera_lock: true from _base).

## Shot skeleton

- **Beat**: {{BEAT}}  (hook / concept / demo / proof / summary)
- **Subject**: {{SUBJECT}}  (device, screen, diagram, data visualisation, or presenter)
- **Action**: {{ACTION}}  (single clear explanatory action — see motion.md vocabulary)
- **Background**: {{LOCATION}}  (studio seamless, dark navy, or minimal desk setup)
- **Framing**: tight on screen/device for detail; medium for presenter; wide for context

## Beat conventions

| Beat | Goal | Typical duration |
|------|------|------------------|
| hook | state the problem or question clearly | 8s |
| concept | introduce the key idea or technology | 8s |
| demo | show the product or feature in action | 8s |
| proof | demonstrate real-world benefit or result | 8s |
| summary | reinforce the key takeaway | 6–8s |

## Composition rules

- One concept focus per scene — no information overload
- Locked-off static frame (camera lock from `_base`)
- Leave headroom for lower-third text overlays and stat cards
- Keep continuity: same presenter, same lighting, same background within a segment
- Screens and interfaces must be clearly legible — avoid glare or reflection
