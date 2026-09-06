"""Verifier: did the agent build the bakery landing page it was asked for?

Structural checks come from the shared harness. Everything below is specific
to this brief — the part the agent cannot satisfy by linting.
"""

import re
import sys
from pathlib import Path

# Harbor mounts tests/ at /tests; fall back to this file's own directory
# so the verifier can also be run against a local site during development.
sys.path.insert(0, "/tests" if Path("/tests").is_dir() else str(Path(__file__).parent))

from harness import Scorecard, site_from_argv

site = site_from_argv()
card = Scorecard(site)

card.check("index.html exists", "index.html" in site.pages)

home = site.pages.get("index.html", "")
text = site.text("index.html")

h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", home, re.S | re.I)
h1_text = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""
card.check("h1 names the bakery", "rye" in h1_text.lower(), f"h1 was {h1_text!r}")

card.check(
    "at least three content sections",
    len(re.findall(r"<h2\b", home, re.I)) >= 3,
    f"{len(re.findall(r'<h2\\b', home, re.I))} <h2> found",
)

card.check("mentions Portland", "portland" in text.lower())

# "Visit us" means an address and hours a customer could actually act on.
card.check(
    "opening hours present",
    bool(re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", text, re.I)),
    "no am/pm time found",
)
card.check(
    "street address present",
    bool(re.search(r"\b\d{2,5}\s+[A-Z][A-Za-z]+\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|Way|Dr|Drive)\b", text)),
    "no street address found",
)

card.check("real body copy", len(text.split()) >= 200, f"{len(text.split())} words")
card.check_no_placeholders()

card.check("a stylesheet was written", bool(site.styles), "no .css file")
card.check(
    "design tokens in :root",
    bool(re.search(r":root\s*\{[^}]*--", site.css, re.S)),
    "no custom properties in :root",
)
card.check(
    "responsive breakpoint",
    "@media" in site.css,
    "no @media query",
)

sys.exit(card.finish())
