"""Cell 5a — Load VieNeu inference engine (apply LoRA nếu Path A)."""
from cells._shared import BASE_MODEL, _state, banner, require_state

require_state('mode', 'config', 'voices_json_path')

if _state.get('engine') is not None:
    print('✅ Engine đã load (cached). Skip.')
else:
    print('📥 Load VieNeu inference engine (~30-60s lần đầu)...')
    from vieneu import Vieneu

    engine = Vieneu(
        mode='standard',
        backbone_repo=BASE_MODEL,
        backbone_device='cuda',
        codec_repo='neuphonic/neucodec-onnx-decoder-int8',
        codec_device='cpu',
    )

    if _state['mode'] == 'lora':
        lora_dir = _state['lora_dir']
        print(f'🎯 Apply LoRA adapter: {lora_dir}')
        engine.load_lora_adapter(str(lora_dir))
    else:
        # Path B — load voices.json thủ công vì không có repo
        engine._load_voices_from_file(_state['voices_json_path'], clear_existing=False)

    _state['engine'] = engine
    banner('✅ Engine ready')
