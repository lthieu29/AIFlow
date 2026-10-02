"""Cell 2d — Verify upload thành công."""
from cells._shared import _state, require_state

require_state('mode', 'data_ready')

print(f'✅ Data ready: mode={_state["mode"]}')
if _state['mode'] == 'lora':
    print(f'   {_state["num_samples"]} files, {_state["total_duration_sec"] / 60:.1f} phút')
else:
    print(f'   ref audio {_state["ref_duration_sec"]:.1f}s')
