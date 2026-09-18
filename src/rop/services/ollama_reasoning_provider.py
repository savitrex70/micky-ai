"""Task 057: concrete Ollama provider for the LLM reasoning boundary.

Reads its base URL and model name from the project Settings. Never
downloads a model, never silently substitutes one, and never retries.
Any failure to obtain a provider response raises
LLMReasoningProviderError, which the Task 057 service maps to
MODEL_UNAVAILABLE.
"""

from __future__ import annotations

import json

import httpx

from rop.config import get_settings
from rop.prompts import REASONING_SYSTEM_PROMPT
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
    LLMReasoningRequest,
)


class OllamaReasoningProvider:
    """Ollama chat-completion provider for the reasoning boundary."""

    provider_name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (
            base_url if base_url is not None else settings.ollama_base_url
        ).rstrip("/")
        resolved_model = (
            model_name
            if model_name is not None
            else settings.ollama_reasoning_model
        )
        if not resolved_model:
            raise LLMReasoningProviderError(
                "OLLAMA_REASONING_MODEL is not configured"
            )
        self.model_name = resolved_model
        self._timeout = timeout_seconds

    def generate_reasoning(
        self, request: LLMReasoningRequest
    ) -> LLMReasoningProviderResponse:
        body = {
            "model": self.model_name,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": REASONING_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        request.to_model_json(),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    self.base_url + "/api/chat", json=body
                )
        except httpx.HTTPError as exc:
            raise LLMReasoningProviderError(
                "Ollama request failed: " + str(exc)
            ) from exc
        if response.status_code != 200:
            raise LLMReasoningProviderError(
                "Ollama returned HTTP "
                + str(response.status_code)
                + ": "
                + response.text[:200]
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMReasoningProviderError(
                "Ollama returned non-JSON envelope"
            ) from exc
        message = data.get("message") if isinstance(data, dict) else None
        text = (
            message.get("content")
            if isinstance(message, dict)
            else None
        )
        if not isinstance(text, str) or not text:
            raise LLMReasoningProviderError(
                "Ollama response had no message content"
            )
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
        )
