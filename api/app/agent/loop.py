"""The hand-rolled tool-use loop behind POST /api/ask (PLAN §8), over AnthropicProvider (agent/providers.py).

A manual loop rather than a framework's, because code, not the model, decides what the user sees: every tool call
is recorded here, and response.assemble builds the answer, SQL, data and label from those records.
"""

import json
import time

from app import config
from app.agent.prompt import FINAL_SCHEMA, system_prompt
from app.agent.providers import AnthropicProvider, ToolUse
from app.agent.response import ToolCall, assemble, refusal
from app.agent.trace import Trace
from app.guardrails import refusal_routing
from app.tools.definitions import TOOLS
from app.tools.handlers import ToolError, for_model, run_tool

# Asked once when a turn ends without a readable final answer (a weaker model often replies in prose).
FINAL_NUDGE = (
    "Your last reply wasn't the final answer in the required format. Reply now with only the final answer, in the "
    "format the instructions give, citing the tool_use_id of every result it relies on."
)


class AgentError(Exception):
    """The loop could not produce an answer; `status` is the HTTP status to report."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def run_agent(provider: AnthropicProvider, question: str, region: str, trace: Trace, *, tools: list[dict] = TOOLS,
              system: str | None = None) -> dict:
    """Answer one question; fills `trace` as it goes, so a failure still leaves a useful record."""
    if reason := refusal_routing.route(question):  # no answer could be right, so no model call (D39)
        note = f"Refused before any model call ({reason.replace('_', ' ')}); no figures reported."
        return _finish(trace, refusal(refusal_routing.message(reason), note, _id(trace)))
    started = time.monotonic()
    system = system if system is not None else system_prompt()
    transcript: list[dict] = [
        {"role": "user", "content": f"<region_claim>{region}</region_claim>\n<question>{question}</question>"}]
    calls: dict[str, ToolCall] = {}
    nudged = False
    for round_no in range(config.MAX_TOOL_ROUNDS + 1):
        remaining = config.AGENT_TIMEOUT_S - (time.monotonic() - started)
        if remaining <= 0:
            raise AgentError("The agent ran out of time.", 504)
        # Past the tool-round cap, the model must answer with what it has.
        turn = provider.complete(system, transcript, tools, final_only=round_no == config.MAX_TOOL_ROUNDS,
                                 timeout=remaining)
        trace.add_usage(turn)
        # Check refusal before touching content: the whole fallback chain declined, and content may be partial.
        if turn.stop == "refusal":
            category = f" ({turn.refusal_category})" if turn.refusal_category else ""
            note = f"Refused by the API's safety classifiers{category}; no figures reported."
            return _finish(trace, refusal("This request was declined by the model's safety checks.", note, _id(trace)))
        if turn.stop == "max_tokens":
            raise AgentError("The model's response was cut off at max_tokens.")
        transcript.append({"role": "assistant", "turn": turn})
        if turn.stop == "pause":
            continue  # resend as-is; the API resumes the paused turn
        if turn.stop == "end_turn":
            final = _final_answer(turn.text)
            if final is not None:
                return _finish(trace, assemble(final, calls, _id(trace)))
            if nudged:
                raise AgentError("The model finished without a final answer.")
            nudged = True
            transcript.append({"role": "user", "content": FINAL_NUDGE})
            continue
        transcript.append({"role": "tool", "results": [_run(use, region, calls, trace) for use in turn.tool_uses]})
    raise AgentError("The model kept calling tools past the round limit.")


def _run(use: ToolUse, region: str, calls: dict[str, ToolCall], trace: Trace) -> dict:
    """Execute one tool call and return its result; failures go back to the model as errors."""
    started = time.perf_counter()
    result, error = None, None
    try:
        result = run_tool(use.name, use.input, region)
    except ToolError as e:
        error = str(e)
    content = for_model(use.id, result) if error is None else json.dumps({"tool_use_id": use.id, "error": error},
                                                                          ensure_ascii=False)
    duration_ms = round((time.perf_counter() - started) * 1000)
    calls[use.id] = ToolCall(use.id, use.name, use.input or {}, result, error, duration_ms)
    trace.tool_calls.append({
        "id": use.id,
        "name": use.name,
        "input": use.input,
        "output": content[:300],
        "sql": result.get("sql") if result else None,
        "row_count": result.get("row_count") if result else None,
        "duration_ms": duration_ms,
        "error": error,
    })
    return {"tool_use_id": use.id, "content": content, "is_error": error is not None}


def _final_answer(text: str) -> dict | None:
    """The final answer object, or None when the text isn't one."""
    try:
        answer = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(answer, dict):
        return None
    if not set(FINAL_SCHEMA["required"]) <= answer.keys():
        return None
    ids, hint = answer["evidence_tool_use_ids"], answer["chart_hint"]
    if not isinstance(ids, list) or not isinstance(hint, dict) or not isinstance(answer["answer_text"], str):
        return None
    return {
        **answer,
        "refused": answer["refused"] is True,
        "clarifying_question": q if isinstance(q := answer["clarifying_question"], str) and q.strip() else None,
        "evidence_tool_use_ids": [str(i) for i in ids],
        "chart_hint": {"type": hint.get("type") or "none", **{k: hint.get(k) for k in ("x", "y", "series")}},
    }


def _finish(trace: Trace, response: dict) -> dict:
    trace.label = response["label"]
    trace.final_sql = response["sql"]
    trace.row_count = len(response["data"]["rows"]) if response["data"] else None
    trace.answer_text = response["answer_text"]
    return response


def _id(trace: Trace) -> str:
    return str(trace.trace_id)
