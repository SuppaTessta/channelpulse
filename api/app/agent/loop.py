"""The hand-rolled Claude tool-use loop behind POST /api/ask (PLAN §8).

A manual loop rather than the SDK's tool runner, because code, not the model, decides what the user sees: every
tool call is recorded here, and response.assemble builds the answer, SQL, data and label from those records.
"""

import json
import time

from app import config
from app.agent.prompt import FINAL_SCHEMA, system_prompt
from app.agent.response import ToolCall, assemble, refusal
from app.agent.trace import Trace
from app.tools.definitions import TOOLS
from app.tools.handlers import ToolError, for_model, run_tool

# With fallbacks="default", a request Claude's safety classifiers decline is re-run server-side on the model
# Anthropic recommends for that refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentError(Exception):
    """The loop could not produce an answer; `status` is the HTTP status to report."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def run_agent(client, question: str, region: str, trace: Trace) -> dict:
    """Answer one question; fills `trace` as it goes, so a failure still leaves a useful record."""
    started = time.monotonic()
    # Stable prefix: tools, then the system prompt, cached together by this breakpoint. Volatile content follows.
    system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": f"<region_claim>{region}</region_claim>\n<question>{question}</question>"}]
    calls: dict[str, ToolCall] = {}
    for round_no in range(config.MAX_TOOL_ROUNDS + 1):
        remaining = config.AGENT_TIMEOUT_S - (time.monotonic() - started)
        if remaining <= 0:
            raise AgentError("The agent ran out of time.", 504)
        # Past the tool-round cap, the model must answer with what it has.
        last_round = {"tool_choice": {"type": "none"}} if round_no == config.MAX_TOOL_ROUNDS else {}
        response = client.beta.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": config.EFFORT, "format": {"type": "json_schema", "schema": FINAL_SCHEMA}},
            cache_control={"type": "ephemeral"},  # automatic breakpoint on the growing conversation tail
            system=system,
            tools=TOOLS,
            messages=messages,
            timeout=remaining,
            **last_round,
        )
        trace.add_usage(response)
        # Check refusal before touching content: the whole fallback chain declined, and content may be partial.
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            note = f"Refused by the API's safety classifiers{f' ({category})' if category else ''}; no figures reported."
            return _finish(trace, refusal("This request was declined by the model's safety checks.", note, _id(trace)))
        if response.stop_reason == "max_tokens":
            raise AgentError("The model's response was cut off at max_tokens.")
        messages.append({"role": "assistant", "content": _echoable(response.content)})
        if response.stop_reason == "pause_turn":
            continue  # resend as-is; the API resumes the paused turn
        if response.stop_reason == "end_turn":
            return _finish(trace, assemble(_final_answer(response), calls, _id(trace)))
        if response.stop_reason != "tool_use":
            raise AgentError(f"Unexpected stop reason {response.stop_reason!r}.")
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        messages.append({"role": "user", "content": [_run(block, region, calls, trace) for block in tool_uses]})
    raise AgentError("The model kept calling tools past the round limit.")


def _run(block, region: str, calls: dict[str, ToolCall], trace: Trace) -> dict:
    """Execute one tool_use block and return its tool_result; failures go back to the model with is_error."""
    started = time.perf_counter()
    try:
        result, error = run_tool(block.name, block.input, region), None
        content = for_model(block.id, result)
    except ToolError as e:
        result, error = None, str(e)
        content = json.dumps({"tool_use_id": block.id, "error": error}, ensure_ascii=False)
    duration_ms = round((time.perf_counter() - started) * 1000)
    calls[block.id] = ToolCall(block.id, block.name, block.input, result, error, duration_ms)
    trace.tool_calls.append({
        "id": block.id,
        "name": block.name,
        "input": block.input,
        "output": content[:300],
        "sql": result.get("sql") if result else None,
        "row_count": result.get("row_count") if result else None,
        "duration_ms": duration_ms,
        "error": error,
    })
    tool_result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
    if error:
        tool_result["is_error"] = True
    return tool_result


def _echoable(content: list) -> list:
    """Blocks to send back next round. After a refusal fallback, only text may be echoed from before the switch."""
    switch = max((i for i, block in enumerate(content) if block.type == "fallback"), default=-1)
    return [block for i, block in enumerate(content) if i > switch or (i < switch and block.type == "text")]


def _final_answer(response) -> dict:
    texts = [block.text for block in response.content if block.type == "text"]
    try:
        answer = json.loads(texts[-1])
    except (IndexError, json.JSONDecodeError) as e:
        raise AgentError("The model finished without a final answer.") from e
    if not isinstance(answer, dict) or not set(FINAL_SCHEMA["required"]) <= answer.keys():
        raise AgentError("The model's final answer did not match the response format.")
    return answer


def _finish(trace: Trace, response: dict) -> dict:
    trace.label = response["label"]
    trace.final_sql = response["sql"]
    trace.row_count = len(response["data"]["rows"]) if response["data"] else None
    trace.answer_text = response["answer_text"]
    return response


def _id(trace: Trace) -> str:
    return str(trace.trace_id)
