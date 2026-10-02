"""Minimal Gemini API client for AIFlow.

Wraps google.genai.Client with friendly error messages per REVIEW-01.

Usage:
    from server.ai.gemini import GeminiClient
    client = GeminiClient(api_key="AIzaSy...", model="gemini-2.5-flash")
    text = client.generate_text("Say: AIFlow ready")
    ok = client.health_check()
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """Friendly Gemini API error with a human-readable message."""
    pass


class GeminiClient:
    """Thin wrapper around google.genai.Client.

    Provides generate_text() and health_check() with friendly error messages
    for common failure modes (401, 429, network errors).
    """

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout: int = 60) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = self._build_client()

    def _build_client(self):  # type: ignore[return]
        """Instantiate the underlying google.genai.Client."""
        try:
            import google.genai as genai  # type: ignore[import]
            return genai.Client(api_key=self.api_key)
        except ImportError as e:
            raise GeminiError(
                "google-genai package is not installed. "
                "Run: pip install google-genai"
            ) from e

    def generate_text(self, prompt: str) -> str:
        """Send a text prompt to Gemini and return the response text.

        Args:
            prompt: The text prompt to send.

        Returns:
            The model's text response.

        Raises:
            GeminiError: With a friendly message for 401, 429, or network errors.
        """
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            raise self._wrap_error(e) from e

    def health_check(self) -> bool:
        """Verify the Gemini API is reachable and the key is valid.

        Returns:
            True if the API responds successfully, False otherwise.
        """
        try:
            result = self.generate_text("Respond with exactly: ok")
            return bool(result)
        except GeminiError as e:
            logger.warning("Gemini health check failed: %s", e)
            return False

    @staticmethod
    def _wrap_error(exc: Exception) -> GeminiError:
        """Convert a google.genai exception into a friendly GeminiError."""
        msg = str(exc)
        msg_lower = msg.lower()

        # 401 / invalid key
        if "401" in msg or "api_key_invalid" in msg_lower or "invalid api key" in msg_lower:
            return GeminiError(
                "Invalid API key. Check AIFLOW_GEMINI_API_KEY in your .env file.\n"
                "Get a valid key at: https://aistudio.google.com/app/apikey"
            )

        # 429 / quota exceeded
        if "429" in msg or "quota" in msg_lower or "resource_exhausted" in msg_lower:
            return GeminiError(
                "Quota exceeded. You have hit the Gemini API rate limit.\n"
                "Wait a moment and try again, or check your quota at: "
                "https://aistudio.google.com/app/apikey"
            )

        # Network / connectivity errors
        if any(kw in msg_lower for kw in ("connection", "timeout", "network", "unreachable", "name or service")):
            return GeminiError(
                "Cannot reach Gemini API. Check your internet connection and try again."
            )

        # Generic fallback
        return GeminiError(f"Gemini API error: {msg}")
