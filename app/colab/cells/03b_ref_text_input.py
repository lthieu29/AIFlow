"""Cell 3b — (Path B only) Paste transcript của ref audio.

Bỏ qua nếu dùng Path A.
"""
import ipywidgets as widgets
from IPython.display import display

from cells._shared import _state

if _state.get('mode') != 'embedding':
    print('ℹ️ Bạn đang ở Path A — bỏ qua cell này, chạy Cell 3c.')
else:
    ref_text_input = widgets.Textarea(
        value='', description='Transcript:',
        placeholder='Paste văn bản chính xác 100% với audio đã upload',
        style={'description_width': 'initial'},
        layout=widgets.Layout(width='600px', height='100px'),
    )
    display(ref_text_input)
    _state['widget_ref_text'] = ref_text_input
