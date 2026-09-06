"""Verifier: three pages, one navigation, one stylesheet, a usable form."""

import re
import sys
from pathlib import Path

# Harbor mounts tests/ at /tests; fall back to this file's own directory
# so the verifier can also be run against a local site during development.
sys.path.insert(0, "/tests" if Path("/tests").is_dir() else str(Path(__file__).parent))

from harness import Scorecard, site_from_argv

EXPECTED = ["index.html", "services.html", "contact.html"]

site = site_from_argv()
card = Scorecard(site)

for page in EXPECTED:
    card.check(f"{page} exists", page in site.pages)

# The interesting failure mode: pages built independently drift apart.
card.check_shared_nav([p for p in EXPECTED if p in site.pages])

services = site.pages.get("services.html", "")
services_text = site.text("services.html")
card.check(
    "at least three named services",
    len(re.findall(r"<h[23]\b", services, re.I)) >= 3,
    f"{len(re.findall(r'<h[23]\\b', services, re.I))} service headings",
)
prices = re.findall(r"\$\s?\d+", services_text)
card.check("a price per service", len(prices) >= 3, f"found {len(prices)} prices")

contact = site.pages.get("contact.html", "")
card.check("contact page has a form", bool(re.search(r"<form\b", contact, re.I)))
card.check(
    "form asks for an email",
    bool(re.search(r'<input[^>]*type\s*=\s*["\']email["\']', contact, re.I))
    or bool(re.search(r'<input[^>]*name\s*=\s*["\'][^"\']*email', contact, re.I)),
    "no email input",
)
card.check(
    "form asks for a name",
    bool(re.search(r'<input[^>]*name\s*=\s*["\'][^"\']*name', contact, re.I)),
    "no name input",
)
card.check(
    "form asks for a message",
    bool(re.search(r"<textarea\b", contact, re.I)),
    "no textarea",
)
labels = len(re.findall(r"<label\b[^>]*\bfor\s*=", contact, re.I))
card.check("form fields are labelled", labels >= 3, f"{labels} <label for> elements")

card.check("mentions Boulder", "boulder" in site.text().lower())
card.check_no_placeholders()

# One stylesheet for the whole site, per the house rules.
card.check(
    "exactly one stylesheet",
    len(site.styles) == 1,
    f"{len(site.styles)} .css files: {', '.join(site.styles) or 'none'}",
)
card.check("responsive breakpoint", "@media" in site.css, "no @media query")

sys.exit(card.finish())
