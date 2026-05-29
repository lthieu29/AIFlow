"""Cell 3e — Validate + collect tất cả widgets thành config dict."""
from cells._shared import PRESETS, _state, banner, validate_voice_id

mw = _state.get('widgets_metadata')
if not mw:
    raise SystemExit('❌ Chạy Cell 3a trước.')

vid = mw['voice_id'].value.strip()
ok, msg = validate_voice_id(vid)
if not ok:
    raise SystemExit(f'❌ {msg}')

cfg = {
    'voice_id': vid,
    'display_name': mw['display_name'].value.strip() or vid,
    'description': mw['description'].value.strip(),
    'language': mw['language'].value,
    'gender': mw['gender'].value,
}

if _state['mode'] == 'lora':
    pw = _state.get('widget_preset')
    if not pw:
        raise SystemExit('❌ Chạy Cell 3c trước.')
    preset_key = pw.value
    base = dict(PRESETS[preset_key])

    if preset_key == 'advanced':
        adv = _state.get('widgets_advanced')
        if not adv:
            raise SystemExit('❌ Chọn Advanced nhưng chưa chạy Cell 3d.')
        for k, w in adv.items():
            base[k] = w.value

    cfg['preset_key'] = preset_key
    cfg['hyperparams'] = {
        'batch_size': int(base['batch_size']),
        'grad_accum': int(base['grad_accum']),
        'max_steps': int(base['max_steps']),
        'learning_rate': float(base['learning_rate']),
        'warmup_ratio': float(base['warmup_ratio']),
        'lora_r': int(base['lora_r']),
        'lora_alpha': int(base['lora_alpha']),
        'lora_dropout': float(base['lora_dropout']),
    }
    eff_batch = cfg['hyperparams']['batch_size'] * cfg['hyperparams']['grad_accum']

    banner(f'✅ Path A — {base["label"]}')
    print(f'   voice_id:       {cfg["voice_id"]}')
    print(f'   display_name:   {cfg["display_name"]}')
    print(f'   language:       {cfg["language"]}')
    print(f'   gender:         {cfg["gender"]}')
    print(f'   batch (effective): {eff_batch}')
    for k, v in cfg['hyperparams'].items():
        print(f'   {k:18s}: {v}')

else:
    rt = _state.get('widget_ref_text')
    if not rt or not rt.value.strip():
        raise SystemExit('❌ Path B cần ref_text — chạy Cell 3b và paste transcript.')
    cfg['ref_text'] = rt.value.strip()

    banner('✅ Path B — Persistent embedding')
    print(f'   voice_id:    {cfg["voice_id"]}')
    print(f'   ref_text:    {cfg["ref_text"][:80]}...')

_state['config'] = cfg
print('\nNext: Cell 4 — train/encode')
