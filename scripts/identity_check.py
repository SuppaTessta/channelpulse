"""Pre-publish check: no identifying term anywhere in the repository or its history (docs/deploy-checklist.md).

    python scripts/identity_check.py [--pattern TERM ...] [--repo PATH]

Terms come from --pattern and from .identity-patterns at the repo root (one per line, # comments), which is
gitignored: the terms themselves must never be committed. Matching is case-insensitive and literal. It searches
every tracked file at every commit on every ref, plus commit messages and author and committer names and emails.
Exit 0 clean, 1 on any match, 2 when there is nothing to search for.
"""

import argparse
import subprocess
import sys
from pathlib import Path

PATTERNS_FILE = ".identity-patterns"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def load_patterns(repo: Path, extra: list[str]) -> list[str]:
    path = repo / PATTERNS_FILE
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [p.strip() for p in [*lines, *extra] if p.strip() and not p.strip().startswith("#")]


def find(repo: Path, pattern: str) -> list[str]:
    hits = []
    revisions = git(repo, "rev-list", "--all").split()
    for start in range(0, len(revisions), 200):  # keep command lines short on Windows
        chunk = revisions[start:start + 200]
        result = subprocess.run(["git", "-C", str(repo), "grep", "-I", "-i", "-F", "-l", "-e", pattern, *chunk],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        hits += [f"file {line.split(':', 1)[-1]} (at {line.split(':', 1)[0][:7]})" for line in result.stdout.splitlines()]
    log = git(repo, "log", "--all", "--format=%h%x09%an <%ae>%x09%cn <%ce>%x09%B%x00")
    for entry in filter(str.strip, log.split("\0")):
        if pattern.lower() in entry.lower():
            hits.append(f"commit {entry.strip().split(chr(9), 1)[0]} (identity or message)")
    return sorted(set(hits))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pattern", action="append", default=[], help="a term to search for (repeatable)")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)

    patterns = load_patterns(args.repo, args.pattern)
    if not patterns:
        print(f"Nothing to search for: add terms to {PATTERNS_FILE} (gitignored) or pass --pattern.", file=sys.stderr)
        return 2
    found = False
    for n, pattern in enumerate(patterns, 1):
        hits = find(args.repo, pattern)
        found |= bool(hits)
        # The term itself is never printed, so the check's output is safe to share.
        print(f"term {n}: {'FOUND in ' + str(len(hits)) + ' place(s)' if hits else 'not found'}")
        for hit in hits:
            print(f"  {hit}")
    print("FAIL: identifying terms found." if found else f"OK: {len(patterns)} term(s), none found.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
