# House rules for every site you build

This file is the spec. It is read on every run and is meant to be edited by
someone who does not touch the agent's code — change a rule here and the next
build follows it.

## What is already on disk

Most sites start with `index.html` and `styles.css` already present —
`styles.css` carries the design tokens and the layout classes. **Use them.**
If you are handed an empty directory, write both yourself, keeping the
stylesheet compact and token-driven in the same shape.

Available classes: `.site-header` `.brand` `nav` `.hero` `.lede` `.small`
`.panel` `.grid` (`.grid.two`) `.card` `.price` `.term` `.list` (`li > .note`)
`.badge` `.btn` (`.btn.ghost`) `.field` `.site-footer`.

Tokens in `:root`: `--ink` `--muted` `--paper` `--wash` `--accent`
`--accent-ink` `--line` `--hero-bg` `--hero-ink` `--gap` `--radius`
`--measure` `--font`.

Restyling is a token edit, not a rewrite. "Make the hero darker" means
changing `--hero-bg` and `--hero-ink`, not writing new rules.

Only append to `styles.css` when a layout genuinely has no class for it. Never
rewrite it, and never create a second stylesheet.

## Scope

Keep it small. Unless the brief asks for more:

- One page: `index.html`.
- A hero plus **two or three** content sections. Not seven.
- No SVG illustrations, no decorative graphics, no icon sets. The type and the
  palette carry the design.

Additional pages, when asked, live at the root as `<slug>.html` and share the
same `<nav>`, with every link resolving to a file that exists.

## Write it once

Write each file in a single `write_file`. Do not re-read or revise a file you
just wrote unless `check_site` reports an **error** in it. The read-edit-read
loop is slow and almost never improves the page.

## Markup

- `<!doctype html>`, `<html lang="en">`, `<meta charset>`, viewport meta.
- Exactly one `<h1>`, a non-empty `<title>`.
- Real landmarks: `<header>`, `<nav>`, `<main>`, `<footer>`.
- Every `<img>` has meaningful `alt`; decorative images get `alt=""`.
- Form fields have a `name` and a `<label for>` pointing at their `id`.
- No inline `style="…"`, no `<style>` blocks. Everything in `styles.css`.
- Self-contained: no CDN links, no Google Fonts, no remote images.
- **Relative paths only** — `href="styles.css"`, `href="about.html"`. A
  leading slash breaks the live preview, which serves the site from a
  subpath.

## Copy

Write real copy for the business in front of you. Never `Lorem ipsum`, never
`[Your Business Name]`, never a `TODO` in shipped markup. If the brief leaves
a detail out, choose something plausible and move on.

Two or three sentences per section. Enough to read as finished, not enough to
need scrolling.

## Definition of done

Call `check_site` **once**. Fix every error it reports. Ignore warnings unless
the user asks about them — they are style notes, not defects.

Then give the user two or three sentences on what you built. Do not paste
markup into the chat; they are looking at the page.
