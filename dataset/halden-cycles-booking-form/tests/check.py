"""Verifier for halden-cycles-booking-form.

Two layers, deliberately separated:

  * `functional.py` — shared, generic, derived from the artifact. Holds the
    page to the promises its own markup makes. Knows nothing about Halden.
  * this file — the thin part. Did the page contain what *this* brief asked
    for. Roughly five lines per task.

`reward` is conjunctive across both. A flawlessly working page that ignored
the brief is not a pass, and neither is a page that says all the right things
and does nothing.
"""

from __future__ import annotations

import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, "/tests" if Path("/tests").is_dir() else str(Path(__file__).parent))

from functional import METRICS, Result, run  # noqa: E402

SITE = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SITE_DIR", "/app/site"))
REWARD_DIR = Path(os.environ.get("REWARD_DIR", "/logs/verifier"))

# --- the only task-specific part -----------------------------------------
MUST_MENTION = ["halden", "minneapolis"]
MIN_PRICES = 3
MIN_LABELLED_FIELDS = 3

ALL = [*METRICS, "brief_coverage"]


class _Strip(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def coverage(result: Result) -> None:
    html = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in SITE.rglob("*.html"))
    parser = _Strip()
    parser.feed(html)
    text = parser.text()

    problems = []
    for term in MUST_MENTION:
        if term not in text.lower():
            problems.append(f"never mentions {term!r}")

    form = re.search(r"<form\b.*?</form>", html, re.S | re.I)
    if not form:
        problems.append("no <form>")
    else:
        labels = len(re.findall(r"<label\b[^>]*\bfor\s*=", form.group(0), re.I))
        if labels < MIN_LABELLED_FIELDS:
            problems.append(f"{labels} labelled fields, wanted {MIN_LABELLED_FIELDS}")

    prices = len(re.findall(r"\$\s?[\d,]+", text))
    if prices < MIN_PRICES:
        problems.append(f"{prices} prices, wanted {MIN_PRICES}")

    result.record("brief_coverage", not problems, "; ".join(problems[:2]))


def main() -> int:
    result = Result()

    if not SITE.is_dir() or not (SITE / "index.html").is_file():
        for name in ALL:
            result.record(name, False, f"no index.html in {SITE}")
    else:
        coverage(result)
        run(SITE, result)

    for name in ALL:
        result.scores.setdefault(name, 0.0)
    reward = 1.0 if all(result.scores[n] == 1.0 for n in ALL) else 0.0
    metrics = {"reward": reward, **{n: result.scores[n] for n in ALL}}

    print("\n" + "=" * 70)
    print(f"{'check':<20} {'score':>6}   note")
    print("-" * 70)
    for name in ALL:
        print(f"{name:<20} {result.scores[name]:>6.1f}   {result.notes.get(name, '')[:40]}")
    print("-" * 70)
    print(f"{'REWARD':<20} {reward:>6.1f}")
    failed = [n for n in ALL if result.scores[n] != 1.0]
    if failed:
        print(f"\nfailing: {', '.join(failed)}")
    print("=" * 70, flush=True)

    payload = json.dumps(metrics, indent=2)
    try:
        REWARD_DIR.mkdir(parents=True, exist_ok=True)
        (REWARD_DIR / "reward.json").write_text(payload)
        (REWARD_DIR / "notes.json").write_text(json.dumps(result.notes, indent=2))
    except OSError as exc:
        print(f"(not writing {REWARD_DIR}/reward.json: {exc})")
        print(payload)
    return 0 if reward == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
