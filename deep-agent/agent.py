"""Website builder — a deep agent that ships a small static site.

The demo is a barebones Lovable: you type "a landing page for my bakery" and
watch a site appear. What makes it a *deep* agent rather than one big
completion is the shape of the work:

  * a plan the agent writes down and works through, because "build a
    three-page site" is a handful of tasks with an order to them
  * a filesystem, because the deliverable is several files that reference each
    other, not one blob of text
  * one subagent per page, so the fussy detail of the pricing page never
    crowds out the home page's context — and so pages can be built in parallel
  * a reviewer subagent that reads the finished site cold and reports what is
    wrong, which is a different job from building it and does better in its
    own context
  * `check_site`, a deterministic linter, so "done" is something the agent
    verifies rather than asserts

The same graph runs two ways. Under the chat UI, `configurable.cwd` points at
a per-session workspace. Under a Harbor eval, Harbor stages this project into
a container and passes the trial's working directory as `configurable.cwd`.
Nothing about the agent changes between the product and the grader — that is
the whole point of the demo.
"""

from __future__ import annotations

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain.agents.middleware import TodoListMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

from sitecheck import check_site as run_check

PROJECT_DIR = Path(__file__).parent

# Pick up LANGSMITH_* from .env so tracing works however the agent is started
# — the FastAPI server, a script, `langgraph dev`. Plain load_dotenv() never
# overrides a variable already in the environment, so ambient gateway
# credentials always win over anything in the file. Do not add override=True,
# and keep gateway vars out of .env entirely.
# .env sits at the repo root, one level up from this directory. In a Harbor
# trial only this directory is staged, so there is no .env there at all —
# Harbor forwards ANTHROPIC_API_KEY and the LANGSMITH_* vars as real
# environment variables instead. Both lookups are best-effort.
for _candidate in (PROJECT_DIR / ".env", PROJECT_DIR.parent / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate)
        break

# Relies on ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY already pointing at the
# gateway. Harbor passes its own --model through configurable.model, which
# takes precedence over this.
DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


def _load_policy() -> str:
    """The house rules, inlined into the system prompt.

    AGENTS.md is read at graph-build time rather than through the agent's own
    filesystem tools, because the backend root is the *site* workspace and the
    policy lives with the code. Inlining keeps one copy that travels with the
    project — including into a Harbor container, which stages this directory —
    and it keeps the policy out of the shipped site directory.

    Read at build time, so editing AGENTS.md changes the next build: the
    server builds a graph per session and `langgraph dev` hot-reloads.
    """
    path = PROJECT_DIR / "AGENTS.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


BUILDER_PROMPT = """\
You build small static websites — plain HTML and CSS, no framework, no build \
step — from a short brief in chat.

How to work:

1. `ls` first. A site usually already exists on disk — `index.html` and a \
`styles.css` carrying design tokens and layout classes. When it does, your \
job is to edit those, not to start from nothing.

2. Write a short plan with `write_todos` — two or three items for a single \
page. Skip the plan for a small follow-up edit.

3. If `styles.css` exists, read it once to see the classes and tokens you \
have, and compose the page from them. Do not rewrite it. Restyling is a token \
edit in `:root` — "make the hero darker" is changing `--hero-bg` and \
`--hero-ink`, nothing more. If the site is empty, write a compact \
`styles.css` first, then the page.

4. Write `index.html` in a single `write_file`.

5. Call `check_site` once and fix any errors. Ignore warnings.

On a follow-up turn the site is already built. Change the least you can with \
`edit_file` and leave the rest alone. Do not rebuild the page.

For a genuine multi-page request, delegate each additional page to a \
`page-builder` subagent, in parallel, telling each one its path, its \
sections, and the exact shared `<nav>` markup. One page needs no subagent.

Keep chat to two or three sentences. The user is looking at a live preview, \
so describe what you did, not what the markup says, and never paste HTML into \
the conversation.
"""

PAGE_BUILDER_PROMPT = """\
You write exactly one page of a static site, and nothing else.

You will be told the file path, what the page is for, the sections it owns, \
and the shared `<nav>` markup. Write that one file with `write_file`.

Read `styles.css` before you start and use the custom properties and classes \
it already defines. If the page genuinely needs a new shared style, append to \
`styles.css` — never create a second stylesheet, and never restyle what other \
pages depend on.

Reproduce the shared `<nav>` markup exactly as given, so the navigation is \
identical on every page.

Do not touch any other page. Do not call `check_site` — that is the main \
agent's job. When you are done, report back in two or three lines: the path \
you wrote, the sections you included, and anything you added to the \
stylesheet.
"""

REVIEWER_PROMPT = """\
You review a finished static site against the house rules, and you do not \
fix anything.

Do this in order:

1. Call `check_site` and read every error and warning.
2. `ls` the site, then read each page and the stylesheet.
3. Judge what a linter cannot: is the copy real or is it placeholder mush? \
Does every page's `<nav>` match? Is the heading hierarchy sensible? Would \
this be usable at 375px wide? Does it actually answer the brief you were \
given?

Report a numbered list of concrete problems, worst first. For each one name \
the file, what is wrong, and the specific fix. If the site is genuinely fine, \
say so in one line rather than inventing work.

Never call `write_file`, `edit_file`, or `delete`.
"""


def _resolve_site_dir(config: dict | None) -> Path:
    """Where this run's site lives.

    Harbor passes the trial's working directory as `configurable.cwd`. The
    chat server passes a per-session workspace the same way. `SITE_DIR` is the
    escape hatch for running the graph by hand.
    """
    configurable = ((config or {}).get("configurable") or {})
    candidate = configurable.get("cwd") or os.environ.get("SITE_DIR")
    if candidate:
        return Path(candidate).expanduser()

    # No caller told us where to build: keep it out of the source tree, and
    # keep separate threads from overwriting each other's sites.
    thread = configurable.get("thread_id") or "scratch"
    return PROJECT_DIR / "workspaces" / str(thread)


def _make_check_tool(site_dir: Path):
    """`check_site`, bound to this run's site root.

    Bound rather than taking a path argument, so the model cannot point the
    linter at the wrong directory and conclude the site is clean.
    """

    @tool
    def check_site() -> str:
        """Check the site for broken markup, broken links, and missing accessibility basics.

        Checks doctype, lang, title, viewport, one h1, alt text on images,
        internal links and stylesheet references that actually resolve, no
        external CDN references, and balanced CSS braces.

        Returns the errors that must be fixed. Call this once, when you think
        the site is finished.
        """
        report = run_check(site_dir)
        lines = [f"Pages: {', '.join(report['pages']) or 'none'}"]
        if report["errors"]:
            lines.append(f"\n{len(report['errors'])} ERROR(S) — fix these:")
            lines += [f"  - {e}" for e in report["errors"]]
        else:
            lines.append("\nNo errors. The site is good to ship.")
        # Warnings are counted, not listed. Listing them turns a finished page
        # into a long read-edit-read tail that does not improve it.
        if report["warnings"]:
            lines.append(
                f"\n({len(report['warnings'])} style warning(s) not shown — "
                "ignore unless the user asks.)"
            )
        return "\n".join(lines)

    return check_site


def build_graph(
    site_dir: Path | str | None = None,
    model: str | None = None,
    checkpointer=None,
):
    """Compile the agent for one site directory.

    site_dir is created if it does not exist — the agent's first `write_file`
    should not fail because nobody made the folder.
    """
    root = Path(site_dir) if site_dir else _resolve_site_dir(None)
    root.mkdir(parents=True, exist_ok=True)

    policy = _load_policy()
    system_prompt = f"{BUILDER_PROMPT}\n\n---\n\n{policy}" if policy else BUILDER_PROMPT
    subagent_policy = f"\n\n---\n\n{policy}" if policy else ""

    # virtual_mode=True confines the agent to this directory: `..`, `~`, and
    # absolute paths outside root are rejected. Without it, a site-building
    # agent with write access is pointed at the whole disk.
    backend = FilesystemBackend(root_dir=root, virtual_mode=True)
    check_tool = _make_check_tool(root)

    return create_deep_agent(
        model=init_chat_model(model or DEFAULT_MODEL),
        tools=[check_tool],
        system_prompt=system_prompt,
        # `write_todos` is not in deepagents' default stack as of 0.7.x, and
        # the plan is half the point here: a multi-page build is a handful of
        # ordered tasks, and the UI renders the todo list as it changes.
        middleware=[TodoListMiddleware()],
        subagents=[
            {
                "name": "page-builder",
                "description": (
                    "Writes one page of the site. Give it the file path, the "
                    "page's purpose, the sections it owns, and the shared nav "
                    "markup. Invoke one per page, in parallel, for a "
                    "multi-page site."
                ),
                "system_prompt": PAGE_BUILDER_PROMPT + subagent_policy,
            },
            {
                "name": "site-reviewer",
                "description": (
                    "Reviews a finished site against the house rules and "
                    "reports what is wrong, worst first. Read-only — it never "
                    "edits. Use it when the user asks for a review, or for a "
                    "multi-page site where the nav has to match across pages. "
                    "A single page does not need it."
                ),
                "system_prompt": REVIEWER_PROMPT + subagent_policy,
                "tools": [check_tool],
            },
        ],
        backend=backend,
        checkpointer=checkpointer,
    )


def make_graph(config: dict | None = None):
    """Graph factory for `langgraph.json`.

    Harbor calls this per trial with `configurable.cwd` set to the trial's
    working directory and `configurable.model` set from `--model`, which is
    why the model is read from config rather than hardcoded.
    """
    configurable = ((config or {}).get("configurable") or {})
    return build_graph(
        site_dir=_resolve_site_dir(config),
        model=configurable.get("model") or os.environ.get("HARBOR_MODEL"),
    )
