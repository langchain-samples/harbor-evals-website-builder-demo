# Talk track

**The argument in one line:** an LLM judge tells you whether the output looks
right; a verifier that runs the software tells you whether it works. Same
agent, same prompt, same run — they disagree, and the one that clicks the
button is correct.

15–20 minutes. Lines in **>** are things to say roughly as written.

---

## Before you walk in

```bash
make snapshot          # must print status: ready
make verify            # must end "The verifier is sound."
```

Two terminals in this directory. Four browser tabs: `localhost:8000`,
LangSmith `site-builder-briefs`, LangSmith `site-builder-briefs-harbor`,
LangSmith Sandboxes.

> ⚠️ **Run `make judge` once before you present.** The traditional
> experiment's *code* evaluators are confirmed (1.00 / 1.00 on the Halden
> page), but I have never seen the two judge scores. Act 2 assumes they land
> high. Read the real numbers and adjust the script.

---

## Act 1 — The product (4 min, live)

```bash
make ui
```

Type: **A landing page for Rye & Co, a sourdough bakery in Portland**

> "This is a barebones Lovable. Chat on the left, the site on the right. It's
> a deep agent with real file access — so watch the left pane, because the
> order of what it does is the interesting part."

As it goes (~65 seconds):

> "It wrote a plan first. Then it read the stylesheet before writing
> anything — it's composing from the design tokens that already exist rather
> than inventing a new palette. One write for the page. And now it's calling
> `check_site` — it's grading its own work before telling me it's done."

Then type: **make the hero darker**

> "Twenty seconds, one edit. It changed one variable in `:root`. It didn't
> rebuild the page — the site's on disk and the conversation is checkpointed,
> so a follow-up is an edit."

Optional, open `deep-agent/AGENTS.md`:

> "These are the house rules it reads every single run. Someone who doesn't
> write code changes what this ships by editing markdown."

---

## Act 2 — The eval most teams already have (4 min, pre-run)

LangSmith tab → `site-builder-briefs`.

> "Five briefs. Five evaluators. Two of them are code — is the markup sound,
> did it cover what the brief asked for. Two are an LLM judge — design
> quality, and compliance with those house rules. Plus we record the tool-call
> count, because otherwise nothing here tells you how much work it did."

Open the **halden-cycles-booking-form** row.

> "Green across the board."

Open the judge's reasoning and **read it out loud.**

> "And this is a good review. It's not hand-waving — it's citing
> `aria-describedby`, it's checking the labels are associated with the right
> inputs. If you got this in a PR you'd be pleased."

The point of this act is to make the judge credible. Don't rush it.

---

## Act 3 — The transition (3 min, live)

```bash
make page
```

**Scroll the page.**

> "So that's what it built. Hero, services with prices, a booking form."

**Put the form's source on screen.**

```html
<form action="#" method="post" novalidate>
  <label for="email">Email address</label>
  <input type="email" id="email" name="email" autocomplete="email" required>
```

> "Here's the form. Labels tied to inputs, `type=email`, `required` on the
> fields that matter, autocomplete hints. Would anyone block this in review?"

Let them say no.

> "Nor would I. Let's just look at the thing."

**Click Submit. Leave every field empty.**

```
Error response
Error code: 501
Message: Unsupported method ('POST').
```

Let the silence sit for a second.

> "Two things just happened. First — it submitted. Every one of those fields
> is marked `required`, and the form is also marked `novalidate`, which
> cancels all of it. There's no JavaScript to make up the difference. The
> validation is decorative.
>
> Second — the submission went nowhere. That's not the bike shop's site any
> more, that's a server error. If a customer did that, they'd think they'd
> booked a repair. The shop never hears from them."

**The pivot:**

> "Structure scored 1.00. Coverage scored five out of five. The judge praised
> the accessibility, and it was right to. So — what check would have caught
> that?"

**Staging rule: never announce the break.** "Let's just look at the thing" is
the whole setup. The moment you say "watch, it's broken," you've lost it.

---

## Act 4 — Harbor (5 min, pre-run)

> "So we wrote the check that clicks the button."

```bash
make results
```

```
renders             1.0
brief_coverage      1.0
controls_work       0.0   nothing happened on submit — no request,
validation_works    1.0      no confirmation (6 fields filled)
responsive          1.0
no_errors           1.0
REWARD              0.0
```

### The most important thirty seconds

Put the two score sheets side by side.

| | traditional | Harbor |
|---|---|---|
| is the markup sound | 1.00 | 1.00 |
| **did it cover the brief** | **1.00** | **1.00** |
| does it work on a phone | *no such check* | 1.00 |
| any runtime errors | *no such check* | 1.00 |
| **does the form submit** | ***no such check*** | **0.00** |

> "`brief_coverage` is literally the same function. I wrote it once and both
> evals call it. That's deliberate.
>
> These two evals agree on every single thing they can both see. The only
> thing they disagree about is the one thing you can only find out by filling
> in the form and clicking the button."

> "And that matters, because if Harbor had scored this page zero across the
> board, you'd be right to wonder whether I'd rigged it. Harbor isn't saying
> this page is bad. It's saying this page is good, *and the form doesn't
> work*."

### Show the check is general, not tuned to this bug

Open `dataset/_shared/functional.py` and read the docstring:

> "We never wrote 'check the Halden form.' We wrote: hold the page to the
> promises its own markup makes. An `<a href>` claims it leads somewhere. An
> `<img src>` claims it'll show you something. A `<form>` claims it accepts
> input. `required` claims it'll refuse an empty one. Every check in here
> asserts one of those. There's no business name in this file and no brief.
>
> It found the Halden form. It'll find the next one too."

### Where it ran

LangSmith → Sandboxes.

> "Each trial gets its own container, and it's torn down after. That's not
> decoration — this eval runs a browser *and* hands an agent shell access, per
> trial, in parallel. You can't do that safely on a laptop. Same reason a
> deployed version of the builder itself would want one."

---

## Act 5 — Close (2 min)

Pre-empt the objection before someone raises it:

> "The obvious response is: you don't need a browser, just read the trace.
>
> The trace shows `write_file` succeeded. `edit_file` succeeded. Every one of
> those is accurate — writing the files *did* work. But it can't show either
> failure. The first one is an event that didn't happen. The second is a
> change in whether something still works. Neither of those is in a
> transcript of what the agent did."

**The rule:**

> "If you'd have to click the button to know whether it worked, grading the
> output can't get you there."

**The framing — don't leave them thinking it's either/or:**

> "This isn't judges versus verifiers. The judge is fast, cheap and broad —
> run it on everything, use it to triage. The verifier is slow, expensive and
> true — put it on the ship decision. Triage with one, gate with the other."

---

## What you can defend

**Deterministic, six for six.** Every run has produced `<form action="#"
method="post">` with zero `<script>` tags. `controls_work` has failed every
time. This is the transition; lean on it.

**Variable — do not promise it.** `validation_works` only fails when the agent
adds `novalidate`. The last sandbox run omitted it and the check correctly
passed. Treat it as a bonus if it shows up, and if someone asks, say so —
"that one's run-dependent" is a much better answer than being caught.

**Cost, if asked.** ~$0.20 and ~90 seconds per trial. Five briefs × three
attempts is about three dollars.

**Not verified.** No live judge score has been observed (see the pre-flight
warning). `make attempts` and `make haiku` have not been run, so you cannot
yet say "five out of five" or "both model tiers."

---

## Objections, rehearsed

**"You wrote that check after finding the bug by hand."**

> "Partly true, and worth saying. The first version was form-specific and I
> threw it out. What's there now asserts only what the markup declares — no
> business name, no brief in the file. And `controls_work` comes from the
> brief itself: 'add a booking form so people can request a repair slot.' A
> form that discards submissions doesn't satisfy that, whatever the reason."

**"Static analysis would catch this."**

> "For this instance, partly yes — `action="#"` with no scripts is visible in
> the source, and so is `required` plus `novalidate`. The honest version is:
> to reason statically about whether a form does anything, you have to
> enumerate every way a form can be wired — the action, a JS listener, htmx
> attributes, a framework binding — and you're permanently behind that list.
> Running it is the general answer. It isn't the only one."

**"Why not just run Playwright in CI?"**

> "You could. What you'd be rebuilding is everything around the browser:
> provisioning an environment per trial, making the agent-under-test a
> swappable component, the parallel fan-out, repeated attempts for variance,
> and the plumbing that turns a job into an experiment with reward, cost,
> tokens and the agent's own trace attached. The point isn't that Playwright
> finds bugs. It's a harness that makes running the software as routine as
> calling a judge."

**"Is Playwright part of Harbor?"**

> "No, and it isn't the recommended default. Harbor's contract is just: write
> a number to `/logs/verifier/reward.json`. Its own examples use pytest. A
> browser is our choice because the artifact is a website."

**"Is the agent itself sandboxed?"**

> "Not in the local UI — that's a `LocalShellBackend`, and its own docs say
> there's no sandboxing. Fine for a laptop I'm driving. A deployed version
> needs one per session, and `LangSmithSandbox` is the drop-in. Which is the
> same reason Harbor puts every trial in a container."

---

## If the wifi dies

Acts 2, 3 and 4 are all pre-recorded — `make page` and `make results` are
local, and the LangSmith tabs are already loaded. Only Act 1 needs a model.
