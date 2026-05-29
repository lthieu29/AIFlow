"""Cell 5b — Generate sample audio + play inline.

Chạy nhiều lần với text khác nhau để nghe thử voice trước khi export.
"""
import subprocess as sp

import ipywidgets as widgets
import soundfile as sf
from IPython.display import Audio, clear_output, display

from cells._shared import WORK_DIR, _state, require_state

require_state('mode', 'config', 'engine')

text_input = widgets.Textarea(
    value='Xin chào, đây là giọng nói được tạo bởi AIFlow. '
    'Hôm nay là một ngày đẹp trời.',
    description='Test text:',
    layout=widgets.Layout(width='600px', height='80px'),
    style={'description_width': 'initial'},
)
gen_btn = widgets.Button(description='🎵 Generate', button_style='primary')
out = widgets.Output()


def _generate(_):
    with out:
        clear_output()
        text = text_input.value.strip()
        if not text:
            print('❌ Text rỗng'); return

        engine = _state['engine']
        cfg = _state['config']
        try:
            voice_data = engine.get_preset_voice(cfg['voice_id'])
        except Exception as e:
            print(f'❌ Voice không tìm thấy: {e}'); return

        print(f'🎵 Synthesizing: {text[:60]}...')
        try:
            audio = engine.infer(text=text, voice=voice_data, apply_watermark=False)
        except Exception as e:
            print(f'❌ Synth fail: {e}'); return

        # Save WAV để play
        sample_path = WORK_DIR / 'test_sample.wav'
        sf.write(str(sample_path), audio, engine.sample_rate, subtype='PCM_16')

        duration = len(audio) / engine.sample_rate
        print(f'✅ Generated {duration:.1f}s')
        display(Audio(str(sample_path)))

        # Tạo demo.mp3 cho cell 6
        demo_mp3 = WORK_DIR / 'demo.mp3'
        sp.run(
            ['ffmpeg', '-y', '-i', str(sample_path),
             '-codec:a', 'libmp3lame', '-b:a', '192k', '-ac', '1', str(demo_mp3)],
            check=True, capture_output=True,
        )
        _state['demo_mp3'] = demo_mp3
        _state['demo_text'] = text


gen_btn.on_click(_generate)
display(text_input, gen_btn, out)
print('Click "Generate" — chạy nhiều lần với text khác nếu muốn.')
