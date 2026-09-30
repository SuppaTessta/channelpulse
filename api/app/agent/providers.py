"""Model providers behind one small interface (decisions D31): the loop sends a system prompt, a provider-neutral
transcript and the tool definitions; a provider returns one Turn (text, tool calls, token usage, stop reason).

Two wire formats cover every provider this project uses, both hand-rolled:
- AnthropicProvider: the Messages API through the official SDK (refusal fallback, adaptive thinking, structured
  final answer). Its requests are exactly what the loop sent before providers existed.
- OpenAICompatProvider: /chat/completions over HTTP, for Gemini (Google's OpenAI-compatible endpoint) and Ollama
  (/v1). The final answer arrives as a call to a `final_answer` tool whose parameters are the final-answer schema,
  because tool calling is the one capability both have. Each assistant message is echoed back exactly as received,
  so provider extras such as Gemini's thought signatures survive the next round.

Transcript items: {"role": "user", "content": str}, {"role": "assistant", "turn": Turn} and
{"role": "tool", "results": [{"tool_use_id", "content", "is_error"}]}.
"""

import copy
import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx2

from app import config

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FINAL_TOOL = "final_answer"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

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
    input: dict | None  # None when the model's arguments weren't a JSON object
    error: str | None = None


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
    """A call that produced no turn. `kind` separates the model's service from the model:
    infrastructure (unreachable, timed out, 5xx, a proxy's error page), rate_limited (429) or rejected (4xx).
    Messages never carry the base URL or a key."""

    def __init__(self, message: str, kind: Literal["infrastructure", "rate_limited", "rejected"],
                 status: int | None = None, retry_after: float | None = None, quota_id: str | None = None):
        super().__init__(message)
        self.kind, self.status, self.retry_after = kind, status, retry_after
        self.quota_id = quota_id  # which quota a 429 hit, when the server says (Google's QuotaFailure)


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, transcript: list[dict], tools: list[dict], *, final_only: bool,
                 timeout: float) -> Turn: ...

    def settings(self) -> dict: ...


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
        return {"effort": self._effort or config.EFFORT, "thinking": "adaptive", "fallbacks": "default"}

    def complete(self, system, transcript, tools, *, final_only, timeout):
        from app.agent.prompt import FINAL_SCHEMA

        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=config.MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",
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
            raise ProviderError(f"Unexpected stop reason {response.stop_reason!r}.", "rejected")
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


# --- OpenAI-compatible (Gemini, Ollama) ---------------------------------------------------------------------------

FINAL_INSTRUCTION = (
    f"\nDeliver that JSON object by calling the {FINAL_TOOL} tool, on its own, once you have the tool results you "
    "need. Each tool result carries its tool_use_id: cite those ids in evidence_tool_use_ids."
)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_CLOUDFLARE_DOWN = {520, 521, 522, 523, 524, 525, 526, 527, 530}


class OpenAICompatProvider:
    def __init__(self, name: str, base_url: str, model: str, api_key: str | None = None, *,
                 temperature: float | None = 0.0, reasoning_effort: str | None = None, extra: dict | None = None,
                 http: httpx2.Client | None = None, record: dict | None = None, call_timeout: float = 120.0):
        self.name, self.model = name, model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._temperature, self._reasoning = temperature, reasoning_effort
        self._extra = extra or {}
        self._http = http or httpx2.Client()
        self._record = record or {}  # facts about the serving setup, reported with every eval run
        self._call_timeout = call_timeout  # one model call; the loop's own budget covers the whole question

    def settings(self) -> dict:
        return {"temperature": self._temperature, "reasoning_effort": self._reasoning or "provider default",
                **self._record}

    def complete(self, system, transcript, tools, *, final_only, timeout):
        from app.agent.prompt import FINAL_SCHEMA

        final = {"type": "function", "function": {
            "name": FINAL_TOOL, "description": "Deliver the final answer. Call it alone, as the last step.",
            "parameters": FINAL_SCHEMA}}
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system + FINAL_INSTRUCTION}, *self._messages(transcript)],
            "tools": [final] if final_only else [*map(_function, tools), final],
            "tool_choice": "required" if final_only else "auto",
            "max_tokens": config.MAX_TOKENS,
            **self._extra,
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._reasoning:
            body["reasoning_effort"] = self._reasoning
        return self._turn(self._post(body, min(timeout, self._call_timeout)))

    def _post(self, body: dict, timeout: float) -> dict:
        try:
            res = self._http.post(self._url, json=body, headers=self._headers, timeout=timeout)
        except httpx2.TimeoutException:
            raise ProviderError(f"{self.name}: no response within {timeout:.0f} s.", "infrastructure") from None
        except httpx2.HTTPError as e:  # connection refused, DNS, reset: the message would carry the URL, so it's dropped
            raise ProviderError(f"{self.name}: couldn't connect ({type(e).__name__}).", "infrastructure") from None
        if res.status_code == 429:
            raise ProviderError(f"{self.name}: rate limited.", "rate_limited", 429, _retry_after(res), _quota_id(res))
        if res.status_code >= 500 or res.status_code in _CLOUDFLARE_DOWN:
            raise ProviderError(f"{self.name}: server error {res.status_code}.", "infrastructure", res.status_code)
        if res.status_code >= 400:
            raise ProviderError(f"{self.name}: request rejected ({res.status_code}): {_error_text(res)}", "rejected",
                                res.status_code)
        try:
            payload = res.json()
        except ValueError:  # e.g. an HTML page from a proxy in front of a dead server
            raise ProviderError(f"{self.name}: the reply wasn't JSON.", "infrastructure", res.status_code) from None
        if not isinstance(payload, dict):
            raise ProviderError(f"{self.name}: the reply wasn't a JSON object.", "infrastructure", res.status_code)
        return payload

    def _turn(self, payload: dict) -> Turn:
        raw = payload.get("usage") or {}
        prompt, completion = int(raw.get("prompt_tokens") or 0), int(raw.get("completion_tokens") or 0)
        # Gemini leaves thinking tokens out of completion_tokens but counts them in total_tokens: they're output.
        output = max(completion, int(raw.get("total_tokens") or 0) - prompt)
        usage = Usage(prompt, output, int((raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0))
        model = payload.get("model") or self.model
        choices = payload.get("choices") or []
        if not choices or not isinstance(choices[0], dict):  # an empty reply: the loop asks once more for an answer
            return Turn("end_turn", "", [], usage, model, native={"role": "assistant", "content": ""})
        choice = choices[0]
        message = copy.deepcopy(choice.get("message") or {"role": "assistant", "content": ""})
        message.setdefault("role", "assistant")
        text = _THINK.sub("", message.get("content") or "").strip()
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            return Turn("refusal", "", [], usage, model, native=message, refusal_category="content_filter")
        calls = message.get("tool_calls") or []
        uses = []
        for call in calls:
            call.setdefault("type", "function")
            if not call.get("id"):  # some servers omit ids; the echoed message must carry the same ones
                call["id"] = f"call_{uuid.uuid4().hex[:12]}"
            fn = call.get("function") or {}
            uses.append(_tool_use(call["id"], fn.get("name") or "", fn.get("arguments")))
        finals = [u for u in uses if u.name == FINAL_TOOL]
        if finals and len(uses) == 1:
            answer = finals[0]
            return Turn("end_turn", json.dumps(answer.input) if answer.input is not None else answer.error or "", [],
                        usage, model, native=message)
        if uses:
            for u in finals:  # an answer given alongside other calls is premature: the model gets a note instead
                u.error = f"Call {FINAL_TOOL} on its own, after reading the results of your other tool calls."
            return Turn("tool_use", "", uses, usage, model, native=message)
        if finish == "length":
            return Turn("max_tokens", "", [], usage, model, native=message)
        return Turn("end_turn", text, [], usage, model, native=message)

    @staticmethod
    def _messages(transcript: list[dict]) -> list[dict]:
        out = []
        for item in transcript:
            if item["role"] == "user":
                out.append({"role": "user", "content": item["content"]})
            elif item["role"] == "assistant":
                out.append(item["turn"].native)
            else:
                out += [{"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]} for r in item["results"]]
        return out


def _function(tool: dict) -> dict:
    return {"type": "function",
            "function": {"name": tool["name"], "description": tool["description"], "parameters": tool["input_schema"]}}


def _tool_use(call_id: str, name: str, arguments: Any) -> ToolUse:
    if isinstance(arguments, dict):  # some servers send an object rather than a JSON string
        return ToolUse(call_id, name, arguments)
    try:
        parsed = json.loads(arguments or "{}")
    except (TypeError, ValueError):
        parsed = None
    if not isinstance(parsed, dict):
        return ToolUse(call_id, name, None, error=f"The arguments for {name or 'this call'} weren't a JSON object; "
                                                   "call it again with valid JSON.")
    return ToolUse(call_id, name, parsed)


def _retry_after(res: httpx2.Response) -> float | None:
    if (header := res.headers.get("retry-after")) and header.replace(".", "", 1).isdigit():
        return float(header)
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', res.text)  # Google's RetryInfo in the error body
    return float(match.group(1)) if match else None


def _quota_id(res: httpx2.Response) -> str | None:
    match = re.search(r'"quotaId"\s*:\s*"([^"]+)"', res.text)
    return match.group(1) if match else None


def _error_text(res: httpx2.Response) -> str:
    try:
        body = res.json()
        error = body[0].get("error") if isinstance(body, list) else body.get("error", body)
        message = error.get("message") if isinstance(error, dict) else error
        return str(message)[:300]
    except (ValueError, AttributeError, IndexError):
        return res.text[:300]


# --- configuration ------------------------------------------------------------------------------------------------


def from_env(anthropic_client=None) -> Provider | None:
    """The configured provider (CHANNELPULSE_PROVIDER, default gemini), or None when its credentials or endpoint
    aren't set. `anthropic_client` is the resolved SDK client for the anthropic provider."""
    env = os.environ.get
    name = config.PROVIDER
    temperature = float(env("CHANNELPULSE_TEMPERATURE", "0"))
    if name == "anthropic":
        return AnthropicProvider(anthropic_client) if anthropic_client is not None else None
    if name == "gemini":
        key = env("GEMINI_API_KEY")
        if not key:
            return None
        model = env("GEMINI_MODEL", config.GEMINI_MODEL)
        reasoning = env("GEMINI_REASONING_EFFORT") or None
        default = config.GEMINI_DEFAULT_THINKING.get(model, "unknown")
        return OpenAICompatProvider("gemini", GEMINI_BASE_URL, model, key, temperature=temperature,
                                    reasoning_effort=reasoning,
                                    record={"thinking": reasoning or f"provider default ({default})"})
    if name == "ollama":
        base, model = env("OLLAMA_BASE_URL"), env("OLLAMA_MODEL")
        if not base or not model:
            return None
        # Ollama's /v1 ignores `think: false` but honours reasoning_effort "none" (verified live, D35).
        thinking_off = env("OLLAMA_THINKING", "").lower() in ("off", "false", "0", "none")
        reasoning = env("OLLAMA_REASONING_EFFORT") or ("none" if thinking_off else None)
        record = {"thinking": f"off (reasoning_effort={reasoning})" if reasoning == "none"
                  else (reasoning or "server default")}
        return OpenAICompatProvider("ollama", base.rstrip("/") + "/v1", model, env("OLLAMA_API_TOKEN") or None,
                                    temperature=temperature, reasoning_effort=reasoning, record=record,
                                    call_timeout=float(env("OLLAMA_CALL_TIMEOUT_S", "300")))
    raise ValueError(f"Unknown CHANNELPULSE_PROVIDER {name!r}: use gemini, ollama or anthropic.")



def ollama_show(base_url: str, model: str, token: str | None = None, http: httpx2.Client | None = None) -> dict:
    """What the Ollama server itself reports for `model` (POST /api/show): quantization, context length, family and
    size. Recorded with every eval run instead of assuming them. Errors never carry the URL."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        res = (http or httpx2.Client()).post(base_url.rstrip("/") + "/api/show", json={"model": model},
                                             headers=headers, timeout=60)
        res.raise_for_status()
        info = res.json()
    except (httpx2.HTTPError, ValueError) as e:
        raise ProviderError(f"ollama: /api/show failed ({type(e).__name__}).", "infrastructure") from None
    details, model_info = info.get("details") or {}, info.get("model_info") or {}
    trained = next((v for k, v in model_info.items() if k.endswith(".context_length")), None)
    parameters = dict(line.split(None, 1) for line in (info.get("parameters") or "").splitlines() if line.strip())
    parameters = {k: v.strip() for k, v in parameters.items()}
    num_ctx = int(parameters["num_ctx"]) if parameters.get("num_ctx", "").isdigit() else None
    return {
        "quantization": details.get("quantization_level"),
        "context_length": num_ctx or trained,  # num_ctx is what the served tag runs with; else the model's trained length
        "context_length_trained": trained,
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "format": details.get("format"),
        "server_parameters": parameters,  # e.g. temperature, num_ctx, draft_num_predict (MTP)
        "server_thinking_default": (info.get("thinking") or {}).get("default"),
    }
