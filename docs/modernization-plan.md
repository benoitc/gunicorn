# Website Modernization Plan

## Goals
- Serve a single, canonical domain backed by a static MkDocs build.
- Keep the documentation authoring experience entirely in Markdown.
- Modernize the marketing home page with a refreshed visual identity.
- Preserve the generated settings reference sourced from Python code.

## Architecture Overview
- **Static site generator:** MkDocs with the Material theme.
- **Content layout:** Markdown files in `docs/content/`, grouped by guides, reference, and news archives.
- **Styling:** Lightweight CSS overrides in `docs/content/styles/overrides.css` for hero, feature cards, and color palette.
- **Dynamic data:** `docs/macros.py` exposes the Gunicorn version, while `scripts/build_settings_doc.py` renders the settings reference into Markdown during every build.
- **Assets:** SVG mascot and hero art live under `docs/content/assets/` so both the homepage and docs share the same branding.

## Completed Work
- Removed Sphinx configuration, themes, and the legacy static snapshot under `docs/site/`.
- Converted the entire content library (guides, FAQ, design notes, yearly news) from MyST/RST to MkDocs-friendly Markdown.
- Rebuilt the homepage using Material’s layout primitives with responsive hero, CTAs, and feature cards.
- Added CSS overrides that mirror Gunicorn’s brand colors and support light/dark modes.
- Replaced the Sphinx extension with a standalone Markdown generator for the settings reference.
- Introduced an automated MkDocs workflow (`.github/workflows/docs.yml`) that builds on every push and deploys to `gh-pages` from the `main` branch.

## Remaining Enhancements
1. **Visual polish:** produce updated screenshots/asciicasts for quickstart and deployment examples; add Open Graph imagery.
2. **Content review:** prune outdated news entries, tighten FAQs, and add framework-specific quickstarts (FastAPI, Flask, Django).
3. **Accessibility & internationalization:** run axe audits, ensure color contrast, and consider adding minimal localization support.
4. **Performance extras:** enable MkDocs search index minification and gzip the GitHub Pages output (served automatically once deployed).
5. **Contributor docs:** extend `CONTRIBUTING.md` with MkDocs authoring tips, link to preview artifacts, and describe the `mkdocs serve` workflow.

## Deployment Checklist
- [x] Update DNS to point away from ReadTheDocs once `gh-pages` is published.
- [x] Verify `site_url` in `mkdocs.yml` for canonical URLs and sitemap generation.
- [x] Ensure `CNAME` (if required) is checked into `gh-pages` during deployment.
- [ ] Announce the migration to end-users and update links in READMEs and PyPI metadata.
