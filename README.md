# Site Builder: evaluating a deep agent with Harbor

A minimal website builder driven by a LangChain deep agent, scored two ways:
once by a traditional LangSmith evaluation that reads the agent's output, and
once by a Harbor evaluation that runs the site in a container and drives a real
browser against it.

The two evaluations agree on every check they can both perform. They disagree
on exactly one, and that disagreement is the point of this repository.

---

## Purpose and background

**Traditional evaluations read what the agent produced.** You assemble a
dataset of inputs, run the agent across them, and score the outputs with code
assertions, string matching, or an LLM judge. This works well when the output
*is* the answer: a summary, a classification, a SQL query, a drafted reply.
The artifact under test and the thing being graded are the same object, so
reading one tells you about the other.

**Deep agents break that equivalence.** A deep agent plans, delegates to
subagents, and writes to a filesystem across many turns. What it returns is not
an answer but a change to a world: files on disk, a migrated schema, a
restructured repository, a website that now exists. The final message is a
*report about* that world rather than the world itself. Grade the report, or
the transcript, and you learn what the agent believed it accomplished. That
belief can be entirely accurate while the artifact it describes is broken,
because "I wrote the file" and "the file does its job" are different claims and
only the first one appears in a trace.

**Harbor closes that gap.** Harbor is an evaluation harness that provisions an
isolated environment per trial, runs the agent inside it, then executes a
verifier against the environment the agent leaves behind. Because the verifier
runs in that same environment, it can do what a judge cannot: serve the site,
start a browser, fill in a form, click the button, and assert on what actually
happens. Harbor's contract is deliberately narrow. Write a number to
`/logs/verifier/reward.json`, and Harbor supplies everything around it, namely
per-trial provisioning, parallel fan-out, repeated attempts for variance, and
reporting into LangSmith.

**So the two approaches answer different questions.** A traditional evaluation
answers "does this output look correct," which is cheap, fast, and broad enough
to run on everything. A Harbor evaluation answers "does the software the agent
produced actually work," which is slower and more expensive but is the only one
of the two that can gate a release. For deep agent tasks, where the deliverable
is a working artifact rather than a piece of text, the second question is
usually the one you needed answered.

This repository demonstrates that difference on a single concrete artifact.

> **The rule it illustrates:** if you would have to click the button to know
> whether it worked, grading the output cannot get you there.

---

## Demo context

The product is a stripped-down Lovable. You type a brief into a chat pane and
watch a website appear in a live preview beside it, file by file, as the agent
writes it.

<!-- SCREENSHOT: the chat UI at localhost:8000, mid-build, chat on the left and live preview on the right -->

The agent is built with [deepagents](https://github.com/langchain-ai/deepagents)
and has four things worth knowing about:

| piece | what it does |
| --- | --- |
| a planner | writes a todo list before touching any files, so multi-page briefs get real structure |
| a filesystem backend | reads and writes the site directory directly, which is what makes follow-up turns edits rather than rebuilds |
| two subagents | `page-builder` composes one page at a time, `site-reviewer` reads the finished site cold and reports problems |
| `check_site` | a structural linter the agent calls on its own output before claiming it is done |

House rules live in [`deep-agent/AGENTS.md`](deep-agent/AGENTS.md), which is
inlined into the system prompt on every run. Editing that markdown file changes
what the product ships without touching any code.

### One graph, two runtimes

This is the structural claim of the demo. There is no test double and no
re-implementation. The same graph serves the product and both evaluations, and
the only thing that changes is which directory it builds into.

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

### Running it

```bash
make setup
```

That installs dependencies, fetches Chromium for the verifier, and reminds you
to add `LANGSMITH_API_KEY` to `.env`. Model credentials come from the ambient
environment (`ANTHROPIC_API_KEY`, plus `ANTHROPIC_BASE_URL` if you route
through a gateway). Keep those two out of `.env`, because plain `load_dotenv()`
never overrides an already-set variable and that is what lets the ambient value
win.

```bash
make ui
```

Open http://localhost:8000 and type *"A landing page for Rye & Co, a sourdough
bakery in Portland."* A cold build takes roughly 65 seconds and five tool
calls. Watch the order of operations in the chat pane, because that ordering is
the deep agent behaviour: it plans first, reads `styles.css` before writing
anything so it composes from existing design tokens instead of inventing a
palette, writes the page, then calls `check_site` on itself.

<img width="1720" height="968" alt="image" src="https://github.com/user-attachments/assets/d8a0dd5a-1aa5-4a47-b4ef-974cd22100e6" />

Follow up with *"make the hero darker."* That takes about 20 seconds and one
`edit_file` call. The site is on disk and the thread is checkpointed, so a
second turn edits the existing site rather than regenerating it.

The graph also runs in LangGraph Studio, which is the fastest way to see the
subagent calls as a graph:

```bash
cd deep-agent && uv run langgraph dev
```

---

## Traditional evals

This is the evaluation most teams building on agents already have, and it is
implemented here in full rather than as a strawman.

[`traditional/run_eval.py`](traditional/run_eval.py) creates a LangSmith
dataset of five briefs and scores each run with four evaluators plus one
recorded metric:

| evaluator | kind | what it asks |
| --- | --- | --- |
| `no_structural_errors` | code | doctype, `lang`, title, viewport, exactly one `h1`, alt text on images, internal links and stylesheet references that resolve |
| `brief_coverage` | code | did the page actually contain what the brief asked for |
| `design_quality` | LLM judge | is this a well-composed, credible-looking page |
| `follows_house_rules` | LLM judge | does it comply with the rules in `AGENTS.md` |
| `tool_calls` | recorded | how much work did it do, so effort is visible at all |

The split is deliberate. The code evaluators are cheap, deterministic, and
cover considerably more than people expect. The judge is asked only about the
things code genuinely cannot assess. It is not weakened to manufacture a
result: on the booking-form brief it cites `aria-describedby` and verifies that
labels are associated with the correct inputs. If that came back on a pull
request, you would be pleased with it.

```bash
make judge                                                   # all five briefs
make judge-quick                                             # one brief, no judges
uv run python traditional/run_eval.py --offline              # code evaluators, no model
uv run python traditional/run_eval.py --dataset-only         # sync the dataset only
```

Results land in LangSmith as the `site-builder-briefs` experiment.

<!-- SCREENSHOT: LangSmith `site-builder-briefs` experiment, evaluator columns green across the row -->
<img width="1448" height="825" alt="image" src="https://github.com/user-attachments/assets/05e96919-9433-43b8-8310-cc6b285adfdd" />


<!-- SCREENSHOT: the judge's reasoning expanded on the halden-cycles-booking-form row -->


On the `halden-cycles-booking-form` brief, the code evaluators return **1.00
for structure and 1.00 for coverage.** Every requirement in the brief is
present and the markup is sound. Nothing here is a lucky pass or a rigged
rubric, and that matters for what comes next.

---

## What the traditional eval misses

Here is the page the evaluation just scored. Serve it and click through it
yourself:

```bash
make page
```

<!-- SCREENSHOT: the rendered Halden Cycles page, hero and services and booking form -->

Scroll to the booking form and read its source:

```html
<form action="#" method="post" novalidate>
  <label for="email">Email address</label>
  <input type="email" id="email" name="email" autocomplete="email" required>
```

Labels tied to inputs, `type="email"`, `required` on the fields that matter,
autocomplete hints. This is the markup you would want. Nobody blocks it in
review, and every source-reading check in the previous section passes it,
correctly.

Now submit it with every field empty.

<!-- SCREENSHOT: the browser showing "Error code: 501, Message: Unsupported method ('POST')" -->

```
Error code: 501
Message: Unsupported method ('POST').
```

Two separate failures happen at once.

**The validation is decorative.** Every field carries `required`, and the form
also carries `novalidate`, which cancels all of it. There is no JavaScript on
the page to make up the difference, so an empty form submits.

**The submission goes nowhere.** A static site has nothing listening for a
POST, so the customer sees a server error instead of the bike shop's site. If
this were live, someone would believe they had booked a repair and the shop
would never hear from them.

Neither failure is visible to any check that reads the source. The first is a
*combination* of two attributes that are individually correct. The second is
**an event that did not happen**, and absence of an event is not something a
document contains. Reading the trace does not help either, because
`write_file` genuinely did succeed and the trace says so accurately.

So the transition is not "the traditional eval was bad." The traditional eval
was right about everything it examined. The question is what check would have
caught this, and the answer is the one that fills in the form and clicks the
button.

---

## Harbor evals

### What a Harbor eval is

Harbor evaluates an agent by running it inside an environment and then grading
the environment, not the transcript. A Harbor **task** is a directory with four
parts:

| part | role |
| --- | --- |
| `instruction.md` | the brief handed to the agent, and nothing else |
| `environment/` | a Dockerfile describing the world the agent wakes up in |
| `tests/` | the verifier, run after the agent finishes |
| `solution/` | a reference answer, used to prove the task is passable |

A **trial** is one run of one agent against one task. Harbor provisions the
environment, runs the agent inside it, copies `tests/` in, executes
`tests/test.sh`, and reads the result. The verifier's only obligation is to
write a JSON object of metric names to scores at
`/logs/verifier/reward.json`. Harbor is agnostic about how it arrives at those
numbers.

That narrow contract is what makes the approach general. Harbor's own examples
use pytest. This project runs a browser because the artifact is a website.
Playwright is our choice here, not a Harbor requirement or default.

Everything else is infrastructure Harbor provides so you do not build it
yourself: an environment per trial, the agent-under-test as a swappable
component, parallel fan-out, repeated attempts to measure variance, and the
plumbing that turns a job into a LangSmith experiment with reward, cost, token
counts, and the agent's own trace attached.

### Setting it up in this project

The task lives in [`dataset/`](dataset/):

```
dataset/
├── _shared/functional.py                 # the generic browser suite, shared by every task
├── sync.py                               # vendors _shared into each task's tests/
├── harbor-job.json                       # the job config: snapshot, agent, tasks, artifacts
└── halden-cycles-booking-form/
    ├── task.toml                         # timeouts, resources, SITE_DIR
    ├── instruction.md                    # the same brief the traditional eval uses
    ├── environment/
    │   ├── Dockerfile                    # python:3.12-slim-bookworm + Chromium
    │   └── site/                         # the scaffold the agent starts from
    ├── tests/
    │   ├── test.sh                       # Harbor's entrypoint
    │   ├── check.py                      # this brief's coverage check, roughly five lines
    │   └── functional.py                 # generated copy of _shared/functional.py
    └── solution/solve.sh                 # oracle reference, scores 1.0
```

Three setup details are worth calling out because each one exists in response
to a specific failure rather than a preference.

**The agent is staged into the container, not reimplemented.**
`harbor-job.json` points Harbor's LangGraph agent at `./deep-agent`, and it
runs the graph named in `langgraph.json`. `configurable.cwd` and the
`SITE_DIR` environment variable both point at `/app/site`, which is also the
directory the verifier inspects. Without `SITE_DIR` the agent falls back to a
per-thread workspace and the verifier finds an empty site.

**`functional.py` is vendored into each task, not imported.** Harbor uploads a
task's `tests/` directory on its own, so a verifier can only import what sits
beside it. Edit the shared source, then run `make sync` before any Harbor run.
The Makefile targets already depend on it.

**Trials run on a pre-built LangSmith sandbox snapshot.** Building the image
server-side takes minutes, so build it once and pin it:

```bash
make snapshot        # must print status: ready
```

<!-- SCREENSHOT: LangSmith Sandboxes page showing the site-builder-playwright snapshot as ready -->

Each trial then gets its own container, torn down afterwards. That isolation is
not decoration: this evaluation runs a browser *and* gives an agent shell
access, per trial, in parallel. The same reasoning applies to the builder
itself, whose local `LocalShellBackend` is explicitly unsandboxed and would
need a sandbox per session in any deployed version.

Three CLI flags cannot live in the JSON config and are load-bearing. They are
kept in the `HARBOR_ARGS` block of the [Makefile](Makefile):

- `--env-file .env`, because the Harbor CLI does not read `.env` itself and the
  LangSmith plugin hard-fails without `LANGSMITH_API_KEY`
- `--ae ANTHROPIC_BASE_URL=...`, because Harbor forwards `ANTHROPIC_API_KEY`
  but not the base URL, so a gateway-scoped key gets a 401 from
  `api.anthropic.com`
- `--plugin langsmith --pk dataset_name=...`, because plugins are not part of
  `JobConfig`

### What we are measuring

The verifier has two layers, and separating them is what keeps the evaluation
honest.

**The generic layer** is
[`dataset/_shared/functional.py`](dataset/_shared/functional.py). It contains
no business name and no brief. Its organising idea is to hold the page to the
promises its own markup makes:

```
<a href="x">           I lead somewhere
<img src="x">          I will show you something
<link rel=stylesheet>  I change how this looks
<form>                 I accept input
required               I will refuse to submit empty
type="email"           I will refuse a non-address
meta viewport          I work on a phone
```

Every check asserts one of those declarations, which yields five metrics any
web-authoring task can inherit:

| metric | how it is measured |
| --- | --- |
| `renders` | the page loads, and every link, image, and stylesheet it declares resolves |
| `controls_work` | fill the form, submit it, and confirm the submission reached somewhere useful or produced a visible confirmation |
| `validation_works` | submit an empty form and confirm it is refused, but only if the markup declared validation |
| `responsive` | load at 375px wide and measure horizontal overflow |
| `no_errors` | no console errors and no failed requests while the page loads |

Two fairness rules apply, because a check nothing can satisfy is as broken as
one nothing can fail. The suite only asserts against declarations that are
actually present, so a page with no `<form>` has `controls_work` skipped rather
than failed. And it honours anything the markup declares inert, such as
`disabled` or `aria-disabled`, and skips off-origin resources an offline
verifier cannot resolve.

One implementation detail carries real weight: the site is served over HTTP
from a subpath, never from the server root and never over `file://`. At the
root, `href="/styles.css"` resolves and an absolute-path bug hides. From a
subpath it 404s, exactly as it does in the real preview.

**The task-specific layer** is
[`tests/check.py`](dataset/halden-cycles-booking-form/tests/check.py), which is
deliberately thin. Three constants and one function ask whether the page
mentioned Halden and Minneapolis, listed at least three prices, and included a
form with at least three labelled fields. It contributes a single metric,
`brief_coverage`.

`reward` is conjunctive across both layers. A flawlessly working page that
ignored the brief is not a pass, and neither is a page that says all the right
things and does nothing.

### Running it

```bash
make harbor                    # one trial
make attempts ATTEMPTS=5       # five trials, because one run is not an estimate
make haiku                     # the same task on a cheaper model tier
make oracle                    # the reference solution, proving 1.0 is reachable
make results                   # print the last result without spending anything
```

A trial costs roughly $0.20 and takes about 90 seconds.

<!-- SCREENSHOT: LangSmith Harbor experiment, per-metric feedback columns with controls_work at 0.00 -->

<img width="1327" height="439" alt="image" src="https://github.com/user-attachments/assets/4d11aabe-45b8-422e-9a46-1c086230d80c" />

<img width="1146" height="684" alt="image" src="https://github.com/user-attachments/assets/fe1c13b6-0fd3-49cd-b82c-7943f2f216ed" />

```
renders             1.0
brief_coverage      1.0
controls_work       0.0   nothing happened on submit — no request,
validation_works    1.0      no confirmation (6 fields filled)
responsive          1.0
no_errors           1.0
REWARD              0.0
```

### The comparison

|                            | traditional eval | Harbor eval |
| -------------------------- | ---------------- | ----------- |
| is the markup sound        | 1.00             | 1.00        |
| did it cover the brief      | 1.00             | 1.00        |
| design quality              | judge            | not assessed |
| does it work on a phone     | no such check    | 1.00        |
| any runtime errors          | no such check    | 1.00        |
| **does the form submit**    | **no such check** | **0.00**   |
|                            |                  | **reward 0.00** |

`brief_coverage` is the same function on both sides, written once and called by
both evaluations. The two agree on every check they can both make.

Note also what Harbor does *not* say. It does not score this page zero across
the board, which would be grounds for suspecting a rigged rubric. It says the
page is good, and the form does not work.

---

## Repo map

| path | what it is |
| --- | --- |
| `deep-agent/agent.py` | the agent: subagents, `check_site`, and `make_graph` for Harbor |
| `deep-agent/AGENTS.md` | house rules, read every run, editable without touching code |
| `deep-agent/sitecheck.py` | structural checks, used as the agent's linter and as a grading rubric |
| `deep-agent/langgraph.json` | graph name and container dependency pins |
| `server.py`, `static/index.html` | the chat UI: SSE stream, live preview, file tree |
| `scaffold/` | design-token stylesheet and placeholder page, seeded per session |
| `traditional/run_eval.py` | the traditional evaluation: five briefs, five evaluators |
| `dataset/_shared/functional.py` | the generic browser suite, five reusable metrics |
| `dataset/halden-cycles-booking-form/` | the Harbor task |
| `dataset/harbor-job.json` | Harbor job config: snapshot pin, agent kwargs, artifacts |
| `demo-pages/halden-cycles-scored/` | the recorded page the traditional eval scored 1.00 |
| `build_snapshot.py` | builds and inspects the LangSmith sandbox snapshot |
| `scripts/verify.py` | free gate: is the verifier still sound |
| `DEMO.md` | the speakable talk track for presenting this |

---

## Notes from building it

The non-obvious things, recorded so nobody has to rediscover them.

- **deepagents 0.7.x does not include `TodoListMiddleware` by default.** Add it
  explicitly or there is no `write_todos` tool.
- **`build_timeout_sec` in `task.toml` is the gate on environment start**, and
  it defaults to 600s. The LangSmith environment's own
  `--ek startup_timeout_seconds` is a different, inner timeout; raising that
  alone does nothing because the outer one fires first.
- **`python:3.12-slim` now tracks Debian trixie**, where Playwright 1.49.1's
  apt list names packages that have been renamed. Pin `-bookworm`.
- **`--ak project_path=.` with the default `jobs_dir`** makes `copytree`
  recurse into its own output, 64 path segments deep. Hence
  `jobs_dir: /tmp/harbor-jobs` and `project_path: ./deep-agent`.
- **A LangSmith snapshot record can exist with `status: failed`.** Matching on
  name alone will report a usable snapshot that is not one, so check the status.
- **`fs_capacity_bytes` has a 16 GiB floor** on the Dockerfile path. It is not
  tunable below that.
- **A POST back to the page's own URL is not a submission.** Counting it
  produced a false pass on `controls_work`, because the test fixture had no
  `action` at all while the real agent wrote `action="#"`.
- **Serve from a subpath, never the root.** Absolute-path bugs are invisible at
  `/`. This project once shipped a page that rendered completely unstyled while
  the structural checker reported no errors, and it was found only by looking
  at the render.

---

## Links

- [deepagents](https://github.com/langchain-ai/deepagents)
- [LangSmith Harbor integration](https://docs.langchain.com/langsmith/harbor-integrations)
- [LangSmith Sandboxes](https://docs.langchain.com/langsmith/sandboxes)
- [LangGraph](https://github.com/langchain-ai/langgraph)
