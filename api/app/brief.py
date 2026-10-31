"""The Weekly Channel & Quality Brief (Part C 3, decisions D41): one page for a chosen Monday-to-Sunday week.

Every figure is a fact: one query, governed metric or detector, run under the viewer's region claim, and every
sentence cites the facts it states. Narration is the model's in live mode, else a deterministic template.
Before a brief is served, the numbers check re-executes every cited query: a sentence whose figures don't match its
cited facts, or a fact whose value changed on re-execution, fails it. A model narration that fails is blocked and
the template is served in its place, with the reasons; a template that fails (the data changed underneath) blocks
the brief.
"""

import datetime as dt
import functools
import json
import logging
import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app import config, semantic
from app.agent.providers import AnthropicProvider, ProviderError
from app.agent.response import figures, traced
from app.guardrails import readonly_db

log = logging.getLogger("channelpulse.api")

WEEKS_SQL = """\
select distinct week_start from marts.dim_date
where is_complete_week order by week_start desc limit 104"""
# New detector flags whose first flag falls in the week, at the week's last snapshot.
FLAGS_SQL = """\
select detector, count(distinct (entity_id, failure_mode, details ->> 'category')) as new_flags
from marts.mart_anomaly_flags
where snapshot_date = (select max(snapshot_date) from marts.mart_anomaly_flags where snapshot_date <= %(end)s)
  and first_flag_date between %(start)s and %(end)s
group by detector
order by detector"""

DETECTORS = {"lot_scan": "resin-lot", "installer_scan": "installer", "stuffing": "stuffing",
             "distributor_health": "distributor-health"}


@dataclass
class Fact:
    id: str
    label: str
    kind: str  # money, count, days, percent, flags (detector: count), text
    run: Callable[[], readonly_db.QueryResult]
    pick: Callable[[readonly_db.QueryResult], object]
    metric: str | None = None  # the governed metric, when there is one
    value: object = None
    sql: str = ""

    def execute(self) -> object:
        result = self.run()
        self.sql = result.sql
        return self.pick(result)

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "kind": self.kind, "metric": self.metric, "value": self.value,
                "display": display(self.kind, self.value), "sql": self.sql,
                "source": "governed_metric" if self.metric else "detector_query"}


def display(kind: str, value) -> str:
    """How the brief states a value; the numbers check reads it back with response.figures."""
    if value is None:
        return "n/a"
    if kind == "money":
        v = float(value)
        return f"₹{v / 1e7:.2f} crore" if v >= 1e7 else f"₹{v / 1e5:.2f} lakh" if v >= 1e5 else f"₹{v:,.0f}"
    if kind == "percent":
        return f"{100 * float(value):.1f}%"
    if kind == "days":
        return f"{float(value):.1f} days"
    if kind == "count":
        return f"{int(value):,}"
    if kind == "flags":
        return ", ".join(f"{n} {DETECTORS.get(k, k)}" for k, n in value.items()) or "none"
    return str(value)


def _metric(name: str, start: dt.date, end: dt.date, region: str, group_by=(), filters=()) -> Callable:
    def run() -> readonly_db.QueryResult:
        date_range = {"start": start.isoformat(), "end": end.isoformat()}
        return readonly_db.run(semantic.compile_query(name, list(filters), list(group_by), date_range), None, region)
    return run


def _last(column: int = -1) -> Callable:
    return lambda r: r.rows[-1][column] if r.rows else None


def _first(column: int) -> Callable:
    return lambda r: r.rows[0][column] if r.rows else None


def facts(start: dt.date, region: str) -> dict[str, Fact]:
    end, prev, prev_end = start + dt.timedelta(days=6), start - dt.timedelta(days=7), start - dt.timedelta(days=1)
    week = {"start": start.isoformat(), "end": end.isoformat()}
    m = functools.partial(_metric, region=region)
    items = [
        Fact("primary", "Primary sales (sell-in)", "money", m("primary_sales_value", start, end), _last(),
             "primary_sales_value"),
        Fact("primary_prev", "Primary sales, week before", "money", m("primary_sales_value", prev, prev_end), _last(),
             "primary_sales_value"),
        Fact("secondary", "Secondary sales (sell-out, list price)", "money", m("secondary_sales_value", start, end),
             _last(), "secondary_sales_value"),
        Fact("secondary_prev", "Secondary sales, week before", "money", m("secondary_sales_value", prev, prev_end),
             _last(), "secondary_sales_value"),
        Fact("days_of_stock", "Channel days of stock at the week's close", "days",
             m("channel_days_of_stock", start, end, group_by=["metric_time__week"]), _last(), "channel_days_of_stock"),
        Fact("stockout", "Stock-out rate", "percent", m("stockout_rate", start, end), _last(), "stockout_rate"),
        Fact("at_risk", "Distributors at risk", "count", m("at_risk_distributors", start, start), _last(),
             "at_risk_distributors"),
        Fact("claims", "Warranty claims filed", "count", m("warranty_claims", start, end), _last(), "warranty_claims"),
        Fact("claims_prev", "Warranty claims, week before", "count", m("warranty_claims", prev, prev_end), _last(),
             "warranty_claims"),
        Fact("claim_cost", "Warranty claim cost", "money", m("warranty_claim_cost", start, end), _last(),
             "warranty_claim_cost"),
        # Grouped results come back largest first, so the first row is the top failure mode.
        Fact("top_failure_mode", "Most common failure mode", "text",
             m("warranty_claims", start, end, group_by=["claim__failure_mode"]), _first(0), "warranty_claims"),
        Fact("top_failure_claims", "Claims with that failure mode", "count",
             m("warranty_claims", start, end, group_by=["claim__failure_mode"]), _first(1), "warranty_claims"),
        Fact("new_flags", "New detector flags", "flags", lambda: readonly_db.run(FLAGS_SQL, week, region),
             lambda r: {d: n for d, n in r.rows}),
    ]
    return {f.id: f for f in items}


# --- narration ------------------------------------------------------------------------------------------------------


def template(fs: dict[str, Fact], provisional: bool) -> list[dict]:
    d = {k: display(f.kind, f.value) for k, f in fs.items()}
    channel = [
        _s(f"Sell-in to distributors was {d['primary']}, against {d['primary_prev']} the week before.",
           "primary", "primary_prev"),
        _s(f"Sell-out to retailers was {d['secondary']}, against {d['secondary_prev']} the week before.",
           "secondary", "secondary_prev"),
        *([_s("Sell-out for the latest weeks is still being reported, so these figures will rise.")] if provisional
          else []),
        _s(f"The channel closed the week holding {d['days_of_stock']} of stock, with a stock-out rate of "
           f"{d['stockout']}.", "days_of_stock", "stockout"),
        _s(f"The health score flagged {d['at_risk']} distributors at risk.", "at_risk"),
    ]
    quality = [
        _s(f"{d['claims']} warranty claims were filed, against {d['claims_prev']} the week before, costing "
           f"{d['claim_cost']}.", "claims", "claims_prev", "claim_cost"),
        *([_s(f"The most common failure mode was {d['top_failure_mode'].replace('_', ' ')}, with "
              f"{d['top_failure_claims']} claims.", "top_failure_mode", "top_failure_claims")]
          if fs["top_failure_mode"].value else []),
        _s(f"New detector flags this week: {d['new_flags']}." if fs["new_flags"].value
           else "No detector raised a new flag this week.", "new_flags"),
    ]
    return [{"title": "Channel", "sentences": channel}, {"title": "Quality", "sentences": quality}]


def _s(text: str, *fact_ids: str) -> dict:
    return {"text": text, "facts": list(fact_ids)}


NARRATOR_PROMPT = """\
You write the weekly Channel & Quality Brief for Gangasagar Polymers, a synthetic building-products manufacturer.
You get the week's facts as JSON: id, label, and display, the exact text of each figure. Write the brief as two
sections, Channel and Quality, of two to five plain sentences each, for a sales and quality manager.

Rules: state figures only by copying a fact's display text exactly; never compute, round or invent a number; cite in
each sentence the ids of every fact it states. Say nothing the facts don't support.

Reply with the final answer: put in answer_text a JSON object
{"sections": [{"title": "Channel" | "Quality", "sentences": [{"text": "...", "facts": ["id", ...]}]}]}
and set refused false, refusal_reason null, clarifying_question null, evidence_tool_use_ids [] and chart_hint type none.
"""


def narrate(provider: AnthropicProvider, fs: dict[str, Fact]) -> list[dict]:
    """The model's sections; raises ValueError or ProviderError when it can't give usable ones."""
    payload = [{"id": f.id, "label": f.label, "display": display(f.kind, f.value)} for f in fs.values()]
    turn = provider.complete(NARRATOR_PROMPT, [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                             [], final_only=True, timeout=90)
    sections = json.loads(json.loads(turn.text)["answer_text"])["sections"]
    if not (isinstance(sections, list) and all(
            isinstance(s["title"], str) and all(isinstance(x["text"], str) and set(x["facts"]) <= fs.keys()
                                                for x in s["sentences"]) for s in sections)):
        raise ValueError("the narration isn't in the brief's shape or cites unknown facts")
    return sections


# --- the numbers check -------------------------------------------------------------------------------------------


def numbers_check(sections: list[dict], fs: dict[str, Fact]) -> list[str]:
    """Re-execute every cited query, then check each sentence's figures against its cited facts. Returns problems."""
    cited = sorted({i for s in sections for x in s["sentences"] for i in x["facts"]})
    problems = []
    rechecked = dict(zip(cited, _execute_all([fs[i] for i in cited]), strict=True))
    for fid, again in rechecked.items():
        if not _same(again, fs[fid].value):
            problems.append(f"{fid}: {display(fs[fid].kind, fs[fid].value)} on the page, "
                            f"{display(fs[fid].kind, again)} on re-execution")
    for section in sections:
        for sentence in section["sentences"]:
            pool = [n for i in sentence["facts"] for n in _numbers(rechecked[i])]
            # ponytail: figures() skips bare single digits and years, so a wrong "3 flags" isn't caught; a unit
            # or a comma makes it checkable.
            untraced = [f.text for f in figures(sentence["text"]) if not traced(f, pool)]
            if untraced:
                problems.append(f"\"{sentence['text']}\" states {', '.join(untraced)}, which no cited query returned")
    return problems


def _execute_all(items: list[Fact]) -> list:
    """Run the facts' queries four at a time, like a dashboard page (MetricFlow compiles one at a time anyway)."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(Fact.execute, items))


def _same(a, b) -> bool:
    """Equal, floats within 1e-5 relative: sums over the marts' float4 columns (avg_daily_secondary_units) vary in the
    fifth significant digit between runs, as parallel workers add them in a different order (D41)."""
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-5)
    return a == b


def _numbers(value) -> list[float]:
    if isinstance(value, dict):
        return [float(v) for v in value.values()]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return [float(value)]
    return []


# --- the brief ------------------------------------------------------------------------------------------------------


def weeks(region: str) -> list[str]:
    return [str(row[0])[:10] for row in readonly_db.run(WEEKS_SQL, None, region).rows]


def build(start: dt.date, region: str, as_of: dt.date, provider: AnthropicProvider | None) -> dict:
    fs = facts(start, region)
    for f, value in zip(fs.values(), _execute_all(list(fs.values())), strict=True):
        f.value = value
    end = start + dt.timedelta(days=6)
    provisional = end > as_of - dt.timedelta(days=config.PROVISIONAL_DAYS)
    narration = {"by": "template", "model": None, "blocked": []}
    sections = None
    if provider is not None and config.ASK_LIVE and config.BRIEF_NARRATE:
        try:
            sections = narrate(provider, fs)
            narration |= {"by": "model", "model": provider.model}
        except (ProviderError, ValueError, KeyError, TypeError) as e:
            log.warning("brief narration unavailable: %s", e)
            narration["blocked"] = [f"The model's narration was unusable ({type(e).__name__}), so the template was used."]
    if sections is not None and (problems := numbers_check(sections, fs)):
        narration = {"by": "template", "model": None,
                     "blocked": ["The model's narration failed the numbers check and was blocked:", *problems]}
        sections = None
    if sections is None:
        sections = template(fs, provisional)
        problems = numbers_check(sections, fs)
    cited = sorted({i for s in sections for x in s["sentences"] for i in x["facts"]})
    return {
        "week": {"start": start.isoformat(), "end": end.isoformat()},
        "as_of": as_of.isoformat(),
        "provisional": provisional,
        "status": "blocked" if problems else "verified",
        "sections": [] if problems else sections,
        "facts": {i: fs[i].public() for i in cited},
        "check": {"queries_rechecked": len(cited), "problems": problems},
        "narration": narration,
    }
