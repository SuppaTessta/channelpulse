"""The provider adapters (decisions D31) against fixed responses. Nothing here reaches a model: HTTP goes through
httpx2.MockTransport, and the Anthropic adapter is covered by test_agent.py's scripted SDK client."""

import json
from pathlib import Path

import httpx2
import pytest

from app import config
from app.agent import providers
from app.agent.loop import FINAL_NUDGE, AgentError, run_agent
from app.agent.providers import (
    FINAL_TOOL,
    AnthropicProvider,
    OpenAICompatProvider,
    ProviderError,
)
from app.agent.trace import Trace
from app.tools.definitions import TOOLS

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "openai_compat_responses.json").read_text(encoding="utf-8"))
BASE = "https://tunnel-secret.example.test"


@pytest.fixture(autouse=True)
def offline(fake_db, fake_semantic):
    """The loop tests below run against the fake database and semantic layer."""


class Server:
    """A scripted /chat/completions endpoint: each reply is a fixture name, a dict, or an httpx2.Response/exception."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append({"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx2.Response):
            return reply
        return httpx2.Response(200, json=FIXTURES[reply] if isinstance(reply, str) else reply)


def provider(server: Server, **kwargs) -> OpenAICompatProvider:
    return OpenAICompatProvider("ollama", BASE + "/v1", "qwen3.8-27b-64k", kwargs.pop("api_key", None),
                                http=httpx2.Client(transport=httpx2.MockTransport(server)), **kwargs)


def turn_for(fixture: str):
    return provider(Server(fixture)).complete("rules", [{"role": "user", "content": "q"}], TOOLS, final_only=False, timeout=5)


# --- request shape ------------------------------------------------------------------------------------------------


def test_a_request_carries_every_tool_plus_final_answer_at_temperature_zero():
    server = Server("ollama_tool_call")
    provider(server).complete("rules", [{"role": "user", "content": "q"}], TOOLS, final_only=False, timeout=5)
    body = server.requests[0]["body"]
    assert server.requests[0]["url"] == BASE + "/v1/chat/completions"
    assert [t["function"]["name"] for t in body["tools"]] == [t["name"] for t in TOOLS] + [FINAL_TOOL]
    assert body["tools"][0]["function"]["parameters"] == TOOLS[0]["input_schema"]
    assert (body["tool_choice"], body["temperature"], body["model"]) == ("auto", 0.0, "qwen3.8-27b-64k")
    assert body["messages"][0]["role"] == "system" and FINAL_TOOL in body["messages"][0]["content"]
    assert "reasoning_effort" not in body and "authorization" not in server.requests[0]["headers"]


def test_the_last_round_offers_only_final_answer_and_requires_it():
    server = Server("gemini_final_answer")
    provider(server).complete("rules", [{"role": "user", "content": "q"}], TOOLS, final_only=True, timeout=5)
    body = server.requests[0]["body"]
    assert ([t["function"]["name"] for t in body["tools"]], body["tool_choice"]) == ([FINAL_TOOL], "required")


def test_a_token_and_a_reasoning_setting_are_sent_when_configured():
    server = Server("ollama_tool_call")
    provider(server, api_key="tok", reasoning_effort="none").complete(
        "rules", [{"role": "user", "content": "q"}], TOOLS, final_only=False, timeout=5)
    assert server.requests[0]["headers"]["authorization"] == "Bearer tok"
    assert server.requests[0]["body"]["reasoning_effort"] == "none"


def test_assistant_messages_are_echoed_verbatim_so_thought_signatures_survive():
    server = Server("gemini_tool_call", "gemini_final_answer")
    llm = provider(server)
    first = llm.complete("rules", [{"role": "user", "content": "q"}], TOOLS, final_only=False, timeout=5)
    transcript = [{"role": "user", "content": "q"}, {"role": "assistant", "turn": first},
                  {"role": "tool", "results": [{"tool_use_id": "function-call-1", "content": "{}", "is_error": False}]}]
    llm.complete("rules", transcript, TOOLS, final_only=False, timeout=5)
    sent = server.requests[1]["body"]["messages"]
    assert sent[2] == FIXTURES["gemini_tool_call"]["choices"][0]["message"]
    assert sent[2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "c2lnbmF0dXJlLWJ5dGVz"
    assert sent[3] == {"role": "tool", "tool_call_id": "function-call-1", "content": "{}"}


# --- response mapping ---------------------------------------------------------------------------------------------


def test_tool_calls_become_tool_uses_with_usage():
    turn = turn_for("gemini_tool_call")
    assert (turn.stop, turn.model, [(u.id, u.name) for u in turn.tool_uses]) == (
        "tool_use", "gemini-3.8-flash", [("function-call-1", "query_metric")])
    assert turn.tool_uses[0].input["metric_name"] == "dso"
    assert (turn.usage.input_tokens, turn.usage.output_tokens, turn.usage.cache_read_tokens) == (9000, 120, 8000)


def test_a_lone_final_answer_call_ends_the_turn_with_its_json():
    turn = turn_for("gemini_final_answer")
    assert turn.stop == "end_turn" and json.loads(turn.text)["evidence_tool_use_ids"] == ["function-call-1"]


def test_a_text_answer_loses_its_think_block_and_keeps_its_fence_for_the_loop():
    turn = turn_for("ollama_text_answer_with_think")
    assert turn.stop == "end_turn" and turn.text.startswith("```json") and "<think>" not in turn.text


def test_malformed_arguments_become_an_error_for_the_model_not_a_crash():
    use = turn_for("malformed_arguments").tool_uses[0]
    assert use.input is None and "weren't a JSON object" in use.error


def test_missing_ids_are_filled_in_on_the_echoed_message_too():
    turn = turn_for("missing_ids")
    assert turn.tool_uses[0].id and turn.native["tool_calls"][0]["id"] == turn.tool_uses[0].id
    assert turn.tool_uses[0].input == {}  # arguments sent as an object rather than a string


def test_a_final_answer_given_alongside_other_calls_is_refused_back_to_the_model():
    turn = turn_for("final_with_other_call")
    assert turn.stop == "tool_use" and [u.name for u in turn.tool_uses] == ["query_metric", FINAL_TOOL]
    assert "on its own" in turn.tool_uses[1].error


@pytest.mark.parametrize(("fixture", "stop"), [("empty_choices", "end_turn"), ("content_filter", "refusal"),
                                                ("length", "max_tokens")])
def test_empty_filtered_and_truncated_replies(fixture, stop):
    turn = turn_for(fixture)
    assert (turn.stop, turn.text, turn.tool_uses) == (stop, "", [])


# --- failures: infrastructure versus the model --------------------------------------------------------------------


@pytest.mark.parametrize(("reply", "kind"), [
    (httpx2.ConnectError("no route to " + BASE), "infrastructure"),
    (httpx2.ReadTimeout("timed out"), "infrastructure"),
    (httpx2.Response(530, text="<html>Cloudflare: origin is unreachable</html>"), "infrastructure"),
    (httpx2.Response(502, text="bad gateway"), "infrastructure"),
    (httpx2.Response(200, text="<html>tunnel error</html>"), "infrastructure"),
    (httpx2.Response(429, json=[{"error": {"details": [{"retryDelay": "37s"}]}}]), "rate_limited"),
    (httpx2.Response(400, json={"error": {"message": "Invalid JSON payload: unknown field"}}), "rejected"),
])
def test_failures_are_classified_and_never_carry_the_url(reply, kind):
    with pytest.raises(ProviderError) as caught:
        provider(Server(reply)).complete("rules", [{"role": "user", "content": "q"}], TOOLS, final_only=False, timeout=5)
    assert caught.value.kind == kind and "tunnel-secret" not in str(caught.value)
    if kind == "rate_limited":
        assert caught.value.retry_after == 37.0


# --- the loop over this adapter -----------------------------------------------------------------------------------


def ask(server: Server):
    trace = Trace(question="q", region_claim="Assam", model="qwen3.8-27b-64k", provider="ollama")
    return run_agent(provider(server), "How has DSO moved?", "Assam", trace), trace


def test_the_governed_path_works_end_to_end(fake_db):
    server = Server("gemini_tool_call", "gemini_final_answer")
    response, trace = ask(server)
    assert (response["label"], response["data"], response["chart_spec"]["type"]) == (
        "governed_metric", fake_db.result.data, "line")
    assert fake_db.calls[0][2] == "Assam" and (trace.provider, trace.est_cost_usd) == ("ollama", 0.0)
    tool_message = server.requests[1]["body"]["messages"][-1]
    assert tool_message["role"] == "tool" and json.loads(tool_message["content"])["tool_use_id"] == "function-call-1"


def test_malformed_arguments_are_sent_back_and_the_model_retries(fake_db):
    retry = json.loads(json.dumps(FIXTURES["gemini_final_answer"]).replace("function-call-1", "call_ok"))
    ok_call = json.loads(json.dumps(FIXTURES["ollama_tool_call"]).replace("call_abc123", "call_ok"))
    server = Server("malformed_arguments", ok_call, retry)
    response, trace = ask(server)
    error = json.loads(server.requests[1]["body"]["messages"][-1]["content"])
    assert "weren't a JSON object" in error["error"] and response["label"] == "governed_metric"
    assert trace.tool_calls[0]["error"] and not trace.tool_calls[1]["error"]


def test_an_empty_reply_gets_one_nudge_then_the_answer_counts():
    answer = json.loads(json.dumps(FIXTURES["ollama_text_answer_with_think"]).replace(
        '[\\"call_abc123\\"]', "[]").replace('\\"refused\\": false', '\\"refused\\": true'))
    server = Server("empty_choices", answer)
    response, _ = ask(server)
    assert server.requests[1]["body"]["messages"][-1] == {"role": "user", "content": FINAL_NUDGE}
    assert response["label"] == "refused"


def test_two_unreadable_endings_are_an_agent_error_not_an_answer():
    with pytest.raises(AgentError, match="without a final answer"):
        ask(Server("empty_choices", "empty_choices"))


# --- configuration ------------------------------------------------------------------------------------------------


def test_the_default_provider_is_gemini():
    assert config.DEFAULT_PROVIDER == "gemini"


@pytest.mark.parametrize(("name", "env", "configured"), [
    ("gemini", {}, False),
    ("gemini", {"GEMINI_API_KEY": "k"}, True),
    ("ollama", {"OLLAMA_BASE_URL": BASE}, False),
    ("ollama", {"OLLAMA_BASE_URL": BASE, "OLLAMA_MODEL": "qwen3.8-27b-64k"}, True),
    ("anthropic", {}, False),
])
def test_each_provider_needs_its_own_settings(monkeypatch, name, env, configured):
    for var in ("GEMINI_API_KEY", "GEMINI_MODEL", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(config, "PROVIDER", name)
    built = providers.from_env()
    assert (built is not None) == configured
    if configured:
        assert built.name == name


def test_ollama_is_reached_on_v1_and_a_token_becomes_a_bearer_header(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", BASE + "/")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.8-27b-64k")
    monkeypatch.setenv("OLLAMA_API_TOKEN", "tok")
    built = providers.from_env()
    assert built._url == BASE + "/v1/chat/completions" and built._headers == {"Authorization": "Bearer tok"}


def test_an_unknown_provider_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "openai")
    with pytest.raises(ValueError, match="Unknown CHANNELPULSE_PROVIDER"):
        providers.from_env()


def test_the_anthropic_provider_wraps_a_resolved_client(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    sentinel = object()
    built = providers.from_env(sentinel)
    assert isinstance(built, AnthropicProvider) and built.client is sentinel and built.model == config.MODEL


# --- captured from the live tool-calling test (Part B, 2026-09-29) --------------------------------------------------


def test_the_captured_gemini_reply_maps_to_a_query_metric_call_with_its_signature_kept():
    turn = turn_for("captured_gemini_tool_call")
    (use,) = turn.tool_uses
    assert (turn.stop, use.name, use.input["metric_name"]) == ("tool_use", "query_metric", "dso")
    assert turn.native["tool_calls"][0]["extra_content"]["google"]["thought_signature"]


def test_thinking_tokens_count_as_output_when_the_total_says_so():
    # Gemini leaves its thinking tokens out of completion_tokens; total_tokens includes them (892 + 68 + 122 = 1082).
    usage = turn_for("captured_gemini_tool_call").usage
    assert (usage.input_tokens, usage.output_tokens) == (892, 190)


def test_a_429_carries_the_quota_it_hit():
    body = [{"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
             "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "23s"}]}}]
    with pytest.raises(ProviderError) as caught:
        provider(Server(httpx2.Response(429, json=body))).complete("s", [{"role": "user", "content": "q"}], TOOLS,
                                                                    final_only=False, timeout=5)
    assert (caught.value.quota_id, caught.value.retry_after) == ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 23)
