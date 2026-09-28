"""Pure scoring for the golden-set eval: agent evidence vs golden answers, and the scorecard. No DB, no API key.

A table is {"columns": [...], "rows": [[...]]} with JSON-safe cells, the shape both the golden SQL (after json_safe)
and the agent's tool results use. Agent columns are matched to golden ones by their values, never by name, since
the agent's columns carry MetricFlow names (distributor__region, metric_time__month).
"""

import math
import re
import statistics

REFUSED = "refused"
ERROR = "error"
TRAP = "trap"

_MIDNIGHT = re.compile(r"(\d{4}-\d{2}-\d{2})[t ]00:00:00(?:\.0+)?(?:z|[+-]00:?00)?")
_PUNCTUATION = re.compile(r"[\s_\-‐-―/]+")
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")
# A sentence with any of these is taken as rejecting a claim, not making it ("not a batch problem").
_NEGATION = re.compile(
    r"\b(?:not|no|never|nor|rather than|instead of|rules? out|ruled out|unlikely)\b|n't\b", re.IGNORECASE
)


def number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def key(value) -> str | None:
    """A cell as a comparable key: text casefolded and trimmed, midnight timestamps as days, 2.0 as 2."""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if (n := number(value)) is not None:
        return str(int(n)) if n.is_integer() else repr(n)
    text = str(value).strip().casefold()
    midnight = _MIDNIGHT.fullmatch(text)
    return midnight[1] if midnight else text


def close(actual, golden, tolerance_rel: float) -> bool:
    """Within tolerance_rel of golden, inclusive; a golden zero needs an (almost) exact zero."""
    a, g = number(actual), number(golden)
    if a is None or g is None:
        return False
    return abs(a - g) <= max(tolerance_rel * abs(g), 1e-9)


def records(table: dict) -> list[dict]:
    return [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]


# --- comparisons ------------------------------------------------------------------------------------------------


def match_scalar(golden: dict, spec: dict, tables: list[dict]) -> dict:
    """Every value in the golden's single row must appear as a number somewhere in the agent's evidence."""
    (row,) = records(golden)
    pool = [cell for table in tables for data_row in table["rows"] for cell in data_row if number(cell) is not None]
    found = {column: any(close(cell, value, spec["tolerance_rel"]) for cell in pool) for column, value in row.items()}
    return {"ok": all(found.values()), "found": found, "golden": row}


def map_keys(golden_rows: list[dict], key_spec: list, table: dict) -> list[tuple[str, int]] | None:
    """For each golden key, the (golden column, agent column index) whose values overlap most; None if one has none.

    A key entry is a golden column or a list of alternatives (distributor_id or distributor_name)."""
    agent_values = [{key(row[i]) for row in table["rows"]} for i in range(len(table["columns"]))]
    mapping, used = [], set()
    for entry in key_spec:
        alternatives = entry if isinstance(entry, list) else [entry]
        candidates = [
            (len({key(row[column]) for row in golden_rows} & agent_values[i]), column, i)
            for column in alternatives
            for i in range(len(agent_values))
            if i not in used
        ]
        overlap, column, index = max(candidates, key=lambda c: c[0], default=(0, None, None))
        if not overlap:
            return None
        mapping.append((column, index))
        used.add(index)
    return mapping


def match_keyed(golden: dict, spec: dict, tables: list[dict]) -> dict:
    """Each golden key must be in some evidence table with every golden value, within tolerance, in its row.

    Tables are checked one at a time, so a comparison answered with one query per period still matches."""
    golden_rows, values, tolerance = records(golden), spec["values"], spec["tolerance_rel"]
    hits: set[tuple[int, str]] = set()
    extra: set[tuple] = set()
    for table in tables:
        mapping = map_keys(golden_rows, spec["keys"], table)
        if mapping is None:
            continue
        key_columns = {index for _, index in mapping}
        by_key: dict[tuple, list[list]] = {}
        for row in table["rows"]:
            by_key.setdefault(tuple(key(row[index]) for _, index in mapping), []).append(row)
        golden_keys = set()
        table_hits = set()
        for position, golden_row in enumerate(golden_rows):
            golden_key = tuple(key(golden_row[column]) for column, _ in mapping)
            golden_keys.add(golden_key)
            cells = [cell for row in by_key.get(golden_key, []) for i, cell in enumerate(row) if i not in key_columns]
            table_hits |= {(position, v) for v in values if any(close(c, golden_row[v], tolerance) for c in cells)}
        if table_hits:
            hits |= table_hits
            extra |= by_key.keys() - golden_keys
    missing = [
        {"key": [golden_row[entry[0] if isinstance(entry, list) else entry] for entry in spec["keys"]], "value": v}
        for position, golden_row in enumerate(golden_rows)
        for v in values
        if (position, v) not in hits
    ]
    extra_ok = spec.get("allow_extra_keys", False) or not extra
    return {
        "ok": not missing and extra_ok,
        "matched": len(hits),
        "expected": len(golden_rows) * len(values),
        "missing": missing[:10],
        "extra_keys": sorted(map(list, extra), key=str)[:10],
        "extra_keys_allowed": spec.get("allow_extra_keys", False),
    }


def plain(text: str) -> str:
    """Casefolded, with underscores, hyphens, slashes and runs of space as one space: base_crack ~ base-crack."""
    return _PUNCTUATION.sub(" ", text.casefold()).strip()


def mentions(text: str, term: str) -> bool:
    """term appears in text at a word start (so 'base crack' matches 'base cracks', 'D0246' doesn't match 'XD0246')."""
    return re.search(rf"(?<![a-z0-9]){re.escape(plain(term))}", plain(text)) is not None


def match_rubric(golden: dict, spec: dict, answer_text: str, tools_used: list[str]) -> dict:
    """must_mention terms in the answer, no must_not_mention claim made, and every evidence tool called."""
    (row,) = records(golden)
    missing_mentions = []
    for item in spec.get("must_mention", []):
        terms = item.get("any_of") or [t for column in item["golden"] for t in str(row[column]).split("|")]
        if not any(mentions(answer_text, term) for term in terms):
            missing_mentions.append(terms)
    patterns = spec.get("must_not_mention", [])
    forbidden = [
        sentence
        for sentence in _SENTENCE_END.split(answer_text)
        if not _NEGATION.search(sentence) and any(re.search(p, sentence, re.IGNORECASE) for p in patterns)
    ]
    missing_tools = [
        tool for tool in spec.get("evidence_tools", [])
        if not set(tool if isinstance(tool, list) else [tool]) & set(tools_used)
    ]
    return {
        "ok": not (missing_mentions or forbidden or missing_tools),
        "missing_mentions": missing_mentions,
        "forbidden_claims": forbidden,
        "missing_tools": missing_tools,
        "golden": row,
    }


def score_question(question: dict, golden: dict | None, response: dict | None, tools_used: list[str],
                   tables: list[dict], mode: str = "governed") -> dict:
    """Correctness, refusal, label and confidently-wrong verdicts for one answered (or failed) question.

    Raw mode (decisions D32) has only run_readonly_sql, so a rubric's evidence_tools requirement is dropped (the
    answer is judged on what it says) and every answer is expected to be ad hoc, traps refused."""
    spec = question["compare"]
    expected_label = question["expected_label"]
    if mode == "raw":
        spec = {k: v for k, v in spec.items() if k != "evidence_tools"}
        expected_label = REFUSED if question["category"] == TRAP else "ad_hoc_sql_verify"
    actual_label = response["label"] if response else ERROR
    refused = actual_label == REFUSED
    if spec["type"] == "refusal":
        match = {"ok": refused}
    elif response is None or refused:
        match = {"ok": False, "reason": "no answer" if response is None else "refused"}
    elif spec["type"] == "scalar":
        match = match_scalar(golden, spec, tables)
    elif spec["type"] == "keyed":
        match = match_keyed(golden, spec, tables)
    else:
        match = match_rubric(golden, spec, response["answer_text"], tools_used)
    return {
        "correct": match["ok"],
        "refused": refused,
        "refusal_correct": refused == (question["category"] == TRAP),
        "label_correct": actual_label == expected_label,
        # answered, but wrongly: the count to review by hand
        "confidently_wrong": response is not None and not refused and not match["ok"],
        "match": match,
    }


# --- scorecard --------------------------------------------------------------------------------------------------


def p95(values: list[float]) -> float | None:
    """Nearest-rank 95th percentile."""
    return sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None


def _share(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def scorecard(results: list[dict]) -> dict:
    """Aggregate per-question results; questions skipped by the budget are counted but not scored."""
    ran = [r for r in results if not r.get("skipped")]
    answerable = [r for r in ran if r["category"] != TRAP]
    latencies = [r["latency_ms"] for r in ran if r["latency_ms"] is not None]
    cost = sum(r["cost_usd"] for r in ran)
    categories = dict.fromkeys(r["category"] for r in results)
    return {
        "questions": len(results),
        "scored": len(ran),
        "skipped": len(results) - len(ran),
        "errors": sum(r["actual_label"] == ERROR for r in ran),
        "execution_accuracy": _share([r["correct"] for r in answerable]),
        "accuracy_by_category": {c: _share([r["correct"] for r in ran if r["category"] == c]) for c in categories},
        "refusal_correctness": _share([r["refusal_correct"] for r in ran]),
        "refused_exactly_the_traps": bool(ran) and all(r["refusal_correct"] for r in ran),
        "missed_traps": [r["id"] for r in ran if r["category"] == TRAP and not r["refused"]],
        "false_refusals": [r["id"] for r in answerable if r["refused"]],
        "label_accuracy": _share([r["label_correct"] for r in ran]),
        "confidently_wrong": [r["id"] for r in ran if r["confidently_wrong"]],
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "median_latency_ms": round(statistics.median(latencies)) if latencies else None,
        "p95_latency_ms": p95(latencies),
        "avg_cost_usd": round(cost / len(ran), 5) if ran else None,
        "total_cost_usd": round(cost, 5),
        "total_tokens": {
            kind: sum(r["tokens"][kind] for r in ran) for kind in ("input", "output", "cache_read", "cache_write")
        },
        "tokens_per_question": {
            kind: round(sum(r["tokens"][kind] for r in ran) / len(ran)) if ran else None for kind in ("input", "output")
        },
        # Infrastructure, not the model: never scored, reported separately (decisions D32).
        "infra_retries": sum(r.get("infra_retries", 0) for r in results),
        "rate_limit_waits": sum(r.get("rate_limit_waits", 0) for r in results),
    }


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def markdown(card: dict, meta: dict) -> str:
    """The scorecard as a markdown block for the terminal and the README."""
    who = f"{meta.get('provider', 'anthropic')} / {meta['model']}, {meta.get('mode', 'governed')} mode"
    lines = [
        f"### Eval scorecard: {who} ({meta['effort']}), data as of {meta['as_of']}",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Execution accuracy (non-trap) | {_percent(card['execution_accuracy'])} |",
        *(f"| &nbsp;&nbsp;{c} | {_percent(v)} |" for c, v in card["accuracy_by_category"].items()),
        (
            f"| Refusal correctness | {_percent(card['refusal_correctness'])} "
            f"(refused exactly the traps: {'yes' if card['refused_exactly_the_traps'] else 'no'}) |"
        ),
        f"| Label correctness | {_percent(card['label_accuracy'])} |",
        (
            f"| Confidently wrong (review by hand) | {len(card['confidently_wrong'])}"
            f"{': ' + ', '.join(card['confidently_wrong']) if card['confidently_wrong'] else ''} |"
        ),
        f"| Latency median / p95 | {card['median_latency_ms']} ms / {card['p95_latency_ms']} ms |",
        (
            f"| Tokens per question (input / output) | {card['tokens_per_question']['input']:,} / "
            f"{card['tokens_per_question']['output']:,} |"
            if card["tokens_per_question"]["input"] is not None else "| Tokens per question | n/a |"
        ),
        f"| Cost avg per query / total | ${card['avg_cost_usd']} / ${card['total_cost_usd']} |",
        (
            f"| Infrastructure retries / rate-limit waits (not scored) | {card['infra_retries']} / "
            f"{card['rate_limit_waits']} |"
        ),
        (
            "| Tokens (input / output / cache read / cache write) | "
            f"{' / '.join(f'{n:,}' for n in card['total_tokens'].values())} |"
        ),
        f"| Questions scored / skipped / errors | {card['scored']} / {card['skipped']} / {card['errors']} |",
    ]
    return "\n".join(lines)
