"""Explicit provider selection. Credentials never leave process memory."""
import re
import httpx
from server.text.openrouter import provider as openrouter, TextProviderError

class Gemini:
    def __init__(self):
        self.key = ""
        self.billing_confirmed = False

    def generate_structured(self, prompt, schema, model, timeout=90):
        if not self.key or not self.billing_confirmed:
            raise TextProviderError("Gemini chưa được cấu hình và xác nhận quota/billing.")
        if not re.fullmatch(r"gemini-[a-zA-Z0-9._-]+", model):
            raise TextProviderError("Tên model Gemini không hợp lệ.")
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": self.key}, json={"contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseFormat": {"text": {"mimeType": "application/json", "schema": schema.model_json_schema()}}, "maxOutputTokens": 14000}})
                if response.status_code != 200:
                    raise TextProviderError(f"Gemini HTTP {response.status_code}; không tự retry/chuyển model.")
                data = response.json()
                candidate = data["candidates"][0]
                if candidate.get("finishReason") != "STOP":
                    raise TextProviderError("Gemini trả kết quả chưa hoàn tất.")
                text = "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
                return schema.model_validate_json(text).model_dump(), data.get("modelVersion", model), data.get("usageMetadata")
        except TextProviderError:
            raise
        except Exception as exc:
            raise TextProviderError("Không đọc được kết quả Gemini. Kiểm tra model/schema/kết nối; chưa tự gọi lại.") from exc

class CodexCLI:
    reason = "Codex chạy qua tác vụ CAO/tmux có receipt; dùng luồng codex_tmux.begin."

    def generate_structured(self, prompt, schema, model, timeout=90):
        # Tmux jobs have their own durable lifecycle; never fall back to exec/API.
        raise TextProviderError(self.reason)

gemini = Gemini()
codex = CodexCLI()
PROVIDERS = {"openrouter": openrouter, "gemini": gemini, "codex_cli": codex}
