"""The model call behind the loop: it sends a system prompt, a transcript and the tool definitions, and
AnthropicProvider returns one Turn (text, tool calls, token usage, stop reason). It is the Messages API through
the official SDK (refusal fallback, adaptive thinking, structured final answer); tests script the same methods.

Transcript items: {"role": "user", "content": str}, {"role": "assistant", "turn": Turn} and
{"role": "tool", "results": [{"tool_use_id", "content", "is_error"}]}.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app import config

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models with no server-side refusal fallback: their requests don't send `fallbacks` (decisions D50).
NO_FALLBACK = frozenset({"claude-haiku-5-5"})

Stop = Literal["tool_use", "end_turn", "max_tokens", "refusal", "pause"]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class Turn:
    stop: Stop
    text: str  # the final answer's JSON on end_turn; "" otherwise
    tool_uses: list[ToolUse]
    usage: Usage
    model: str  # the model that served this turn
    native: Any = None  # the provider's own assistant message, echoed back next round
    refusal_category: str | None = None


class ProviderError(Exception):
    """A call that produced no usable turn (the SDK's own errors are anthropic.APIError)."""


# --- Anthropic ----------------------------------------------------------------------------------------------------


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client, model: str | None = None, effort: str | None = None):
        self.client = client
        self._model, self._effort = model, effort

    @property
    def model(self) -> str:  # read at call time, so config overrides (the eval's --model) apply
        return self._model or config.MODEL

    def settings(self) -> dict:
        return {"effort": self._effort or config.EFFORT, "thinking": "adaptive",
                "fallbacks": "none" if self.model in NO_FALLBACK else "default"}

    def complete(self, system, transcript, tools, *, final_only, timeout):
        from app.agent.prompt import FINAL_SCHEMA

        fallback = {} if self.model in NO_FALLBACK else {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=config.MAX_TOKENS,
            **fallback,
            thinking={"type": "adaptive"},
            output_config={"effort": self._effort or config.EFFORT, "format": {"type": "json_schema", "schema": FINAL_SCHEMA}},
            cache_control={"type": "ephemeral"},  # automatic breakpoint on the growing conversation tail
            # Stable prefix: tools, then the system prompt, cached together by this breakpoint.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=[self._message(item) for item in transcript],
            timeout=timeout,
            **({"tool_choice": {"type": "none"}} if final_only else {}),
        )
        usage = response.usage
        spent = Usage(usage.input_tokens, usage.output_tokens, usage.cache_read_input_tokens or 0,
                      usage.cache_creation_input_tokens or 0)
        base = {"usage": spent, "model": response.model, "native": response.content}
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            return Turn("refusal", "", [], refusal_category=category, **base)
        if response.stop_reason in ("max_tokens", "pause_turn"):
            return Turn("max_tokens" if response.stop_reason == "max_tokens" else "pause", "", [], **base)
        if response.stop_reason == "end_turn":
            texts = [block.text for block in response.content if block.type == "text"]
            return Turn("end_turn", texts[-1] if texts else "", [], **base)
        if response.stop_reason != "tool_use":
            raise ProviderError(f"Unexpected stop reason {response.stop_reason!r}.")
        uses = [ToolUse(b.id, b.name, b.input) for b in response.content if b.type == "tool_use"]
        return Turn("tool_use", "", uses, **base)

    @staticmethod
    def _message(item: dict) -> dict:
        if item["role"] == "user":
            return {"role": "user", "content": item["content"]}
        if item["role"] == "assistant":
            return {"role": "assistant", "content": _echoable(item["turn"].native)}
        blocks = []
        for r in item["results"]:
            block = {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
            if r["is_error"]:
                block["is_error"] = True
            blocks.append(block)
        return {"role": "user", "content": blocks}


def _echoable(content: list) -> list:
    """Blocks to send back next round. After a refusal fallback, only text may be echoed from before the switch."""
    switch = max((i for i, block in enumerate(content) if block.type == "fallback"), default=-1)
    return [block for i, block in enumerate(content) if i > switch or (i < switch and block.type == "text")]

