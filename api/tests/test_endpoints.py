import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main, semantic
from app.guardrails import readonly_db
from app.tools import handlers

QUESTION = {"question": "How has DSO moved this year?"}
DSO_QUERY = {"metric_name": "dso", "filters": [], "group_by": ["month"], "date_range": None}


@pytest.fixture
def no_credentials(monkeypatch, tmp_path):
    """An environment where the SDK finds no API key, token, federation config or `ant auth login` profile."""
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_CONFIG_DIR",
                "ANTHROPIC_IDENTITY_TOKEN", "ANTHROPIC_IDENTITY_TOKEN_FILE", "ANTHROPIC_FEDERATION_RULE_ID",
                "ANTHROPIC_ORGANIZATION_ID"):
        monkeypatch.delenv(var, raising=False)
    for home in ("APPDATA", "HOME", "USERPROFILE"):  # the SDK's default profile directory, now empty
        monkeypatch.setenv(home, str(tmp_path))
    main.llm_client.cache_clear()
    yield monkeypatch
    main.llm_client.cache_clear()


def test_no_client_is_built_without_credentials(no_credentials):
    assert main.llm_client() is None


def test_an_api_key_is_enough_for_a_client(no_credentials):
    no_credentials.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    assert main.llm_client() is not None


def test_a_selected_profile_that_cannot_load_counts_as_not_configured(no_credentials, tmp_path):
    no_credentials.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "missing"))
    assert main.llm_client() is None


def test_ask_without_credentials_is_503_and_nothing_else_breaks(api):
    api.use_llm(None)
    response = api.http.post("/api/ask", json=QUESTION)
    assert (response.status_code, response.json()) == (503, {"detail": "LLM not configured"})
    assert api.http.get("/api/anomalies").status_code == 200


def test_ask_returns_the_assembled_response_and_writes_a_trace(api, claude):
    api.use_llm(claude.client(
        claude.message(claude.tool_use("t1", "query_metric", DSO_QUERY), stop_reason="tool_use"),
        claude.message(claude.answer(answer_text="DSO rose from 41.3 to 44.8 days.", evidence_tool_use_ids=["t1"])),
    ))
    response = api.http.post("/api/ask", json=QUESTION, headers={"X-Demo-Region": "Odisha"})
    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"answer_text", "sql", "data", "chart_spec", "label", "confidence_note", "trace_id"}
    assert (body["label"], body["data"]["rows"]) == ("governed_metric", api.db.result.rows)
    (trace,) = api.traces
    assert (str(trace.trace_id), trace.label, trace.region_claim, trace.question, trace.final_sql) == (
        body["trace_id"], "governed_metric", "Odisha", QUESTION["question"], body["sql"])
    assert trace.latency_ms is not None and trace.est_cost_usd > 0 and trace.tool_calls[0]["name"] == "query_metric"


def test_an_agent_failure_is_502_and_still_traced(api, claude):
    api.use_llm(claude.client(claude.message(stop_reason="max_tokens")))
    response = api.http.post("/api/ask", json=QUESTION)
    (trace,) = api.traces
    assert response.status_code == 502 and trace.label == "error" and "max_tokens" in trace.error


@pytest.mark.parametrize("question", ["", "x" * 2001])
def test_empty_and_oversized_questions_are_rejected(api, question):
    api.use_llm(None)
    assert api.http.post("/api/ask", json={"question": question}).status_code == 422


def test_metrics_lists_the_glossary(api):
    assert [m["name"] for m in api.http.get("/api/metrics").json()["metrics"]] == ["dso", "primary_sales_value"]


def test_metrics_serves_the_real_glossary():
    metrics = TestClient(main.app).get("/api/metrics").json()["metrics"]
    manifest = json.loads(Path(semantic.__file__).with_name("semantic_manifest.json").read_text(encoding="utf-8"))
    assert len(metrics) == len(manifest["metrics"]) and sum(metric["glossary"] for metric in metrics) == 12


def test_metric_query_accepts_boolean_filter_values(api, fake_semantic):
    body = {"metric_name": "dso", "filters": [{"dimension": "invoice__is_open", "op": "=", "value": True}]}
    assert api.http.post("/api/metrics/query", json=body).status_code == 200
    assert fake_semantic[0]["filters"][0]["value"] is True


def test_metric_query_is_the_governed_path_under_the_claim(api, fake_semantic):
    body = {"metric_name": "dso", "filters": [{"dimension": "region", "op": "in", "value": ["Assam", "Odisha"]}],
            "group_by": ["month"], "date_range": {"start": "2026-01-01", "end": "2026-06-30"}}
    response = api.http.post("/api/metrics/query", json=body, headers={"X-Demo-Region": "Assam"})
    assert response.status_code == 200 and response.json()["label"] == "governed_metric"
    assert fake_semantic == [body] and api.db.calls[0][2] == "Assam"


def test_an_unknown_metric_is_404(api):
    assert api.http.post("/api/metrics/query", json={"metric_name": "revenue"}).status_code == 404


def test_an_unsupported_filter_op_is_422(api):
    body = {"metric_name": "dso", "filters": [{"dimension": "region", "op": "like", "value": "A%"}]}
    assert api.http.post("/api/metrics/query", json=body).status_code == 422


def test_a_query_the_compiler_rejects_is_422(api, monkeypatch):
    def reject(*_args):
        raise semantic.InvalidQuery("dso has no dimension 'sku'")

    monkeypatch.setattr(semantic, "compile_query", reject)
    response = api.http.post("/api/metrics/query", json={"metric_name": "dso", "group_by": ["sku"]})
    assert (response.status_code, response.json()["detail"]) == (422, "dso has no dimension 'sku'")


def test_a_database_failure_is_502(api, monkeypatch):
    def fail(*_args):
        raise readonly_db.QueryError("the database is unavailable")

    monkeypatch.setattr(readonly_db, "run", fail)
    assert api.http.post("/api/metrics/query", json={"metric_name": "dso"}).status_code == 502


@pytest.mark.parametrize(("query", "as_of"), [("", None), ("?as_of=2026-03-01", dt.date(2026, 3, 1))])
def test_anomalies_read_as_of_a_date_or_the_latest_snapshot(api, query, as_of):
    response = api.http.get(f"/api/anomalies{query}")
    assert response.status_code == 200 and api.db.calls[0][1] == {"as_of": as_of, "detector": None, "failure_mode": None}


def test_anomalies_can_be_filtered_to_one_detector(api):
    assert api.http.get("/api/anomalies?detector=lot_scan").status_code == 200
    assert api.db.calls[0][1] == {"as_of": None, "detector": "lot_scan", "failure_mode": None}
    assert api.http.get("/api/anomalies?detector=everything").status_code == 422


def test_a_malformed_as_of_is_422(api):
    assert api.http.get("/api/anomalies?as_of=yesterday").status_code == 422


def test_meta_frames_the_data(api, monkeypatch):
    monkeypatch.setattr(handlers, "data_window", lambda region: {"data_start": "2023-10-01", "as_of": "2026-09-23"})
    body = api.http.get("/api/meta").json()
    assert body == {"data_start": "2023-10-01", "as_of": "2026-09-23", "provisional_days": 17,
                    "regions": ["South Bengal", "North Bengal & Sikkim", "Assam", "North East", "Bihar & Jharkhand",
                                "Odisha", "ALL"]}


def test_the_dashboard_origin_may_call_the_api(api):
    preflight = {"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type,x-demo-region"}
    response = api.http.options("/api/ask", headers=preflight)
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_other_origins_get_no_cors_grant(api):
    response = api.http.get("/api/anomalies", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
