"""Cell 3d — Advanced hyperparam override.

Chỉ chạy nếu chọn preset='advanced' ở Cell 3c. Cho phép chỉnh từng hyperparam.
"""
import ipywidgets as widgets
from IPython.display import display

from cells._shared import _state

if _state.get('mode') == 'embedding':
    print('ℹ️ Path B — bỏ qua.')
elif not _state.get('widget_preset'):
    print('❌ Chưa chạy Cell 3c.')
elif _state['widget_preset'].value != 'advanced':
    print(f'ℹ️ Preset hiện tại = "{_state["widget_preset"].value}" — bỏ qua cell Advanced.')
else:
    common_layout = widgets.Layout(width='500px')
    style = {'description_width': '160px'}

    adv = {
        'batch_size': widgets.IntSlider(
            value=4, min=1, max=32, step=1,
            description='batch_size', style=style, layout=common_layout,
        ),
        'grad_accum': widgets.IntSlider(
            value=1, min=1, max=8, step=1,
            description='grad_accum', style=style, layout=common_layout,
        ),
        'max_steps': widgets.IntSlider(
            value=4000, min=500, max=20000, step=500,
            description='max_steps', style=style, layout=common_layout,
        ),
        'learning_rate': widgets.FloatLogSlider(
            value=2e-4, min=-5, max=-3, step=0.1,
            description='learning_rate', style=style, layout=common_layout,
        ),
        'warmup_ratio': widgets.FloatSlider(
            value=0.05, min=0.0, max=0.2, step=0.01,
            description='warmup_ratio', style=style, layout=common_layout,
        ),
        'lora_r': widgets.IntSlider(
            value=16, min=4, max=64, step=4,
            description='lora_r', style=style, layout=common_layout,
        ),
        'lora_alpha': widgets.IntSlider(
            value=32, min=8, max=128, step=8,
            description='lora_alpha', style=style, layout=common_layout,
        ),
        'lora_dropout': widgets.FloatSlider(
            value=0.05, min=0.0, max=0.3, step=0.01,
            description='lora_dropout', style=style, layout=common_layout,
        ),
    }
    for w in adv.values():
        display(w)

    _state['widgets_advanced'] = adv
    print('\nChỉnh xong rồi chạy Cell 3e (Save config).')
