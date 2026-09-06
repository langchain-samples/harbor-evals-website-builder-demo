"""Verifier: does the new page belong to the site it was added to?

`pricing.html exists` is one assertion out of eleven. The rest are about
consistency with code the agent did not write — the nav on the pages that
already existed, the token system, the single stylesheet.
"""

import re
import sys
from pathlib import Path

# Harbor mounts tests/ at /tests; fall back to this file's own directory
# so the verifier can also be run against a local site during development.
sys.path.insert(0, "/tests" if Path("/tests").is_dir() else str(Path(__file__).parent))

from harness import Scorecard, site_from_argv

EXPECTED = ["index.html", "about.html", "pricing.html"]
SEED_TOKENS = ["--ink", "--muted", "--paper", "--wash", "--brand", "--line", "--radius"]
SEED_COPY = [
    "We reconcile, we categorise",
    "job costing that ties back to your estimates",
    "Meridian opened in 2019",
]

site = site_from_argv()
card = Scorecard(site)

card.check("pricing.html exists", "pricing.html" in site.pages)
card.check(
    "existing pages still there",
    all(p in site.pages for p in ["index.html", "about.html"]),
    f"pages present: {', '.join(site.pages)}",
)

pricing = site.pages.get("pricing.html", "")
pricing_text = site.text("pricing.html")

tiers = len(re.findall(r"<h[23]\b", pricing, re.I))
card.check("three tiers", tiers >= 3, f"{tiers} tier headings")
prices = re.findall(r"\$\s?[\d,]+", pricing_text)
card.check("a price per tier", len(prices) >= 3, f"found {len(prices)} prices")
card.check("says what each tier includes", len(pricing_text.split()) >= 120, f"{len(pricing_text.split())} words")

# The check that actually separates the runs: was the nav updated everywhere,
# or only on the page the agent wrote?
present = [p for p in EXPECTED if p in site.pages]
missing_nav = [
    page for page in present
    if not any("pricing" in href for href in site.nav_links(page))
]
card.check(
    "pricing is in the nav on every page",
    not missing_nav,
    f"missing from {', '.join(missing_nav)}" if missing_nav else "",
)
card.check_shared_nav(present)

# Design-system consistency.
card.check(
    "still one stylesheet",
    len(site.styles) == 1,
    f"{len(site.styles)} .css files: {', '.join(site.styles)}",
)
card.check(
    "existing tokens intact",
    all(token in site.css for token in SEED_TOKENS),
    "custom properties were removed or renamed",
)
# Colours belong in :root. A new palette hard-coded into new rules is the
# failure this catches.
outside_root = re.sub(r":root\s*\{[^}]*\}", "", site.css, flags=re.S)
stray_hex = re.findall(r"#[0-9a-fA-F]{3,8}\b", outside_root)
card.check(
    "no colours hard-coded outside :root",
    not stray_hex,
    f"{len(stray_hex)} literal colour(s): {', '.join(sorted(set(stray_hex))[:4])}" if stray_hex else "",
)
card.check(
    "new page uses the token system",
    "var(--" in site.css and bool(re.search(r'class\s*=\s*["\'][^"\']*(panel|lede|brand)', pricing, re.I)),
    "pricing.html does not reuse the existing classes",
)

text = " ".join(site.text().split())
lost = [phrase for phrase in SEED_COPY if phrase not in text]
card.check(
    "existing copy untouched",
    not lost,
    f"lost {lost[0]!r}" if lost else "",
)

# The site starts structurally clean, so structure is not where the work is —
# it is weighted down to keep it from flattering a run that changed nothing.
sys.exit(card.finish(weight_structure=0.2))
