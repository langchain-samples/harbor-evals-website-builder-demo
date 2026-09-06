# Site Builder — one agent, two evals

A barebones Lovable: type *"a landing page for my bike shop"* and watch a
deep agent build it file by file in a live preview. Then grade **that same
agent** two ways — an LLM judge reading the output, and a containerized
verifier that serves the site and drives a real browser.

They agree on everything they can both see. They disagree about one thing,
and it is the thing that matters.

> **If you'd have to click the button to know whether it worked, grading the
> output can't get you there.**

---

## The punchline

Same agent, same brief, same run — scored twice:

|                                | traditional eval | Harbor eval |
| ------------------------------ | ---------------- | ----------- |
| is the markup sound            | **1.00**         | **1.00**    |
| did it cover the brief         | **1.00**         | **1.00**    |
| design quality (LLM judge)     | judge            | *n/a*       |
| does it work on a phone        | *no such check*  | **1.00**    |
| any runtime errors             | *no such check*  | **1.00**    |
| **does the form submit**       | ***no such check*** | **0.00** |
|                                |                  | **reward 0.00** |

The agent writes this, every single time:

```html
<form action="#" method="post" novalidate>
  <label for="email">Email address</label>
  <input type="email" id="email" name="email" autocomplete="email" required>
```

Labels tied to inputs, `type=email`, `required`, autocomplete hints. Nobody
blocks that in review. There is also zero JavaScript on the page, so
`required` does nothing, `novalidate` cancels what is left, and the POST goes
nowhere. Click Submit on a static site and you get:

```
Error code: 501
Message: Unsupported method ('POST').
```

Harbor is not saying the page is bad. It is saying the page is good **and the
form does not work.** That distinction is the whole demo.

---

## How it works

One graph. The only thing that changes between the product and the eval is
which directory it builds into.

```
                        deep-agent/agent.py
                    one graph: "website_builder"
                                 │
            ┌────────────────────┴────────────────────┐
            │                                         │
  ┌─────────▼──────────┐                  ┌───────────▼───────────┐
  │  server.py         │                  │  harbor run           │
  │  chat + live       │                  │  one sandbox per trial│
  │  preview (SSE)     │                  │                       │
  │  → workspaces/<id> │                  │  → /app/site          │
  └────────────────────┘                  └───────────┬───────────┘
                                                      │ tests/test.sh
                                              serve over HTTP,
                                              drive Chromium
                                                      ▼
                                          /logs/verifier/reward.json
                                                      │
                                            LangSmith experiment
```

No test double, no re-implementation. `deep-agent/agent.py` is imported by the
chat UI *and* by the traditional eval, and staged into every Harbor trial
container by `--ak project_path=./deep-agent`.

**The agent itself** is [deepagents](https://github.com/langchain-ai/deepagents):
a planner (`write_todos`), a filesystem backend, two subagents
(`page-builder`, `site-reviewer`), and one custom tool — `check_site`, a
structural linter it calls on itself before claiming it is done.

---

## Setup

```bash
uv sync
uv run playwright install chromium
cp .env.example .env        # then add LANGSMITH_API_KEY
```

Or just `make setup`.

Model credentials come from the ambient environment (`ANTHROPIC_API_KEY`, plus
`ANTHROPIC_BASE_URL` if you route through a gateway). **Keep them out of
`.env`** — plain `load_dotenv()` never overrides an already-set variable,
which is what lets the ambient value win.

Two free, no-model sanity checks before you present anything:

```bash
make verify      # the verifier is sound — bad page fails, solution scores 1.0
make snapshot    # the LangSmith sandbox snapshot exists and is ready
```

---

## The demo, end to end

Five acts, ~15 minutes. The speakable script — including the staging, the
pauses, and five rehearsed objections — is in **[DEMO.md](DEMO.md)**.

### 1. The product · `make ui`

http://localhost:8000. Type *"A landing page for Rye & Co, a sourdough bakery
in Portland."*

Watch the **order** in the left pane, because that is the deep-agent story: it
writes a plan, reads `styles.css` before writing anything (composing from
existing design tokens rather than inventing a palette), writes the page, then
calls `check_site` to grade its own work. ~65s, 5 tool calls.

Then *"make the hero darker"* — 20s, one `edit_file`. The site is on disk and
the thread is checkpointed, so a follow-up is an edit, not a rebuild.

Open [`deep-agent/AGENTS.md`](deep-agent/AGENTS.md) — the house rules the agent
reads on every run. Someone who doesn't write code changes what this ships by
editing markdown.

### 2. The eval most teams already have · `make judge`

Five briefs, five evaluators, results in LangSmith as `site-builder-briefs`.
Open the judge's reasoning and read it out loud — it cites `aria-describedby`
and checks that labels are associated with the right inputs. **The point of
this act is to make the judge credible.** Don't rush it.

### 3. The transition · `make page`

Serves the exact page the traditional eval scored 1.00/1.00
(`demo-pages/halden-cycles-scored/`). Scroll it. Put the form's source on
screen. Ask whether anyone would block it in review.

Then: *"Let's just look at the thing."* Click Submit with every field empty.

**Never announce the break.** The moment you say "watch, it's broken," you've
lost it.

### 4. Harbor · `make harbor` (or `make results` for the last run)

```
renders             1.0
brief_coverage      1.0
controls_work       0.0   nothing happened on submit — no request,
validation_works    1.0      no confirmation (6 fields filled)
responsive          1.0
no_errors           1.0
REWARD              0.0
```

`brief_coverage` is *literally the same function* on both sides. The two evals
agree on everything they can both see.

### 5. Close

The obvious objection is "just read the trace." The trace shows `write_file`
succeeded — accurate, and useless here. One failure is **an event that didn't
happen**; the other is **a change in whether something still works**. Neither
is in a transcript of what the agent did.

---

## The two evals

### Traditional — `traditional/run_eval.py`

A LangSmith dataset of five briefs, graded by four evaluators plus one
recorded metric:

| evaluator | kind | asks |
| --- | --- | --- |
| `no_structural_errors` | code | doctype, `lang`, title, viewport, one `h1`, alt text, links and stylesheets that resolve |
| `brief_coverage` | code | did the page contain what the brief asked for |
| `design_quality` | LLM judge | is this a good-looking, well-composed page |
| `follows_house_rules` | LLM judge | does it comply with `AGENTS.md` |
| `tool_calls` | recorded | how much work did it actually do |

**Make the judge genuinely strong.** It is not weakened to manufacture the
result — it is asked only about things code cannot judge, and it is right
about them. Not one evaluator opens a browser. That is the whole point.

```bash
uv run python traditional/run_eval.py --offline        # code evaluators, no model
uv run python traditional/run_eval.py --dataset-only   # sync the dataset only
uv run python traditional/run_eval.py --run            # the real thing
uv run python traditional/run_eval.py --run --limit 1 --no-judges
```

### Harbor — `dataset/`

A standard Harbor task directory:

```
dataset/halden-cycles-booking-form/
├── task.toml            # timeouts, resources, SITE_DIR
├── instruction.md       # the brief handed to the agent
├── environment/
│   ├── Dockerfile       # python:3.12-slim-bookworm + chromium
│   └── site/            # the scaffold the agent starts from
├── tests/
│   ├── test.sh          # Harbor runs this; writes reward.json
│   ├── check.py         # thin — this brief's coverage, ~5 lines
│   └── functional.py    # generated copy of dataset/_shared/functional.py
└── solution/solve.sh    # oracle reference — scores 1.0
```

Harbor's contract is small: **write a number to
`/logs/verifier/reward.json`.** Everything else is your choice. Ours runs a
browser because the artifact is a website; Harbor's own examples use pytest.
Playwright is not part of Harbor and is not its recommended default.

### The generic half — `dataset/_shared/functional.py`

This is the file to open when someone accuses you of writing a check to catch
a bug you already found. There is **no business name and no brief in it.** The
organising idea:

> **Hold the page to the promises its own markup makes.**

```
<a href="x">           I lead somewhere
<img src="x">          I will show you something
<link rel=stylesheet>  I change how this looks
<form>                 I accept input
required               I will refuse to submit empty
type="email"           I will refuse a non-address
meta viewport          I work on a phone
```

Every check asserts one of those, giving five reusable metrics — `renders`,
`controls_work`, `validation_works`, `responsive`, `no_errors` — that any
web-authoring task can inherit. Each task adds its own thin coverage check on
top; `reward` is conjunctive across both, so a flawless page that ignored the
brief is not a pass, and neither is a page that says all the right things and
does nothing.

Two fairness rules, because an unsatisfiable check is a broken eval:

- only assert against declarations that are **actually present** (no `<form>`
  → `controls_work` is skipped, not failed)
- honour anything the markup declares inert (`disabled`, `aria-disabled`) and
  skip anything off-origin, which an offline verifier cannot resolve

The site is served over HTTP from a **subpath** (`/preview/`), never from the
server root and never over `file://`. At the root, `href="/styles.css"`
resolves and an absolute-path bug hides; from a subpath it 404s, exactly as it
does in the real preview.

```bash
make sync    # vendor _shared/functional.py into each task (Harbor uploads
             # tests/ on its own; a verifier can only import what sits beside it)
```

---

## Running on LangSmith sandboxes

Each trial gets its own container, torn down after. That is not decoration:
this eval runs a browser **and** hands an agent shell access, per trial, in
parallel.

Build the snapshot once (a server-side image build — minutes, not seconds):

```bash
make snapshot        # prints status: ready
```

Then run trials against it. `dataset/harbor-job.json` pins the snapshot, so
runs skip the build:

```bash
make harbor                    # one trial
make attempts ATTEMPTS=5       # five — one run is not an estimate
make haiku                     # same task, cheaper model tier
make oracle                    # the reference solution — proves 1.0 is reachable
```

Roughly **$0.20 and 90 seconds per trial.** Results land as a LangSmith
experiment with `reward` and every sub-metric as feedback keys, the agent's own
trace attached, plus tokens and cost.

Three flags are load-bearing and cannot live in the JSON config — see the
`HARBOR_ARGS` block in the [Makefile](Makefile):

- `--env-file .env` — the Harbor CLI does not read `.env` itself, and the
  LangSmith plugin hard-fails without `LANGSMITH_API_KEY`
- `--ae ANTHROPIC_BASE_URL=...` — Harbor forwards `ANTHROPIC_API_KEY` but
  **not** the base URL, so a gateway-scoped key 401s against `api.anthropic.com`
- `--plugin langsmith --pk dataset_name=...` — plugins are not part of
  `JobConfig`

---

## Repo map

| path | what it is |
| --- | --- |
| `deep-agent/agent.py` | the agent — subagents, `check_site`, `make_graph` for Harbor |
| `deep-agent/AGENTS.md` | house rules, read every run, editable without touching code |
| `deep-agent/sitecheck.py` | structural checks — the agent's linter *and* a grading rubric |
| `deep-agent/langgraph.json` | graph + container dependency pins |
| `server.py` · `static/index.html` | FastAPI chat UI: SSE stream, live preview, file tree |
| `scaffold/` | `styles.css` design tokens + placeholder page, seeded per session |
| `traditional/run_eval.py` | the LLM-judge eval: 5 briefs, 5 evaluators |
| `dataset/_shared/functional.py` | the generic browser suite — 5 reusable metrics |
| `dataset/halden-cycles-booking-form/` | the Harbor task |
| `dataset/harbor-job.json` | Harbor job config (snapshot pin, agent kwargs, artifacts) |
| `demo-pages/halden-cycles-scored/` | the recorded artifact the traditional eval scored 1.00 |
| `build_snapshot.py` | builds/inspects the LangSmith sandbox snapshot |
| `scripts/verify.py` | free gate: is the verifier still sound |
| `DEMO.md` | the speakable talk track |

Also runnable in LangGraph Studio, the quickest way to see the subagent calls
as a graph:

```bash
cd deep-agent && uv run langgraph dev
```

---

## What is verified, and what is not

Being straight about this is what makes the demo defensible.

**Verified.**

- The form failure is deterministic — `<form action="#" method="post">` with
  zero `<script>` tags, on **6 of 6 runs across three environments** (local,
  local Docker, LangSmith sandbox). `controls_work` failed every time.
- `brief_coverage` is confirmed at 1.00 on the recorded page by both evals.
- The oracle solution reaches `reward 1.0` locally, so the task is passable.
- `make verify` gates both directions: the bad page fails for the right
  reason, the solution still scores 1.0.

**Not verified — do not promise these.**

- **No live LLM-judge score has been observed.** Run `make judge` once before
  presenting and read the real numbers.
- `make attempts` and `make haiku` have not been run, so you cannot yet say
  "five out of five" or "both model tiers."
- `--agent oracle` has not been run through Harbor end to end.

**Known weaknesses.**

- `controls_work` is reward-hackable: a visible confirmation message with no
  network request passes it.
- `validation_works` is run-dependent — it only fails when the agent adds
  `novalidate`. One sandbox run omitted it and the check correctly passed.
- `responsive` and `validation_works` are not mentioned in `instruction.md`,
  so this task does not meet a strict spec-completeness bar.

---

## Notes from building it

The non-obvious things, so you don't rediscover them:

- **deepagents 0.7.x does not include `TodoListMiddleware` by default.** Add it
  explicitly or there is no `write_todos`.
- **`build_timeout_sec` in `task.toml` is the gate on environment start**
  (default 600s). The LangSmith environment's own
  `--ek startup_timeout_seconds` is a *different, inner* timeout — raising it
  alone does nothing, because the outer one fires first.
- **`python:3.12-slim` now tracks Debian trixie**, where Playwright 1.49.1's
  apt list names packages that no longer exist. Pin `-bookworm`.
- **`--ak project_path=.` with the default `jobs_dir`** makes `copytree`
  recurse into its own output, 64 path segments deep. Hence
  `jobs_dir: /tmp/harbor-jobs` and `project_path: ./deep-agent`.
- **A LangSmith snapshot record can exist with `status: failed`.** Matching on
  name alone reports a usable snapshot that is not one — check status.
- **`fs_capacity_bytes` has a 16 GiB floor** on the Dockerfile path. Not
  tunable.
- **A POST back to the page's own URL is not a submission.** Counting it was a
  false PASS on `controls_work`; the fixture had no `action` while the real
  agent wrote `action="#"`.
- **Serve from a subpath, never the root.** Absolute-path bugs are invisible at
  `/`. This one shipped a page that rendered completely unstyled while the
  structural checker reported no errors — found only by looking at the render.

---

## Links

- [deepagents](https://github.com/langchain-ai/deepagents)
- [LangSmith Harbor integration](https://docs.langchain.com/langsmith/harbor-integrations)
- [LangSmith Sandboxes](https://docs.langchain.com/langsmith/sandboxes)
- [LangGraph](https://github.com/langchain-ai/langgraph)
