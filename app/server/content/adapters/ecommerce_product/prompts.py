"""Prompts for the ecommerce_product adapter.

Ported from daihuo-jianshou/src/lib/script-engine/prompts.ts.

Scene types follow the 5-shot structure used in TikTok/Reels product videos:
  hero_shot      — opening hook, product reveal with visual impact
  detail_shot    — close-up of product details, materials, features
  lifestyle_shot — product in real-life usage context
  feature_shot   — key selling point demonstration
  cta_shot       — call-to-action with price and purchase prompt

All prompts are written for Veo3 (9:16 vertical, 8s clips).
Vietnamese narration style — conversational, TikTok-native.
"""

from __future__ import annotations

# ─── Scene type constants ─────────────────────────────────────────────────────

SCENE_TYPES = [
    "hero_shot",
    "detail_shot",
    "lifestyle_shot",
    "feature_shot",
    "cta_shot",
]

# ─── Veo3 prompt templates per scene type ────────────────────────────────────

PRODUCT_SCENE_PROMPTS: list[str] = [
    # 0 — hero_shot
    (
        "Cinematic product reveal shot. {product_name} placed on a clean minimal surface "
        "with soft studio lighting. Camera slowly zooms in from medium shot to close-up, "
        "revealing the product with dramatic lighting. Shallow depth of field, bokeh "
        "background. 9:16 vertical frame. Photoreal, editorial quality. "
        "No text overlays, no watermarks."
    ),
    # 1 — detail_shot
    (
        "Extreme close-up macro shot of {product_name}. Camera pans slowly across the "
        "product surface revealing texture, material quality, and fine details. "
        "Soft even key light from the left, subtle fill light. Crisp sharp focus on "
        "product details. 9:16 vertical frame. Product photography style. "
        "No text overlays."
    ),
    # 2 — lifestyle_shot
    (
        "Lifestyle scene showing {product_name} in natural everyday use. "
        "Warm natural lighting, authentic home or outdoor setting. "
        "Hands interact naturally with the product — no face visible, hands only. "
        "Shallow DOF, background softly blurred. Warm color grade, film grain. "
        "9:16 vertical frame. Authentic, relatable, not overly staged."
    ),
    # 3 — feature_shot
    (
        "Product feature demonstration shot for {product_name}. "
        "Split-screen or sequential close-up showing the key feature in action. "
        "Clean white or neutral background. Crisp studio lighting. "
        "Camera movement: slow push-in to emphasize the feature detail. "
        "9:16 vertical frame. Clean, informative, high-contrast. "
        "No text overlays."
    ),
    # 4 — cta_shot
    (
        "Final call-to-action product shot. {product_name} centered in frame on a "
        "premium minimal surface. Soft warm studio lighting with subtle rim light. "
        "Camera holds static then slowly pulls back to reveal full product. "
        "9:16 vertical frame. Premium product photography aesthetic. "
        "Clean background, no clutter."
    ),
]

# ─── Narration template ───────────────────────────────────────────────────────

PRODUCT_NARRATION_TEMPLATE: str = (
    "Chị ơi, {product_name} này đang có giá {price} thôi! "
    "{cta} Đừng bỏ lỡ nhé!"
)

# ─── Per-scene narration templates ───────────────────────────────────────────

_SCENE_NARRATION_TEMPLATES: dict[str, str] = {
    "hero_shot": (
        "Ôi trời, {product_name} này đẹp quá đi! "
        "Mình vừa nhận hàng xong là phải khoe ngay với mọi người!"
    ),
    "detail_shot": (
        "Nhìn chất liệu này xem — {product_name} làm từ vật liệu cao cấp, "
        "từng chi tiết đều được hoàn thiện tỉ mỉ. Xứng đáng từng đồng!"
    ),
    "lifestyle_shot": (
        "Dùng {product_name} trong cuộc sống hàng ngày thật sự tiện lợi. "
        "Mình dùng mỗi ngày mà vẫn thích như ngày đầu!"
    ),
    "feature_shot": (
        "{product_name} có tính năng đặc biệt mà mình chưa thấy ở đâu khác. "
        "Đây chính là lý do mình quyết định mua ngay!"
    ),
    "cta_shot": (
        "{product_name} giá chỉ {price}. {cta} "
        "Số lượng có hạn, đặt hàng ngay trước khi hết nhé!"
    ),
}

# ─── Builder functions ────────────────────────────────────────────────────────


def build_scene_prompt(
    scene_num: int,
    product_name: str,
    product_desc: str,
    scene_type: str,
) -> str:
    """Build a Veo3 generation prompt for a specific scene.

    Args:
        scene_num:    0-based scene index (0–4).
        product_name: Display name of the product.
        product_desc: Short product description / key selling points.
        scene_type:   One of the SCENE_TYPES constants.

    Returns:
        A formatted Veo3 prompt string ready for generation.

    Raises:
        ValueError: If ``scene_type`` is not a recognised scene type.
    """
    if scene_type not in SCENE_TYPES:
        raise ValueError(
            f"Unknown scene_type {scene_type!r}. "
            f"Must be one of: {', '.join(SCENE_TYPES)}"
        )

    # Use scene_num to pick the template; fall back to index 0 if out of range
    idx = min(scene_num, len(PRODUCT_SCENE_PROMPTS) - 1)
    template = PRODUCT_SCENE_PROMPTS[idx]

    # Inject product name into the template
    prompt = template.format(product_name=product_name)

    # Append product description as additional context for the model
    if product_desc:
        prompt = f"{prompt} Product context: {product_desc}"

    return prompt


def build_narration(
    product_name: str,
    price: str,
    cta: str,
    scene_type: str = "cta_shot",
) -> str:
    """Build a Vietnamese TTS narration string for a scene.

    Args:
        product_name: Display name of the product.
        price:        Price string, e.g. "299.000đ".
        cta:          Call-to-action text, e.g. "Nhấn vào link dưới đây để mua ngay!".
        scene_type:   Scene type to select the appropriate narration template.
                      Defaults to ``"cta_shot"`` (the generic narration template).

    Returns:
        A formatted Vietnamese narration string.
    """
    template = _SCENE_NARRATION_TEMPLATES.get(
        scene_type, PRODUCT_NARRATION_TEMPLATE
    )
    return template.format(
        product_name=product_name,
        price=price,
        cta=cta,
    )
