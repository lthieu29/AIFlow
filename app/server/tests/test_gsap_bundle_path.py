"""The runtime bundle belongs alongside AIFlow's other app-local vendors."""

from pathlib import Path

from server.render.visual_layer import gsap_bundle


def test_gsap_path_resolves_under_app_vendor():
    app_root = Path(__file__).resolve().parents[2]
    assert gsap_bundle._VENDOR_DIR == app_root / "vendor" / "visual_layer"
    assert gsap_bundle._GSAP_PATH == app_root / "vendor" / "visual_layer" / "gsap.min.js"


def test_inject_gsap_uses_local_bundle_uri(tmp_path, monkeypatch):
    bundle = tmp_path / "vendor" / "visual_layer" / "gsap.min.js"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("fixture bundle", encoding="utf-8")
    monkeypatch.setattr(gsap_bundle, "_GSAP_PATH", bundle)
    html = gsap_bundle.inject_gsap('<script src="{{__VENDOR_GSAP__}}"></script>')
    assert html == f'<script src="{bundle.as_uri()}"></script>'
