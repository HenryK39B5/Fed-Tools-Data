"""
Lightweight DeepSeek API client built on top of plain HTTP requests.

Using requests avoids version conflicts with the OpenAI SDK (e.g., differences
in proxy handling) while keeping the payload compatible with the
OpenAI-style /v1/chat/completions endpoint exposed by DeepSeek.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

# Allow overriding via env so users can point to a custom endpoint if needed.
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


@dataclass
class DeepSeekConfig:
    """
    Runtime parameters for interacting with the DeepSeek endpoint.
    """

    api_key: Optional[str] = None
    base_url: str = DEEPSEEK_BASE_URL
    model: str = "deepseek-chat"
    temperature: float = 0.25
    max_tokens: int = 1600
    top_p: float = 0.95
    timeout: int = 60


class DeepSeekClient:
    """
    Shared client responsible solely for LLM communication.
    """

    def __init__(self, config: Optional[DeepSeekConfig] = None):
        self.config = config or DeepSeekConfig()
        self.api_key = self.config.api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "DeepSeek API key is missing. "
                "Set the DEEPSEEK_API_KEY environment variable or pass api_key via DeepSeekConfig."
            )
        self.base_url = (self.config.base_url or DEEPSEEK_BASE_URL).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, messages: List[Dict[str, str]], **overrides) -> str:
        """
        Invoke the chat.completions endpoint and return the generated text payload.
        """

        payload = {
            "model": overrides.get("model", self.config.model),
            "temperature": overrides.get("temperature", self.config.temperature),
            "max_tokens": overrides.get("max_tokens", self.config.max_tokens),
            "top_p": overrides.get("top_p", self.config.top_p),
            "messages": messages,
        }

        url = f"{self.base_url}/v1/chat/completions"
        timeout = overrides.get("timeout", self.config.timeout)
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=timeout,
                )
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt == 0:
                    continue
                raise RuntimeError(f"DeepSeek request failed: {exc}") from exc

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("DeepSeek响应解析失败") from exc
