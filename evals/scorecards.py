"""The comparison table behind the README scorecard, built from the committed run files (decisions D38).

    python evals/scorecards.py            # markdown table of every complete run in evals/results/runs/

Only complete runs are tabled. A file named <provider>__<mode>__<model>__<label>.json (e.g. __before-D36) is an
earlier, superseded run kept on record and is shown with that label; the unlabelled file is the current run.
"""

import json
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parent / "results" / "runs"


def load(folder: Path = RUNS) -> list[dict]:
    rows = []
    for path in sorted(folder.glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("status") != "complete" or "scorecard" not in run:
            continue
        card, meta = run["scorecard"], run["meta"]
        parts = path.stem.split("__")
        rows.append({
            "provider": meta["provider"], "mode": meta["mode"], "model": meta["model"],
            "label": parts[3] if len(parts) > 3 else "current", "date": meta["timestamp"][:10],
            "settings": meta.get("settings", {}), "accuracy": card["execution_accuracy"],
            "refusal": card["refusal_correctness"], "confidently_wrong": len(card["confidently_wrong"]),
            "median_ms": card["median_latency_ms"], "p95_ms": card["p95_latency_ms"],
            "tokens": card["tokens_per_question"], "infra": card.get("infra_retries", 0),
            "rate_waits": card.get("rate_limit_waits", 0), "by_category": card["accuracy_by_category"],
        })
    return sorted(rows, key=lambda r: (r["label"] != "current", r["provider"], r["mode"], r["label"]))


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _secs(ms: int | None) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f} s"


def markdown(rows: list[dict]) -> str:
    header = ("| Provider / model | Mode | Run | Execution accuracy | Refusal correctness | Confidently wrong | "
              "Latency median / p95 | Tokens / question (in / out) | Infra retries | Date |")
    lines = [header, "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['provider']} / `{r['model']}` | {r['mode']} | {r['label']} | {_pct(r['accuracy'])} | "
            f"{_pct(r['refusal'])} | {r['confidently_wrong']} | {_secs(r['median_ms'])} / {_secs(r['p95_ms'])} | "
            f"{r['tokens']['input']:,} / {r['tokens']['output']:,} | {r['infra']} | {r['date']} |"
        )
    return "\n".join(lines)


def main() -> int:
    rows = load()
    print(markdown(rows))
    categories = sorted({c for r in rows for c in r["by_category"]})
    print("\n| Run | " + " | ".join(categories) + " |\n|---|" + "---|" * len(categories))
    for r in rows:
        print(f"| {r['provider']} {r['mode']} ({r['label']}) | "
              + " | ".join(_pct(r["by_category"].get(c)) for c in categories) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
