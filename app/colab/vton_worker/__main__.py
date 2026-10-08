"""python -m colab.vton_worker download|serve|smoke; one engine per process."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from ..image_worker.app import create_app
from .models import download_models
from .schema import VtonRequest


def main():
    parser = argparse.ArgumentParser(description="Reviewed parser-free flat-lay VTON worker")
    parser.add_argument("command", choices=("download", "serve", "smoke"))
    parser.add_argument("--model-root", type=Path, default=Path("/content/aiflow-vton-models"))
    parser.add_argument("--model-lock", type=Path, default=Path(__file__).with_name("model-lock.json"))
    parser.add_argument("--storage", type=Path, default=Path("/content/aiflow-vton-jobs"))
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path, default=Path("/content/aiflow-vton-smoke.png"))
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    if args.command == "download":
        download_models(args.model_root, args.model_lock)
        print("Reviewed VTON/pose model bytes downloaded and verified")
        return
    if args.command == "smoke" and not args.request:
        parser.error("smoke requires --request")
    request = VtonRequest.model_validate_json(args.request.read_text(encoding="utf-8")) if args.command == "smoke" else None
    from .engine import VtonEngine
    engine = VtonEngine(model_root=args.model_root, model_lock=args.model_lock)
    if args.command == "smoke":
        image, metadata = engine.generate(request)
        image.save(args.output, format="PNG")
        metadata["output_sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
        args.output.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"VTON GPU smoke completed: {args.output.name}")
        return
    import uvicorn
    app = create_app(token=os.environ.get("AIFLOW_IMAGE_WORKER_TOKEN", ""), root=args.storage,
                     engine=engine, request_model=VtonRequest)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
