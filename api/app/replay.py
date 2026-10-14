"""Recorded Ask answers, written by the eval harness (evals/run_eval.py) and served when live mode is off (D29).

One file per model in recordings/, shipped in the API image. Each answer is exactly what /api/ask returned during
that eval run, with the run's model, date and region claim, and whether the eval scored it correct.
"""

import json
from pathlib import Path

RECORDINGS = Path(__file__).with_name("recordings")
_SUMMARY = ("provider", "model", "effort", "recorded_at", "as_of", "region", "status", "git_commit")


def load_all() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(RECORDINGS.glob("*.json"))]


def load() -> dict | None:
    """The newest recording; None before any eval run."""
    return max(load_all(), key=lambda r: r["recorded_at"], default=None)


def summary(recording: dict | None) -> dict | None:
    if recording is None:
        return None
    return {key: recording[key] for key in _SUMMARY} | {"count": len(recording["answers"])}


def for_region(region: str) -> dict:
    """The recording's answers, but only under the region claim they were recorded with: under any other claim they
    could show rows that claim may not see, so they're withheld (the summary still says what exists)."""
    recording = load()
    if recording is None:
        return {"recording": None, "answers": [], "withheld": False}
    same_claim = region == recording["region"]
    answers = recording["answers"] if same_claim else []
    return {"recording": summary(recording), "answers": answers, "withheld": not same_claim}

