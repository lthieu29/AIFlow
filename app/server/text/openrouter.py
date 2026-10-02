"""Explicit free model routing, no model fallback and no automatic retry."""

from decimal import Decimal, InvalidOperation

import httpx
from pydantic import BaseModel, ValidationError
from server.text.schemas import strict_schema


class TextProviderError(Exception):
    pass


def free_structured_model(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    pricing = item.get("pricing") or {}
    if not isinstance(pricing, dict):
        return False
    try:
        return (isinstance(item.get("id"), str) and item["id"].endswith(":free")
                and "structured_outputs" in (item.get("supported_parameters") or [])
                and all(Decimal(str(pricing[key])) == 0 for key in ("prompt", "completion"))
                and all(Decimal(str(value)) == 0 for value in pricing.values()))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


class OpenRouter:
    def __init__(self):
        self.key = ""  # Process memory only; never included in API responses.

    def models(self) -> list[dict]:
        try:
            with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
                response = client.get("https://openrouter.ai/api/v1/models")
                response.raise_for_status()
                data = response.json()["data"]
                if not isinstance(data, list):
                    raise ValueError("Invalid model catalog")
                return [{"id": item["id"], "name": item.get("name", item["id"])}
                        for item in data if free_structured_model(item)]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as from_error:
            raise TextProviderError("Không xác minh được danh sách/giá model. Chưa gửi yêu cầu AI.") from from_error

    def generate_structured(self, prompt: str, schema: type[BaseModel], model: str,
                            timeout: float = 90) -> tuple[dict, str, dict | None]:
        key = self.key
        if not key:
            raise TextProviderError("Nhập OpenRouter API key trước khi sinh nội dung.")
        if model not in {item["id"] for item in self.models()}:
            raise TextProviderError("Model không còn đáp ứng điều kiện miễn phí và structured output.")
        body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 14000, "stream": False,
                "provider": {"allow_fallbacks": False, "require_parameters": True,
                             "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0}},
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "aiflow_story_v2", "strict": True, "schema": strict_schema(schema)}}}
        try:
            with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
                response = client.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                                       headers={"Authorization": f"Bearer {key}"})
                if response.status_code == 429:
                    raise TextProviderError("Hết lượt hoặc giới hạn tốc độ. Chờ rồi thử lại thủ công; không chuyển model trả phí.")
                if response.status_code >= 400:
                    raise TextProviderError(f"OpenRouter từ chối yêu cầu (HTTP {response.status_code}). Kiểm tra key/model rồi thử lại.")
                data = response.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise TextProviderError("Kết quả chưa hoàn chỉnh hoặc bị từ chối. Không lưu thành kịch bản hợp lệ.")
                content = schema.model_validate_json(choice["message"]["content"]).model_dump()
                actual_model = data.get("model")
                if not isinstance(actual_model, str) or not actual_model:
                    raise TextProviderError("Nhà cung cấp không trả tên model thực tế.")
                usage = data.get("usage")
                return content, actual_model, usage if isinstance(usage, dict) else None
        except httpx.HTTPError as exc:
            raise TextProviderError("Mất kết nối/timeout OpenRouter. Không tự gửi lại; kiểm tra lịch sử trước khi thử lại.") from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError) as exc:
            raise TextProviderError("Kết quả không đúng schema JSON. Bản trước vẫn được giữ.") from exc


provider = OpenRouter()
