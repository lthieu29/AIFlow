"""Cell 3c — Quality preset (GPU-aware).

Auto-suggest preset theo RUNTIME tier. User override trong dropdown.
Bỏ qua nếu dùng Path B (không cần preset).
"""
import ipywidgets as widgets
from IPython.display import display

from cells._shared import PRESETS, RUNTIME, TIER_TO_PRESET, _state

if _state.get('mode') == 'embedding':
    print('ℹ️ Bạn đang ở Path B — bỏ qua cell này, chạy Cell 3e.')
else:
    suggested = TIER_TO_PRESET.get(RUNTIME.get('tier', 'cpu'), 'conservative')
    print(f'💡 Auto-suggest: {PRESETS[suggested]["label"]}')
    print(f'   (theo GPU {RUNTIME["name"]} — {RUNTIME["vram_gb"]} GB VRAM)\n')

    preset_dd = widgets.Dropdown(
        options=[(v['label'], k) for k, v in PRESETS.items()],
        value=suggested, description='Preset:',
        style={'description_width': 'initial'},
        layout=widgets.Layout(width='550px'),
    )
    preset_info = widgets.HTML()

    def _update_info(change=None):
        p = PRESETS[preset_dd.value]
        eff_batch = p['batch_size'] * p['grad_accum']
        warn = ''
        if p['min_vram_gb'] > RUNTIME['vram_gb']:
            warn = (
                f"<br><b style='color:#d33'>⚠️ Preset cần ≥{p['min_vram_gb']} GB VRAM, "
                f"hiện chỉ {RUNTIME['vram_gb']} GB. Có thể OOM — giảm preset.</b>"
            )
        preset_info.value = (
            f"<div style='padding:10px; background:#f5f5f5; border-radius:4px; "
            f"margin-top:8px; font-family:monospace;'>"
            f"<b>{p['label']}</b><br>"
            f"{p['desc']}<br><br>"
            f"batch_size={p['batch_size']} × grad_accum={p['grad_accum']} = "
            f"effective batch <b>{eff_batch}</b><br>"
            f"max_steps={p['max_steps']}, lr={p['learning_rate']}, "
            f"warmup={p['warmup_ratio']}<br>"
            f"lora_r={p['lora_r']}, lora_alpha={p['lora_alpha']}, "
            f"dropout={p['lora_dropout']}"
            f"{warn}</div>"
        )

    preset_dd.observe(_update_info, names='value')
    _update_info()
    display(preset_dd, preset_info)

    _state['widget_preset'] = preset_dd
