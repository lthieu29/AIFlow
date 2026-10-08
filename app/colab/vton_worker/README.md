# Dedicated FASHN virtual try-on worker

Use `serve_vton_api.ipynb` with the reviewed `aiflow-vton-worker.zip`. This is
a separate process and runtime from the SDXL image worker. Stop the earlier image
worker or use a fresh Colab runtime before loading VTON; two models must not occupy
the same GPU. Python 3.12 and the separately reviewed Colab Torch/TorchVision pair
are checked before model load.

Inputs are one fictional adult person image and one shop garment product shot on
a plain background. `generation_mode="vton"`, `subject_type="human"`, exactly two
references ordered `role="person"`, then `role="garment"`, `garment_category`
`tops|bottoms|one-pieces`, `garment_photo_type="flat-lay"`, native output 576x864.
Worn-model garment photos are rejected: they require a parser excluded because
its default weights inherit a noncommercial license. No parser model or source
is shipped, imported, downloaded or invoked in this worker.

The upstream maskless/flat-lay branch uses unchanged person and garment pixels.
The reviewed subset preserves model, CPU DWPose, grayscale pose drawing,
preprocessing and Euler rectified-flow equations. Person and garment inputs are
fit/padded preserving aspect ratio. The full native 576x864 generated canvas is
retained instead of upstream unpadding; outputs are never upscaled. FASHN has no
text conditioning: prompt, negative prompt and reference_strength are retained
as immutable request provenance but do not influence generation. Recommended
guidance is 1.5, 30 steps. Seed/steps/guidance/category affect inference.

Model files are immutable hash-locked local safetensors and ONNX files. No git
installation, custom nodes, runtime Python/model downloads, pickle checkpoints,
human parser or implicit Hugging Face token is allowed. Installation requires an
exact approved requirements hash and an isolated venv. Inference runs with hub
offline flags after bytes are verified. Model weights use BF16 when CUDA supports
it; T4 uses the official FP32 fallback, which still needs an observed memory and
quality check. No FP16 substitution is made.

`python -m colab.vton_worker download|serve|smoke` runs the dedicated worker. The
authenticated image-job API and job persistence/integrity behavior are shared
with SDXL; health capabilities are only `image`, `virtual_try_on`. Same request
UUID with changed input returns 409; interrupted jobs fail explicitly. Runtime
tokens stay in memory, with no access logs or notebook output. Colab `/content`
is temporary; explicitly select durable non-code storage if needed.

Source revision, model/pose revisions, ordered input hashes, category, photo
type, precision, device, elapsed time, VRAM peaks, output hash and ignored
parameters are recorded in the output receipt. Local contract/source tests do
not prove CUDA execution, garment fidelity, face preservation or commercial
clearance of user images. Inspect a genuine GPU result before publishing.

Vendored code license and change notices are in
`vendor/fashn_vton/LICENSE` and `vendor/fashn_vton/NOTICE`.
