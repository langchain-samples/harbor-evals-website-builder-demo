"""Structural checks on a generated static site.

This file is deliberately dependency-free (stdlib only) and deliberately
shared. It is used in two places:

  * as an agent tool (`check_site`), so the builder can lint its own work
    before it claims to be done
  * inside every Harbor eval container, as the structural half of the reward

Sharing it is the point. The spec for "a working page" gets written once; the
agent treats it as a linter and the grader treats it as a rubric. What the
eval adds on top is the part the agent *cannot* lint its way to — whether the
page actually contains what the brief asked for. Those content assertions
live in each task's verifier, never here.

Errors fail the build. Warnings are style: they are reported to the agent and
recorded by the grader, but they do not by themselves sink a task.
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

# Tags that must be explicitly closed for the document to be well formed.
# Void elements and the optional-close tags (p, li, td...) are excluded on
# purpose — browsers close them and flagging them would be noise.
_MUST_CLOSE = {
    "html", "head", "body", "div", "section", "article", "header", "footer",
    "nav", "main", "aside", "form", "table", "ul", "ol", "select", "textarea",
    "button", "a", "h1", "h2", "h3", "figure", "label",
}
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class _Page(HTMLParser):
    """Collects everything the checks need in a single pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.unclosed: list[str] = []
        self.stray_close: list[str] = []
        self.has_doctype = False
        self.html_lang: str | None = None
        self.title = ""
        self._in_title = False
        self.viewport = False
        self.headings: list[tuple[str, str]] = []
        self._heading: str | None = None
        self._heading_text = ""
        self.images: list[dict] = []
        self.links: list[str] = []
        self.stylesheets: list[str] = []
        self.scripts: list[str] = []
        self.style_blocks = 0
        self.inline_styles = 0
        self.form_fields: list[dict] = []
        self.labels_for: set[str] = set()
        self.text_len = 0

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        if tag in _MUST_CLOSE:
            self.stack.append(tag)
        if "style" in attrs and attrs["style"].strip():
            self.inline_styles += 1

        if tag == "html":
            self.html_lang = attrs.get("lang") or None
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            if attrs.get("name", "").lower() == "viewport":
                self.viewport = True
        elif tag == "style":
            self.style_blocks += 1
        elif tag in {"h1", "h2", "h3"}:
            self._heading, self._heading_text = tag, ""
        elif tag == "img":
            self.images.append({"src": attrs.get("src", ""), "alt": attrs.get("alt")})
        elif tag == "a":
            if "href" in attrs:
                self.links.append(attrs["href"])
        elif tag == "link":
            rel = attrs.get("rel", "").lower()
            if "stylesheet" in rel:
                self.stylesheets.append(attrs.get("href", ""))
        elif tag == "script":
            if attrs.get("src"):
                self.scripts.append(attrs["src"])
        elif tag in {"input", "textarea", "select"}:
            self.form_fields.append({
                "tag": tag,
                "type": attrs.get("type", "text").lower(),
                "name": attrs.get("name", ""),
                "id": attrs.get("id", ""),
                "required": "required" in attrs,
            })
        elif tag == "label":
            if attrs.get("for"):
                self.labels_for.add(attrs["for"])

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._heading == tag:
            self.headings.append((tag, self._heading_text.strip()))
            self._heading = None
        if tag in _VOID or tag not in _MUST_CLOSE:
            return
        if tag in self.stack:
            # Popping past still-open elements means they were never closed.
            # A browser recovers silently here; we report it, because it is
            # exactly the kind of damage a repair task asks the agent to find.
            while self.stack:
                popped = self.stack.pop()
                if popped == tag:
                    break
                self.unclosed.append(popped)
        else:
            self.stray_close.append(tag)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._heading is not None:
            self._heading_text += data
        self.text_len += len(data.strip())

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self.unclosed += list(self.stack)


def _is_external(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"} or url.startswith("//")


def _is_offsite_ref(url: str) -> bool:
    """A link we should not try to resolve on disk."""
    return _is_external(url) or urlparse(url).scheme in {"mailto", "tel", "data"} or url.startswith("#") or not url.strip()


def _resolve(site: Path, page: Path, url: str) -> Path:
    """Resolve an href/src the way a browser serving `site` statically would."""
    target = unquote(urlparse(url).path)
    if not target:
        return page
    base = site if target.startswith("/") else page.parent
    resolved = (base / target.lstrip("/")).resolve()
    if resolved.is_dir():
        resolved = resolved / "index.html"
    return resolved


def check_site(root: str | Path) -> dict:
    """Run every structural check over the site rooted at `root`."""
    site = Path(root).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not site.is_dir():
        return {"ok": False, "pages": [], "errors": [f"site root {site} does not exist"], "warnings": []}

    pages = sorted(p for p in site.rglob("*.html") if ".harbor" not in p.parts)
    if not pages:
        return {"ok": False, "pages": [], "errors": ["no .html files found"], "warnings": []}
    if not (site / "index.html").is_file():
        errors.append("no index.html at the site root")

    for page in pages:
        rel = page.relative_to(site).as_posix()
        parser = _Page()
        try:
            parser.feed(page.read_text(encoding="utf-8", errors="replace"))
            parser.close()
        except Exception as exc:  # a page that cannot be parsed at all
            errors.append(f"{rel}: unparseable ({exc})")
            continue

        if not parser.has_doctype:
            errors.append(f"{rel}: missing <!doctype html>")
        if not parser.html_lang:
            errors.append(f"{rel}: <html> has no lang attribute")
        if not parser.title.strip():
            errors.append(f"{rel}: empty or missing <title>")
        if not parser.viewport:
            errors.append(f"{rel}: missing responsive viewport meta tag")
        if parser.unclosed:
            errors.append(f"{rel}: unclosed tags: {', '.join(parser.unclosed)}")
        if parser.stray_close:
            errors.append(f"{rel}: closing tags with no opener: {', '.join(sorted(set(parser.stray_close)))}")

        h1s = [text for tag, text in parser.headings if tag == "h1"]
        if not h1s:
            errors.append(f"{rel}: no <h1>")
        elif len(h1s) > 1:
            warnings.append(f"{rel}: {len(h1s)} <h1> elements, expected one")

        for img in parser.images:
            if img["alt"] is None or not img["alt"].strip():
                errors.append(f"{rel}: <img src=\"{img['src']}\"> has no alt text")

        for href in parser.links:
            if _is_offsite_ref(href):
                continue
            target = _resolve(site, page, href)
            if not target.is_file():
                errors.append(f"{rel}: broken link -> {href}")

        for href in parser.stylesheets:
            if _is_external(href):
                errors.append(f"{rel}: external stylesheet {href} (site must be self-contained)")
            elif not _resolve(site, page, href).is_file():
                errors.append(f"{rel}: stylesheet not found -> {href}")

        for src in parser.scripts:
            if _is_external(src):
                errors.append(f"{rel}: external script {src} (site must be self-contained)")
            elif not _resolve(site, page, src).is_file():
                errors.append(f"{rel}: script not found -> {src}")

        if not parser.stylesheets and parser.style_blocks:
            warnings.append(f"{rel}: styles are inline in a <style> block, not a linked stylesheet")
        if parser.inline_styles:
            warnings.append(f"{rel}: {parser.inline_styles} inline style attribute(s)")
        if parser.text_len < 120:
            warnings.append(f"{rel}: very little text content ({parser.text_len} chars)")

        for field in parser.form_fields:
            if field["type"] in {"hidden", "submit", "button"}:
                continue
            if not field["name"]:
                warnings.append(f"{rel}: <{field['tag']}> has no name attribute")
            if field["id"] and field["id"] not in parser.labels_for:
                warnings.append(f"{rel}: field #{field['id']} has no <label for>")

    css_files = sorted(p for p in site.rglob("*.css"))
    for css in css_files:
        text = css.read_text(encoding="utf-8", errors="replace")
        if text.count("{") != text.count("}"):
            errors.append(f"{css.relative_to(site).as_posix()}: unbalanced braces")
        if not re.search(r"@media", text):
            warnings.append(f"{css.relative_to(site).as_posix()}: no @media query — is it responsive?")

    return {
        "ok": not errors,
        "pages": [p.relative_to(site).as_posix() for p in pages],
        "stylesheets": [p.relative_to(site).as_posix() for p in css_files],
        "errors": errors,
        "warnings": warnings,
    }


def format_report(report: dict) -> str:
    """Human/agent-readable rendering of a report."""
    lines = [f"Pages: {', '.join(report['pages']) or 'none'}"]
    if report.get("stylesheets"):
        lines.append(f"Stylesheets: {', '.join(report['stylesheets'])}")
    if report["errors"]:
        lines.append(f"\n{len(report['errors'])} ERROR(S) — these must be fixed:")
        lines += [f"  - {e}" for e in report["errors"]]
    else:
        lines.append("\nNo errors.")
    if report["warnings"]:
        lines.append(f"\n{len(report['warnings'])} warning(s):")
        lines += [f"  - {w}" for w in report["warnings"]]
    return "\n".join(lines)


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    report = check_site(root)
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
    sys.exit(0 if report["ok"] else 1)
