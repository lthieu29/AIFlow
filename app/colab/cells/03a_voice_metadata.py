"""Cell 3a — Voice metadata widgets (id, display name, language, gender).

Widgets được lưu vào _state để Cell 3e đọc giá trị final.
"""
import ipywidgets as widgets
from IPython.display import display

from cells._shared import _state

voice_id_input = widgets.Text(
    value='my-custom-voice', description='Voice ID:',
    style={'description_width': 'initial'},
    layout=widgets.Layout(width='400px'),
)
display_name_input = widgets.Text(
    value='Giọng custom của tôi', description='Display name:',
    style={'description_width': 'initial'},
    layout=widgets.Layout(width='400px'),
)
description_input = widgets.Textarea(
    value='Giọng nữ miền Bắc, ấm, narration video review.',
    description='Mô tả:',
    style={'description_width': 'initial'},
    layout=widgets.Layout(width='500px', height='80px'),
)
language_dd = widgets.Dropdown(
    options=[('Tiếng Việt', 'vi'), ('English', 'en'), ('Vi-En code-switch', 'vi-en')],
    value='vi', description='Ngôn ngữ:',
    style={'description_width': 'initial'},
)
gender_dd = widgets.Dropdown(
    options=[('Nữ', 'female'), ('Nam', 'male'), ('Trung tính', 'neutral')],
    value='female', description='Giới tính:',
    style={'description_width': 'initial'},
)

for w in (voice_id_input, display_name_input, description_input, language_dd, gender_dd):
    display(w)

_state['widgets_metadata'] = {
    'voice_id': voice_id_input,
    'display_name': display_name_input,
    'description': description_input,
    'language': language_dd,
    'gender': gender_dd,
}
