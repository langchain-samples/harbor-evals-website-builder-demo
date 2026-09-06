"""Verifier: was the site repaired, or was it rewritten?

Structure carries more weight here than in the build tasks — repair *is* the
job. The content assertions exist to catch the shortcut: an agent that deletes
both pages and generates clean replacements scores 1.0 on structure and should
still fail the task.
"""

import sys
from pathlib import Path

# Harbor mounts tests/ at /tests; fall back to this file's own directory
# so the verifier can also be run against a local site during development.
sys.path.insert(0, "/tests" if Path("/tests").is_dir() else str(Path(__file__).parent))

from harness import Scorecard, site_from_argv

# Sentences from the original copy, one per section. If the agent rewrote the
# site instead of fixing it, these go missing.
PRESERVED = [
    "Furniture restoration in Providence since 1978",
    "the pieces other shops turn away",
    "French polishing, veneer patching, and hand-caning",
    "We quote in writing before any work starts",
    "44 Dexter Street",
    "401-555-0142",
    "we can recommend two movers who handle antiques carefully",
]

BASELINE_WORDS = 173  # measured on the seed site

site = site_from_argv()
card = Scorecard(site)

card.check("index.html still exists", "index.html" in site.pages)
card.check("contact-us.html still exists", "contact-us.html" in site.pages)
card.check(
    "no pages added or removed",
    len(site.pages) == 2,
    f"{len(site.pages)} pages: {', '.join(site.pages)}",
)

text = " ".join(site.text().split())
missing = [phrase for phrase in PRESERVED if phrase not in text]
card.check(
    "original copy preserved",
    not missing,
    f"{len(missing)} phrase(s) lost, e.g. {missing[0]!r}" if missing else "",
)

words = len(text.split())
card.check(
    "copy not trimmed",
    words >= BASELINE_WORDS * 0.9,
    f"{words} words vs {BASELINE_WORDS} in the original",
)

# The design was declared fine; the tokens should still be there.
card.check(
    "stylesheet kept its design tokens",
    all(token in site.css for token in ["--ink", "--paper", "--accent"]),
    "custom properties were removed",
)
card.check(
    "still one stylesheet",
    len(site.styles) == 1,
    f"{len(site.styles)} .css files",
)
card.check(
    "CDN stylesheet removed",
    "cdn.jsdelivr.net" not in site.html,
    "the external stylesheet is still linked",
)

# Repair is structural work, so structure gets the larger share.
sys.exit(card.finish(weight_structure=0.6))
