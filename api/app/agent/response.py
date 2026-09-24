"""Code, not the model, assembles the PLAN §8 response: evidence, SQL, data, chart, label and verification note."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from app import config
from app.tools.handlers import AD_HOC, GOVERNED

REFUSED = "refused"
NO_EVIDENCE_ANSWER = "I couldn't back an answer with query results from the marts, so I won't state one."


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    result: dict | None  # None when the call failed
    error: str | None
    duration_ms: int


def assemble(final: dict, calls: dict[str, ToolCall], trace_id: str) -> dict:
    """Build the response from the model's final JSON and the tool calls this conversation actually made."""
    if final["refused"]:
        answer = final["answer_text"] or final["refusal_reason"] or "I can't answer that from the governed data."
        return refusal(answer, "Refused by the model; no figures reported.", trace_id)
    cited = dict.fromkeys(final["evidence_tool_use_ids"])  # keeps the model's order: primary first
    evidence = [calls[i] for i in cited if i in calls and calls[i].result is not None]
    if not evidence:
        # Not backed by any successful tool result, so its figures are not shown at all.
        return refusal(NO_EVIDENCE_ANSWER, "Refused: the answer had no successful query result behind it.", trace_id)
    primary = next((call for call in evidence if call.result.get("data")), None)
    data = primary.result["data"] if primary else None
    return {
        "answer_text": final["answer_text"],
        "sql": list(dict.fromkeys(call.result["sql"] for call in evidence if call.result.get("sql"))),
        "data": data,
        "chart_spec": chart_spec(final["chart_hint"], data),
        "label": AD_HOC if any(call.name == "run_readonly_sql" for call in evidence) else GOVERNED,
        "confidence_note": confidence_note(final["answer_text"], evidence, primary),
        "trace_id": trace_id,
    }


def refusal(answer_text: str, note: str, trace_id: str) -> dict:
    return {
        "answer_text": answer_text,
        "sql": [],
        "data": None,
        "chart_spec": None,
        "label": REFUSED,
        "confidence_note": note,
        "trace_id": trace_id,
    }


def chart_spec(hint: dict, data: dict | None) -> dict | None:
    """The model's chart hint, kept only if it fits the returned columns (and y is numeric)."""
    if not data or not data["rows"] or hint.get("type") not in ("line", "bar", "table"):
        return None
    if hint["type"] == "table":
        return {"type": "table", "x": None, "y": None, "series": None}
    columns = data["columns"]
    x, y, series = hint.get("x"), hint.get("y"), hint.get("series")
    if x not in columns or y not in columns or (series is not None and series not in columns):
        return None
    y_at = columns.index(y)
    if not all(_is_number(row[y_at]) or row[y_at] is None for row in data["rows"]):
        return None
    return {"type": hint["type"], "x": x, "y": y, "series": series}


# --- numbers check ---------------------------------------------------------------------------------------------

_SCALES = {
    "k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "cr": 1e7, "crore": 1e7, "crores": 1e7, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9,
}
# A figure: optional sign and currency, a number (1,23,456 grouping allowed), optional unit. Not part of an
# identifier (Q3, FY25, DIST-0042), a date (2025-09-30) or a time, and not an ordinal (3rd).
_FIGURE = re.compile(
    r"(?<![\w.,/:-])[-−]?(?P<currency>₹|rs\.? ?|inr ?|\$)?"
    r"(?P<number>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?: ?(?P<unit>%|percent|crores?|cr|lakhs?|lacs?|k|thousand|mn|million|bn|billion|x|×))?"
    r"(?![\w/:]|[-.,]\d)",
    re.IGNORECASE,
)
_NUMBER_IN_TEXT = re.compile(r"\d+(?:\.\d+)?")
_RELATIVE_TOLERANCE = 0.005


@dataclass(frozen=True)
class Figure:
    text: str
    value: float  # absolute value in base units (a percent stays in percent)
    tolerance: float  # half the last displayed digit, or 0.5% of the value if larger
    percent: bool


def figures(text: str) -> list[Figure]:
    """Figures stated in an answer. Bare years (1900-2100) and bare single digits (top 5, Line 2) aren't counted."""
    found = []
    for match in _FIGURE.finditer(text):
        number, unit = match["number"], (match["unit"] or "").lower()
        value = float(number.replace(",", ""))
        bare = not (match["currency"] or unit) and not set(number) & {",", "."}
        if bare and (value < 10 or 1900 <= value <= 2100):
            continue
        decimals = len(number.partition(".")[2])
        scale = _SCALES.get(unit, 1.0)
        value *= scale
        tolerance = max(0.5 * 10**-decimals * scale, _RELATIVE_TOLERANCE * value)
        found.append(Figure(match.group(0), value, tolerance, unit in ("%", "percent")))
    return found


def confidence_note(answer_text: str, evidence: list[ToolCall], primary: ToolCall | None) -> str:
    """One line saying how many stated figures appear, within rounding, in the evidence behind the answer."""
    stated = figures(answer_text)
    if stated:
        pool = [number for call in evidence for number in _numbers(call.result)]
        untraced = [figure.text for figure in stated if not _traced(figure, pool)]
        count = len(stated)
        note = f"{count - len(untraced)}/{count} figure{'' if count == 1 else 's'} traced to query results"
        note += f"; untraced: {', '.join(untraced[:3])}." if untraced else "."
    else:
        note = "No figures stated, so there was nothing to trace."
    if primary and primary.result.get("row_cap_hit"):
        note += f" Results are capped at {config.ROW_CAP} rows."
    return note


def _traced(figure: Figure, pool: list[float]) -> bool:
    # A percent may be stored as a ratio (0.125 for 12.5%). Signs are ignored: "fell 45%" can match -0.45.
    for number in pool:
        for candidate in (abs(number), abs(number) * 100) if figure.percent else (abs(number),):
            if abs(candidate - figure.value) <= figure.tolerance:
                return True
    return False


def _numbers(value) -> Iterator[float]:
    """Every number in a tool result: cells, nested JSON, row counts, and numbers inside text such as the SQL."""
    if _is_number(value):
        yield float(value)
    elif isinstance(value, str):
        yield from (float(n) for n in _NUMBER_IN_TEXT.findall(value))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _numbers(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _numbers(item)


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
