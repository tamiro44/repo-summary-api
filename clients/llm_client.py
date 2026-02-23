"""Provider-agnostic LLM client supporting OpenAI and Anthropic APIs.

Detects the provider from LLM_API_BASE and formats requests accordingly.
"""

from __future__ import annotations

import json
import logging

import httpx

from config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior software engineer. Your task is to analyze the provided "
    "repository files and produce a structured JSON summary.\n\n"
    "IMPORTANT: Respond with ONLY valid JSON — no markdown fences, no extra text.\n\n"
    "The JSON object MUST have exactly these keys:\n"
    '  "summary"       — a concise 3-5 sentence overview of what the project does,\n'
    "                     its purpose, and its architecture.\n"
    '  "technologies"  — a JSON array of strings listing languages, frameworks,\n'
    "                     libraries, and tools used.\n"
    '  "structure"     — a brief description of the project layout and key modules.\n'
)

USER_PROMPT_TEMPLATE = (
    "Analyze the following repository files and return the JSON summary.\n\n"
    "{context}\n\n"
    "Respond with ONLY a valid JSON object. Do not wrap it in markdown code fences."
)


class LLMClientError(Exception):
    """Raised when the LLM API call fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _is_anthropic(api_base: str) -> bool:
    return "anthropic.com" in api_base


class LLMClient:
    """Calls either the Anthropic Messages API or an OpenAI-compatible endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._api_base = settings.llm_api_base.rstrip("/")
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout
        self._max_tokens = settings.llm_max_tokens
        self._is_anthropic = _is_anthropic(self._api_base)

    async def summarize(self, context: str) -> dict:
        """Send repository context to the LLM and return parsed JSON."""
        if self._is_anthropic:
            return await self._call_anthropic(context)
        return await self._call_openai(context)

    async def _call_openai(self, context: str) -> dict:
        user_message = USER_PROMPT_TEMPLATE.format(context=context)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": self._max_tokens,
            "temperature": 0.2,
        }
        headers = {}
        if self._api_key and self._api_key.strip():
            headers["Authorization"] = f"Bearer {self._api_key.strip()}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._api_base}/chat/completions",
                json=payload,
                headers=headers,
            )

        if resp.status_code != 200:
            raise LLMClientError(
                f"LLM API returned {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        return self._parse_json(raw)

    async def _call_anthropic(self, context: str) -> dict:
        user_message = USER_PROMPT_TEMPLATE.format(context=context)
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": 0.2,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_message},
            ],
        }
        headers = {
            "x-api-key": self._api_key.strip() if self._api_key else "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._api_base}/v1/messages",
                json=payload,
                headers=headers,
            )

        if resp.status_code != 200:
            raise LLMClientError(
                f"Anthropic API returned {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        raw = data["content"][0]["text"].strip()
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM returned invalid JSON: %s", raw[:200])
            raise LLMClientError(f"LLM returned invalid JSON: {exc}") from exc
