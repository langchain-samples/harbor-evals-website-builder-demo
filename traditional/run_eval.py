"""The traditional evaluation: a dataset of briefs, scored by code and a judge.

This is the eval most teams already have. Inputs go in, the agent runs, and
evaluators grade what came out — a filesystem of HTML and CSS, read as text.

The evaluators are deliberately split:

  * `no_structural_errors` and `brief_coverage` are **code**. They are cheap,
    deterministic, and they cover more than people expect.
  * `design_quality` and `follows_house_rules` are an **LLM judge**, asked
    only about the things code cannot judge.

Not one of them opens a browser. That is the whole point, and briefs 1 and 2
are where it shows: a static site's form is always beautifully marked up and
never actually submits anywhere.

    python traditional/run_eval.py --offline        # code evaluators only, no model
    python traditional/run_eval.py --dataset-only   # create/sync the dataset, no run
    python traditional/run_eval.py --run            # the real thing
    python traditional/run_eval.py --run --limit 2  # just the two form briefs
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
# agent.py and sitecheck.py live in deep-agent/ so Harbor can stage that
# directory alone.
AGENT_DIR = PROJECT / "deep-agent"
sys.path.insert(0, str(AGENT_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT / ".env")

from sitecheck import check_site  # noqa: E402

SCAFFOLD = PROJECT / "scaffold"
SEEDS = Path(__file__).resolve().parent / "seeds"

DATASET_NAME = os.environ.get("DEMO_DATASET", "site-builder-briefs")
DEFAULT_MODEL = os.environ.get("DEMO_MODEL", "anthropic:claude-sonnet-4-6")
JUDGE_MODEL = os.environ.get("DEMO_JUDGE_MODEL", "anthropic:claude-sonnet-4-6")


# --------------------------------------------------------------------------
# The dataset. Order matters: the two form briefs come first because they
# carry the demo's transition — they pass every check below and the form does
# nothing when you click it.
# --------------------------------------------------------------------------
BRIEFS: list[dict] = [
    {
        "name": "halden-cycles-booking-form",
        "brief": (
            "A landing page for Halden Cycles, a bike repair shop in "
            "Minneapolis. List the services with prices, and add a booking "
            "form so people can request a repair slot."
        ),
        "must_include": ["halden", "minneapolis", "$"],
        "must_have": {"form_with_labels": 3, "prices": 3},
        "note": "The form is marked up correctly and submits nowhere.",
    },
    {
        "name": "tidewater-swim-signup",
        "brief": (
            "A landing page for Tidewater Swim School in Norfolk. Show class "
            "times for three age groups, and add a signup form for a trial "
            "lesson."
        ),
        "must_include": ["tidewater", "norfolk"],
        "must_have": {"form_with_labels": 3, "times": 3},
        "note": "Same form gap, plus a time table that is the 375px beat.",
    },
    {
        "name": "rye-and-co-bakery",
        "brief": (
            "A landing page for Rye & Co, a sourdough bakery in Portland. "
            "Include opening hours and a price list for the loaves."
        ),
        "must_include": ["rye & co", "portland", "$"],
        "must_have": {"times": 1, "prices": 3},
        "note": "Baseline with no form — the traditional eval genuinely covers this.",
    },
    {
        "name": "mira-okonkwo-portfolio",
        "brief": (
            "A one-page portfolio for Mira Okonkwo, a freelance illustrator. "
            "Dark and typographic, no photographs. Include a client list."
        ),
        "must_include": ["mira", "okonkwo"],
        "must_have": {"no_images": True},
        "note": "Pure taste. The judge is the right instrument here, not a verifier.",
    },
    {
        "name": "hero-darker-follow-up",
        "brief": "Make the hero darker. Leave the rest of the page alone.",
        "seed": "built-bakery",
        "must_include": ["rye & co", "portland"],
        "must_have": {
            "token_changed": "--hero-bg",
            "preserve": [
                "Bread baked on time, not on shortcuts",
                "48-hour cold ferment",
                "1418 Alberta Street",
            ],
        },
        "note": "Multi-turn. A one-shot dataset can barely express this at all.",
    },
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
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


def visible_text(html: str) -> str:
    parser = _Strip()
    parser.feed(html)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


# Sites land under runs/<timestamp>/<brief>/ rather than a random mkdtemp
# name, so that after an experiment you can actually open the page that was
# scored. On macOS mkdtemp lands in $TMPDIR, which is both unguessable and
# periodically swept.
RUNS = PROJECT / "runs"
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")


def label_for(brief: str) -> str:
    """The brief's name from BRIEFS, or a slug of its opening words."""
    for entry in BRIEFS:
        if entry["brief"] == brief:
            return entry["name"]
    words = re.findall(r"[a-z0-9]+", brief.lower())[:6]
    return "-".join(words) or "unnamed"


def stage(seed: str | None = None, label: str | None = None) -> Path:
    """A fresh site directory: the scaffold, or a pre-built site to edit."""
    if label:
        dest = RUNS / RUN_ID / label
        # A repeated brief (repetitions, reruns) gets its own directory.
        suffix = 2
        while dest.exists():
            dest = RUNS / RUN_ID / f"{label}-{suffix}"
            suffix += 1
        dest.mkdir(parents=True)
    else:
        dest = Path(tempfile.mkdtemp(prefix="eval-site-"))

    source = (SEEDS / seed) if seed else SCAFFOLD
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, dest / path.name)
    return dest


def read_site(site_dir: str | Path) -> dict[str, str]:
    site = Path(site_dir)
    return {
        p.relative_to(site).as_posix(): p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(site.rglob("*"))
        if p.is_file() and p.suffix in {".html", ".css"}
    }


# --------------------------------------------------------------------------
# Code evaluators
# --------------------------------------------------------------------------
def _no_site(outputs: dict) -> str:
    error = (outputs or {}).get("error")
    return f"the agent run failed: {error}" if error else "the agent run produced no site"


def _site_of(outputs: dict) -> str | None:
    """The site this run produced, or None when the run itself failed.

    A target that raises leaves empty outputs. Without this guard every
    evaluator then dies on a KeyError and buries the actual error under four
    unrelated tracebacks.
    """
    return (outputs or {}).get("site_dir")


def no_structural_errors(outputs: dict, **_) -> dict:
    """Doctype, lang, title, viewport, one h1, alt text, links that resolve."""
    site = _site_of(outputs)
    if not site:
        return {"key": "no_structural_errors", "score": 0.0, "comment": _no_site(outputs)}
    report = check_site(site)
    errors = report["errors"]
    return {
        "key": "no_structural_errors",
        "score": 1.0 if not errors else 0.0,
        "comment": "clean" if not errors else f"{len(errors)}: " + "; ".join(errors[:3]),
    }


def _structural_checks(requirement: dict, files: dict[str, str]) -> list[tuple[str, bool]]:
    html = "\n".join(v for k, v in files.items() if k.endswith(".html"))
    css = "\n".join(v for k, v in files.items() if k.endswith(".css"))
    text = visible_text(html)
    results: list[tuple[str, bool]] = []

    for name, want in requirement.items():
        if name == "form_with_labels":
            form = re.search(r"<form\b.*?</form>", html, re.S | re.I)
            labels = len(re.findall(r"<label\b[^>]*\bfor\s*=", form.group(0), re.I)) if form else 0
            results.append((f"form with {want}+ labelled fields", bool(form) and labels >= want))
        elif name == "prices":
            results.append((f"{want}+ prices", len(re.findall(r"\$\s?[\d,]+", text)) >= want))
        elif name == "times":
            found = len(re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", text, re.I))
            results.append((f"{want}+ times", found >= want))
        elif name == "no_images":
            results.append(("no <img> elements", not re.search(r"<img\b", html, re.I)))
        elif name == "token_changed":
            # The seed defines the token as var(--wash); a real restyle replaces it.
            match = re.search(rf"{re.escape(want)}\s*:\s*([^;]+);", css)
            value = (match.group(1).strip() if match else "")
            results.append((f"{want} changed from the seed", bool(value) and "var(--wash)" not in value))
        elif name == "preserve":
            missing = [p for p in want if p not in text]
            results.append((f"original copy preserved ({len(want)} phrases)", not missing))

    return results


def brief_coverage(outputs: dict, reference_outputs: dict, **_) -> dict:
    """Did the page contain what the brief actually asked for?"""
    site = _site_of(outputs)
    if not site:
        return {"key": "brief_coverage", "score": 0.0, "comment": _no_site(outputs)}
    files = read_site(site)
    text = visible_text("\n".join(v for k, v in files.items() if k.endswith(".html"))).lower()

    checks = [(f"mentions {t!r}", t.lower() in text) for t in reference_outputs.get("must_include", [])]
    checks += _structural_checks(reference_outputs.get("must_have", {}) or {}, files)

    passed = sum(1 for _, ok in checks if ok)
    failed = [name for name, ok in checks if not ok]
    return {
        "key": "brief_coverage",
        "score": passed / len(checks) if checks else 1.0,
        "comment": f"{passed}/{len(checks)}" + (f" — missing: {', '.join(failed)}" if failed else ""),
    }


def tool_calls(outputs: dict, **_) -> dict:
    """Recorded so effort is visible at all. A judge never sees this."""
    return {"key": "tool_calls", "score": float(outputs.get("tool_calls", 0))}


# --------------------------------------------------------------------------
# LLM judges
# --------------------------------------------------------------------------
JUDGE_SYSTEM = """\
You are a senior frontend engineer reviewing a small static site before it
ships. You are strict: good-looking markup that does not do the job scores
badly, and you would rather block a change than wave through something you
cannot confirm.

Score 0.0 to 1.0 and explain concretely, citing specific elements or
declarations rather than generalities. If something looks risky but you cannot
confirm it from what you were given, say so in `unverifiable` and do not let
an unconfirmed suspicion drive the score.
"""

DESIGN_RUBRIC = """\
Judge the *design and craft* of this page only. Is the visual hierarchy clear?
Is the copy real, specific and worth reading, or filler? Does the structure
suit the brief? Would you be happy to show this to the client?

Do not grade the brief's checklist — that is measured separately.
"""

RULES_RUBRIC = """\
Judge whether the page follows the house rules below. Quote the rule and the
markup when you find a violation.

HOUSE RULES:
{rules}
"""

JUDGE_TEMPLATE = """\
The brief was:

    {brief}

Here are the files that were produced:

{files}

Review it.
"""

_SCHEMA = {
    "title": "Review",
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
        "unverifiable": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "reasoning"],
}


def _judge(rubric: str, inputs: dict, outputs: dict, key: str) -> dict:
    from langchain.chat_models import init_chat_model

    site = _site_of(outputs)
    if not site:
        # Do not spend a judge call on a run that produced nothing.
        return {"key": key, "score": 0.0, "comment": _no_site(outputs)}

    files = read_site(site)
    rendered = "\n\n".join(f"--- {name} ---\n{body}" for name, body in files.items())
    llm = init_chat_model(JUDGE_MODEL, temperature=0).with_structured_output(_SCHEMA)
    verdict = llm.invoke([
        {"role": "system", "content": JUDGE_SYSTEM + "\n\n" + rubric},
        {"role": "user", "content": JUDGE_TEMPLATE.format(
            brief=inputs["brief"], files=rendered[:120_000],
        )},
    ])
    comment = verdict.get("reasoning", "")
    if verdict.get("unverifiable"):
        comment += "\n\nCould not verify: " + "; ".join(verdict["unverifiable"])
    return {"key": key, "score": verdict.get("score", 0.0), "comment": comment}


def design_quality(inputs: dict, outputs: dict, **_) -> dict:
    return _judge(DESIGN_RUBRIC, inputs, outputs, "design_quality")


def follows_house_rules(inputs: dict, outputs: dict, **_) -> dict:
    rules = (AGENT_DIR / "AGENTS.md").read_text(encoding="utf-8")
    return _judge(RULES_RUBRIC.format(rules=rules), inputs, outputs, "follows_house_rules")


# --------------------------------------------------------------------------
# Target
# --------------------------------------------------------------------------
def build_target(model: str):
    """The thing under evaluation: the same agent the chat UI runs."""
    from agent import build_graph

    def target(inputs: dict) -> dict:
        site = stage(inputs.get("seed"), label=label_for(inputs["brief"]))
        graph = build_graph(site_dir=site, model=model)

        # A raised exception here leaves LangSmith with empty outputs, which
        # then breaks every evaluator on a missing key and hides the real
        # cause. Catch it, keep the site dir, and put the error where both the
        # terminal and the experiment can show it.
        try:
            result = graph.invoke(
                {"messages": [{"role": "user", "content": inputs["brief"]}]},
                {"recursion_limit": 100},
            )
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            print(f"\n  !! agent run failed on {inputs['brief'][:48]!r}\n     {detail}\n", flush=True)
            return {
                "message": "",
                "site_dir": str(site),
                "files": sorted(read_site(site)),
                "tool_calls": 0,
                "error": detail,
            }

        calls, message = 0, ""
        for msg in result.get("messages", []):
            calls += len(getattr(msg, "tool_calls", None) or [])
        for msg in reversed(result.get("messages", [])):
            if getattr(msg, "type", "") == "ai":
                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    content = "".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                if content and content.strip():
                    message = content
                    break

        return {
            "message": message,
            "site_dir": str(site),
            "files": sorted(read_site(site)),
            "tool_calls": calls,
        }

    return target


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------
def sync_dataset() -> str:
    from langsmith import Client

    client = Client()
    if not client.has_dataset(dataset_name=DATASET_NAME):
        client.create_dataset(
            dataset_name=DATASET_NAME,
            description=(
                "Briefs for the site-builder deep agent. Reference data is "
                "deterministic coverage, not a golden page — there is no one "
                "correct landing page."
            ),
        )
        print(f"created dataset {DATASET_NAME!r}")

    existing = {e.metadata.get("name") for e in client.list_examples(dataset_name=DATASET_NAME) if e.metadata}
    new = [
        {
            "inputs": {k: v for k, v in ((("brief", b["brief"]),) + ((("seed", b["seed"]),) if b.get("seed") else ()))},
            "outputs": {"must_include": b["must_include"], "must_have": b.get("must_have", {})},
            "metadata": {"name": b["name"], "note": b["note"]},
        }
        for b in BRIEFS if b["name"] not in existing
    ]
    if new:
        client.create_examples(dataset_name=DATASET_NAME, examples=new)
        print(f"added {len(new)} example(s)")
    else:
        print(f"dataset {DATASET_NAME!r} already has all {len(BRIEFS)} briefs")
    return DATASET_NAME


def offline() -> int:
    """Exercise the code evaluators without calling a model.

    Runs them against the seed site, which is what a *correct* answer to the
    follow-up brief starts from — so `token_changed` is expected to fail here.
    """
    print("Code evaluators against the built-bakery seed (no model calls):\n")
    site = stage("built-bakery")
    outputs = {"site_dir": str(site), "tool_calls": 0}
    brief = next(b for b in BRIEFS if b["name"] == "hero-darker-follow-up")
    reference = {"must_include": brief["must_include"], "must_have": brief["must_have"]}

    for evaluator in (no_structural_errors, brief_coverage, tool_calls):
        result = evaluator(outputs=outputs, reference_outputs=reference, inputs={"brief": brief["brief"]})
        print(f"  {result['key']:<24} {result['score']:>6.2f}   {result.get('comment', '')[:80]}")

    print("\n`token_changed` failing is correct — the seed is the *unedited* page.")
    print("A run that darkens the hero flips it to 1.00.\n")
    shutil.rmtree(site, ignore_errors=True)
    return 0


def run(model: str, limit: int | None, judges: bool) -> int:
    from langsmith import Client

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("No model credentials in the environment. Try --offline.")
        return 2

    sync_dataset()
    evaluators = [no_structural_errors, brief_coverage, tool_calls]
    if judges:
        evaluators += [design_quality, follows_house_rules]

    client = Client()
    results = client.evaluate(
        build_target(model),
        data=list(client.list_examples(dataset_name=DATASET_NAME))[:limit] if limit else DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix="traditional-judge",
        metadata={"model": model, "judge": JUDGE_MODEL if judges else None},
        max_concurrency=2,
    )
    print(f"\nexperiment: {getattr(results, 'experiment_name', '(see LangSmith)')}")
    print("Open Datasets & Experiments in LangSmith to compare runs.")

    run_dir = RUNS / RUN_ID
    if run_dir.is_dir():
        print(f"\nThe pages that were scored:\n")
        for site in sorted(run_dir.iterdir()):
            if site.is_dir():
                print(f"  open {site.relative_to(PROJECT)}/index.html")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--offline", action="store_true", help="code evaluators only, no model")
    group.add_argument("--dataset-only", action="store_true", help="create/sync the dataset and exit")
    group.add_argument("--run", action="store_true", help="run the agent and score it")
    parser.add_argument("--limit", type=int, default=None, help="first N briefs only")
    parser.add_argument("--no-judges", action="store_true", help="skip the LLM judges")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--list", action="store_true", help="print the briefs and exit")
    args = parser.parse_args()

    if args.list or not (args.offline or args.dataset_only or args.run):
        for i, b in enumerate(BRIEFS, 1):
            seed = f"  [seeded from {b['seed']}]" if b.get("seed") else ""
            print(f"\n{i}. {b['name']}{seed}\n   {b['brief']}")
            print(f"   text:      {', '.join(b['must_include'])}")
            if b.get("must_have"):
                print(f"   structure: {b['must_have']}")
            print(f"   why:       {b['note']}")
        print()
        return 0

    if args.offline:
        return offline()
    if args.dataset_only:
        sync_dataset()
        return 0
    return run(args.model, args.limit, judges=not args.no_judges)


if __name__ == "__main__":
    sys.exit(main())
