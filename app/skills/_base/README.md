# `_base` skill

The `_base` skill is the root of the skill inheritance hierarchy. It is **not
a standalone skill** — it defines shared defaults and safety rules that all
other skills inherit.

## Files

| File | Purpose |
|------|---------|
| `manifest.yaml` | Base manifest: camera_lock, safety_level, default options |
| `prefix.md` | Prompt prefix: camera lock rules, safety rules, continuity rules |
| `style.json` | Neutral base style (photorealistic, natural lighting, neutral palette) |
| `README.md` | This file |

## Inheritance

Skills declare inheritance with `extends: _base` in their `manifest.yaml`.
The `SkillLoader` merges the base prefix with the child skill's prefix:

```
final_prefix = _base/prefix.md + "\n\n" + skill/prefix.md
```

Style fields from the child skill override the base style fields.

## Rules enforced by `_base`

### Camera lock
All scenes default to a static locked-off camera. Adapters may override
`camera="dynamic"` for individual scenes when motion is required.

### Safety
- No real identifiable persons
- No copyrighted characters or brand logos
- No NSFW content
- No violence or weapons

### Continuity
- Consistent lighting direction within a location block
- Consistent color temperature within a location block
- Location change triggers a continuity chain reset

## Adding a new skill

1. Create `skills/{skill-name}/` directory
2. Create `manifest.yaml` with `extends: _base`
3. Create `style.json` with skill-specific art style
4. Create `prefix.md` with skill-specific prompt additions
5. Run `SkillLoader.validate_skill("{skill-name}")` to check for errors

See `skills/ecommerce-fashion/` for a complete example.
