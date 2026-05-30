# K-Drama Romance — Scene template

> Template the EPUB adapter fills per shot when chunking chapters into scenes.
> Each scene maps to one ~8s Veo3 clip. Camera is dynamic for this skill
> (manifest overrides the `_base` static default).

## Shot skeleton

- **Beat**: {{BEAT}}  (establishing / dialogue / reaction / turning-point)
- **Characters**: {{CHARACTERS}}  (refs to character.md identities)
- **Action**: {{ACTION}}  (one emotional beat — see motion.md)
- **Location**: {{LOCATION}}  (indoor_home / indoor_cafe / outdoor_night / …)
- **Mood**: {{MOOD}}  (romantic / bittersweet / tense / hopeful)
- **Time of day**: {{TIME}}  (drives lighting — golden hour, blue hour, night)

## Beat conventions

| Beat | Goal | Camera |
|------|------|--------|
| establishing | set place + mood | slow push-in or wide hold |
| dialogue | carry the conversation | medium close-up, rack focus |
| reaction | land the emotion | extreme close-up on eyes |
| turning-point | pivotal story moment | slow-motion, dissolve out |

## Continuity rules

- Reset the scene chain only when `location_hint` actually changes category
- Keep character identity, wardrobe, and lighting consistent within a location
- Use match-cut on eye contact for romantic beats
- Leave space for chapter-title and lower-third overlays at episode boundaries
