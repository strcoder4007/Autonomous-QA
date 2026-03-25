"""OpenAI gpt-5-mini wrapper with token tracking and cost estimation."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Cost per million tokens (gpt-5-mini, as of early 2025)
_COST_PER_1M_INPUT = 2.50
_COST_PER_1M_OUTPUT = 10.00


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * _COST_PER_1M_INPUT
            + self.output_tokens / 1_000_000 * _COST_PER_1M_OUTPUT
        )


class LLMClient:
    """Thin wrapper around the OpenAI chat completions API with usage tracking."""

    def __init__(
        self,
        model: str = "gpt-5-mini",
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package is required: pip install openai")

        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            max_retries=max_retries,
        )
        self._usage = LLMUsage()

    def chat(self, system_prompt: str, user_message: str) -> str:
        """Send a chat request and return the text response."""
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        if response.usage:
            self._usage.input_tokens += response.usage.prompt_tokens
            self._usage.output_tokens += response.usage.completion_tokens
        return response.choices[0].message.content or ""

    def chat_json(self, system_prompt: str, user_message: str) -> dict:
        """Send a chat request and return parsed JSON. Retries once on parse failure."""
        # json_object mode requires "JSON" to appear in the system prompt
        sp = system_prompt if "JSON" in system_prompt else system_prompt + "\n\nRespond with valid JSON."

        last_exc: Exception | None = None
        for attempt in range(2):
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": sp},
                    {"role": "user", "content": user_message},
                ],
            )
            if response.usage:
                self._usage.input_tokens += response.usage.prompt_tokens
                self._usage.output_tokens += response.usage.completion_tokens

            content = response.choices[0].message.content or ""
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                last_exc = exc
                if attempt == 0:
                    log.warning("JSON parse failed on attempt 1, retrying: %s", exc)

        raise RuntimeError(f"LLM returned invalid JSON after 2 attempts: {last_exc}") from last_exc

    @property
    def usage(self) -> LLMUsage:
        return self._usage

    def usage_summary(self) -> str:
        u = self._usage
        return (
            f"Tokens used: {u.input_tokens:,} input, {u.output_tokens:,} output — "
            f"estimated cost: ${u.estimated_cost_usd:.4f}"
        )
