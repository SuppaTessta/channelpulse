"""The Weekly Brief's numbers check and narration fallback (decisions D41). No database: facts run fake queries."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from app import brief, config
from app.agent.providers import ProviderError
from app.guardrails.readonly_db import QueryResult

WEEK = dt.date(2026, 9, 14)
VALUES = {"primary": 82_200_000.0, "primary_prev": 70_300_000.0, "secondary": 76_300_000.0,
          "secondary_prev": 91_900_000.0, "days_of_stock": 43.65, "stockout": 0.036, "at_risk": 6, "claims": 147,
          "claims_prev": 121, "claim_cost": 582_000.0, "top_failure_mode": "base_crack", "top_failure_claims": 51,
          "new_flags": {"distributor_health": 4}}


def result(value) -> QueryResult:
    return QueryResult(sql=f"select {value!r}", columns=["v"], rows=[[value]], row_cap_hit=False, duration_ms=1)


@pytest.fixture
def fake_facts(monkeypatch):
    """facts() with every query answering from VALUES (or `live`, to change a value between runs)."""
    live = dict(VALUES)

    def facts(start, region):
        return {k: brief.Fact(k, k, kind, run=lambda k=k: result(live[k]), pick=lambda r: r.rows[0][0],
                              metric=None if k == "new_flags" else "m")
                for k, kind in KINDS.items()}

    monkeypatch.setattr(brief, "facts", facts)
    return live


KINDS = {"primary": "money", "primary_prev": "money", "secondary": "money", "secondary_prev": "money",
         "days_of_stock": "days", "stockout": "percent", "at_risk": "count", "claims": "count", "claims_prev": "count",
         "claim_cost": "money", "top_failure_mode": "text", "top_failure_claims": "count", "new_flags": "flags"}


def provider(sections=None, error=None):
    def complete(*_, **__):
        if error:
            raise error
        text = json.dumps({"answer_text": json.dumps({"sections": sections})})
        return SimpleNamespace(text=text)
    return SimpleNamespace(model="m-1", complete=complete)


@pytest.mark.parametrize(("kind", "value", "shown"), [
    ("money", 82_200_000, "₹8.22 crore"), ("money", 582_000, "₹5.82 lakh"), ("money", 9_500, "₹9,500"),
    ("percent", 0.036, "3.6%"), ("days", 43.65, "43.6 days"), ("count", 1234, "1,234"), ("money", None, "n/a"),
    ("flags", {"lot_scan": 1, "stuffing": 12}, "1 resin-lot, 12 stuffing"), ("flags", {}, "none")])
def test_display(kind, value, shown):
    assert brief.display(kind, value) == shown


def test_the_template_brief_passes_the_check(fake_facts):
    b = brief.build(WEEK, "ALL", dt.date(2026, 9, 23), None)
    assert (b["status"], b["narration"]["by"], b["check"]["problems"]) == ("verified", "template", [])
    texts = [x["text"] for s in b["sections"] for x in s["sentences"]]
    assert "Sell-in to distributors was ₹8.22 crore, against ₹7.03 crore the week before." in texts
    assert b["provisional"] and b["facts"]["primary"]["display"] == "₹8.22 crore"


def test_a_narration_stating_a_number_no_query_returned_is_blocked(fake_facts, monkeypatch):
    monkeypatch.setattr(config, "ASK_LIVE", True)
    invented = [{"title": "Channel", "sentences": [
        {"text": "Sell-in was ₹8.22 crore, up 17% on the week before.", "facts": ["primary", "primary_prev"]}]}]
    b = brief.build(WEEK, "ALL", dt.date(2026, 9, 23), provider(invented))
    assert (b["status"], b["narration"]["by"]) == ("verified", "template")
    assert "17%" in " ".join(b["narration"]["blocked"])


def test_a_faithful_narration_is_served(fake_facts, monkeypatch):
    monkeypatch.setattr(config, "ASK_LIVE", True)
    good = [{"title": "Channel", "sentences": [{"text": "Sell-in reached ₹8.22 crore.", "facts": ["primary"]}]}]
    b = brief.build(WEEK, "ALL", dt.date(2026, 9, 23), provider(good))
    assert (b["narration"], b["sections"]) == ({"by": "model", "model": "m-1", "blocked": []}, good)


def test_without_live_mode_the_model_is_never_called(fake_facts, monkeypatch):
    monkeypatch.setattr(config, "ASK_LIVE", False)
    b = brief.build(WEEK, "ALL", dt.date(2026, 9, 23), provider(error=AssertionError("called")))
    assert b["narration"]["by"] == "template"


def test_an_unusable_narration_falls_back_to_the_template(fake_facts, monkeypatch):
    monkeypatch.setattr(config, "ASK_LIVE", True)
    b = brief.build(WEEK, "ALL", dt.date(2026, 9, 23), provider(error=ProviderError("down", kind="infrastructure")))
    assert b["narration"]["by"] == "template" and b["narration"]["blocked"] and b["status"] == "verified"


def test_a_value_that_changes_on_re_execution_blocks_the_brief(fake_facts, monkeypatch):
    runs = {"n": 0}
    original = brief.Fact.execute

    def execute(self):
        runs["n"] += 1
        if runs["n"] > len(KINDS) and self.id == "claims":
            fake_facts["claims"] = 150  # the data changed between building and checking
        return original(self)

    monkeypatch.setattr(brief.Fact, "execute", execute)
    b = brief.build(WEEK, "ALL", dt.date(2026, 9, 23), None)
    assert b["status"] == "blocked" and b["sections"] == []
    problems = b["check"]["problems"]
    assert problems[0] == "claims: 147 on the page, 150 on re-execution"
    assert len(problems) == 2 and "states 147, which no cited query returned" in problems[1]


def test_float_noise_below_1e5_is_not_a_change():
    assert brief._same(43.654685246465405, 43.654642161539996) and not brief._same(43.65, 43.75)


def test_the_endpoint_rejects_a_week_that_is_not_a_complete_monday(api, monkeypatch):
    monkeypatch.setattr(brief, "weeks", lambda region: ["2026-09-14", "2026-09-07"])
    assert api.http.get("/api/brief?week=2026-09-15").status_code == 422
