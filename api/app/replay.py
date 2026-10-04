"""Recorded Ask answers, written by the eval harness (evals/run_eval.py) and served when live mode is off (D29).

One file per model in recordings/, shipped in the API image. Each answer is exactly what /api/ask returned during
that eval run, with the run's model, date and region claim, and whether the eval scored it correct.
"""

import json
from pathlib import Path

from app import config

RECORDINGS = Path(__file__).with_name("recordings")
_SUMMARY = ("provider", "model", "effort", "recorded_at", "as_of", "region", "status", "git_commit")

# Questions whose answers read detector flags, and so changed when detector v2 replaced v1 (decisions D48). A
# recording made before the switch shows their v1 figures, which the dashboard no longer does, so they carry a note.
DETECTOR_V2_SINCE = "2026-10-02"
DETECTOR_V1_ANSWERS = frozenset({"SL16", "FG16", "MH02", "MH10", "MH12"})
DETECTOR_V1_NOTE = (
    "Recorded under detector v1. On 2 October 2026 the dashboard switched to detector v2 (decisions D48), which "
    "flags fewer distributors, so this answer's figures differ from what the dashboard shows now. It's shown as served."
)


def load_all() -> list[dict]:
    recordings = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(RECORDINGS.glob("*.json"))]
    for r in recordings:
        r.setdefault("provider", "anthropic")  # recordings from before the provider layer
    return recordings


def load() -> dict | None:
    """The newest recording from the configured provider, else the newest one; None before any eval run."""
    recordings = load_all()
    if not recordings:
        return None
    own = [r for r in recordings if r["provider"] == config.PROVIDER]
    return max(own or recordings, key=lambda r: r["recorded_at"])


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
    answers = [with_note(answer, recording["recorded_at"]) for answer in recording["answers"]] if same_claim else []
    return {"recording": summary(recording), "answers": answers, "withheld": not same_claim}


def with_note(answer: dict, recorded_at: str) -> dict:
    stale = answer["id"] in DETECTOR_V1_ANSWERS and recorded_at[:10] < DETECTOR_V2_SINCE
    return {**answer, "note": DETECTOR_V1_NOTE if stale else None}
