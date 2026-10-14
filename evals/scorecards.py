"""The comparison tables behind the README scorecard, built from the committed run files (decisions D39).

    python evals/scorecards.py            # markdown tables of every complete run in evals/results/runs/
    python evals/scorecards.py --readme   # also rewrite the README block between the scorecard markers

Only complete runs are tabled. A file named anthropic__<mode>__<model>__<label>.json (e.g. __before-fix) is an
earlier, superseded run kept on record and is shown with that label; the unlabelled file is the current run.
Each card is recomputed from the run's stored per-question verdicts, so every run is reported with the same
measures; no verdict is re-scored.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script (make scorecard)

from evals import scoring

RUNS = Path(__file__).resolve().parent / "results" / "runs"
README = Path(__file__).resolve().parents[1] / "README.md"
START, END = "<!-- scorecard:start -->", "<!-- scorecard:end -->"


def load(folder: Path = RUNS) -> list[dict]:
    rows = []
    for path in sorted(folder.glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("status") != "complete" or "scorecard" not in run:
            continue
        results = list(run["results"].values()) if isinstance(run.get("results"), dict) else []
        card = scoring.scorecard(results, run["scorecard"].get("accuracy_threshold")) if results else run["scorecard"]
        meta = run["meta"]
        parts = path.stem.split("__")
        rows.append({
            "provider": meta["provider"], "mode": meta["mode"], "model": meta["model"],
            "label": parts[3] if len(parts) > 3 else "current", "date": meta["timestamp"][:10],
            "settings": meta.get("settings", {}), "questions": card["questions"], "accuracy": card["execution_accuracy"],
            "wrong": {k: len(v) for k, v in card["confidently_wrong_by_kind"].items()}
            if "confidently_wrong_by_kind" in card else None,
            "ambiguous": sum(r["category"] == scoring.CLARIFY for r in results),
            "traps": card.get("trap_refusals"), "refusal": card["refusal_correctness"],
            "median_ms": card["median_latency_ms"], "p95_ms": card["p95_latency_ms"],
            "tokens": card["tokens_per_question"], "cost": card.get("avg_cost_usd"),
            "by_category": card["accuracy_by_category"],
            "results": results,
        })
    return sorted(rows, key=lambda r: (r["label"] != "current", r["model"], r["mode"], r["label"]))


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _secs(ms: int | None) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f} s"


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def _traps(t: dict | None) -> str:
    return "n/a" if t is None else f"{t['router']} + {t['model']} of {t['model_of']}"


def markdown(rows: list[dict]) -> str:
    header = ("| Model | Mode | Run | Questions | Execution accuracy | Wrong answers | "
              "Ambiguous answered without asking | Traps answered | Traps refused: router + model | "
              "Latency median / p95 | Tokens / question (in / out) | Cost / question | Date |")
    lines = [header, "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        w = r["wrong"] or {}
        ambiguous = f"{w.get('ambiguous_answered', 0)} of {r['ambiguous']}" if r["ambiguous"] else "n/a"
        lines.append(
            f"| `{r['model']}` | {r['mode']} | {r['label']} | {r['questions']} | {_pct(r['accuracy'])} | "
            f"{w.get('wrong_answer', 'n/a')} | {ambiguous} | {w.get('trap_answered', 'n/a')} | {_traps(r['traps'])} | "
            f"{_secs(r['median_ms'])} / {_secs(r['p95_ms'])} | {r['tokens']['input']:,} / {r['tokens']['output']:,} | "
            f"{_usd(r['cost'])} | {r['date']} |"
        )
    return "\n".join(lines)


def by_category(rows: list[dict]) -> str:
    categories = sorted({c for r in rows for c in r["by_category"]})
    lines = ["| Run | " + " | ".join(categories) + " |", "|---|" + "---|" * len(categories)]
    for r in rows:
        lines.append(f"| {r['model']} {r['mode']} ({r['label']}) | "
                     + " | ".join(_pct(r["by_category"].get(c)) for c in categories) + " |")
    return "\n".join(lines)


def paired(rows: list[dict]) -> str:
    """Governed against raw on the same model, question by question, for each model with both current runs."""
    current = {(r["model"], r["mode"]): r for r in rows if r["label"] == "current" and r["results"]}
    lines = ["| Model | Answerable questions | Wrong to right | Right to wrong | Both right | Both wrong | McNemar exact p |",
             "|---|---|---|---|---|---|---|"]
    for (model, mode), governed in current.items():
        raw = current.get((model, "raw"))
        if mode != "governed" or raw is None:
            continue
        p = scoring.paired(governed["results"], raw["results"])
        lines.append(f"| `{model}` | {p['questions']} | {p['wrong_to_right']} | {p['right_to_wrong']}"
                     f"{' (' + ', '.join(p['right_to_wrong_ids']) + ')' if p['right_to_wrong_ids'] else ''} | "
                     f"{p['both_right']} | {p['both_wrong']} | {p['mcnemar_p']:.2g} |")
    return "\n".join(lines)


def update_readme(readme: Path, rows: list[dict]) -> None:
    """Replace only the generated block between the markers, so the tables always come from the run files."""
    text = readme.read_text(encoding="utf-8")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    tables = (f"{markdown(rows)}\n\nExecution accuracy by category:\n\n{by_category(rows)}\n\n"
              "Governed against raw on the same model, question by question (answerable questions; each result is "
              f"a single run):\n\n{paired(rows)}") if rows else "No complete eval run yet."
    block = (f"{START}\n<!-- generated by `make scorecard` from evals/results/runs; don't edit by hand -->\n"
             f"{tables}\n{END}")
    readme.write_text(head + block + tail, encoding="utf-8", newline="\n")


def main() -> int:
    rows = load()
    print(markdown(rows) + "\n\n" + by_category(rows) + "\n\n" + paired(rows))
    if "--readme" in sys.argv:
        update_readme(README, rows)
        print(f"\nUpdated the scorecard block in {README.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
