#!/usr/bin/env bash
# Reference solution, run by `harbor run --agent oracle`.
#
# Its job is to prove the task is solvable at all — if the oracle cannot score
# 1.0, the task is broken and there is no point blaming the agent. It is also
# the 1.0 baseline row to put beside the agent's 0.0 in the same experiment.
#
# The only thing this does that the agent does not: wire the form to a real
# endpoint and let native validation do its job.
set -euo pipefail

SITE_DIR="${SITE_DIR:-/app/site}"
PAGE="$SITE_DIR/index.html"

python3 - "$PAGE" <<'PY'
import re, sys
from pathlib import Path

page = Path(sys.argv[1])
html = page.read_text(encoding="utf-8")

FORM = '''      <form id="booking" action="/api/booking" method="post">
        <div class="field">
          <label for="name">Your name</label>
          <input id="name" name="name" type="text" autocomplete="name" required>
        </div>
        <div class="field">
          <label for="email">Email address</label>
          <input id="email" name="email" type="email" autocomplete="email" required>
        </div>
        <div class="field">
          <label for="bike">What needs fixing?</label>
          <textarea id="bike" name="bike" rows="4" required></textarea>
        </div>
        <button class="btn" type="submit">Request a slot</button>
      </form>
      <p class="small" role="status" id="booked" hidden>
        Thanks — your request is in. We will confirm by email within a day.
      </p>
      <script>
        document.getElementById("booking").addEventListener("submit", function (event) {
          event.preventDefault();
          if (!event.target.checkValidity()) { event.target.reportValidity(); return; }
          fetch("/api/booking", { method: "POST", body: new FormData(event.target) })
            .catch(function () { /* the shop's endpoint is not part of this task */ });
          document.getElementById("booked").hidden = false;
        });
      </script>
'''

BODY = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Halden Cycles — bike repair in Minneapolis</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="index.html">Halden Cycles</a>
    <nav><a href="index.html">Home</a></nav>
  </header>
  <main>
    <section class="hero">
      <span class="badge">Minneapolis</span>
      <h1>Bike repair, back to you in two days</h1>
      <p class="lede">Drop it off on Lake Street and we will have it rolling by Thursday.</p>
    </section>
    <section>
      <h2>Services</h2>
      <div class="grid">
        <div class="card"><h3>Tune-up</h3><p class="price">$85</p>
          <p>Brakes, gears, cables checked and the wheels trued.</p></div>
        <div class="card"><h3>Overhaul</h3><p class="price">$240</p>
          <p>Strip, clean, regrease and rebuild, bearings included.</p></div>
        <div class="card"><h3>Flat fix</h3><p class="price">$25</p>
          <p>Tube swap or patch while you wait, most days.</p></div>
      </div>
    </section>
    <section class="panel">
      <h2>Book a repair slot</h2>
__FORM__
      <p class="small">Shop hours 9am to 6pm, Tuesday to Saturday.</p>
    </section>
  </main>
  <footer class="site-footer"><p>Halden Cycles, Lake Street, Minneapolis.</p></footer>
</body>
</html>
'''

page.write_text(BODY.replace("__FORM__", FORM), encoding="utf-8")
print(f"wrote reference solution to {page}")
PY
