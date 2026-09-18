# Changelog

## 0.1.1 (unreleased)

Review pass after the 0.1.0 launch. See `REVIEW.md` for the findings behind each change.

### Fixed

- Frontmatter with a `- item` list under a scalar key, a UTF-8 BOM, or a closing `---` on the last line no longer crashes or is skipped.
- `~~~` fences are treated like backtick fences.
- Markers (`TODO`, `[?]`, …) and wikilinks inside inline code are no longer reported. On the reference vault this removes 3 false positives (1 missing-page, 2 unresolved) from the 16 findings recorded in the README.
- Wikilinks with an escaped pipe (`[[page\|alias]]`), a folder prefix (`[[notes/page]]` resolves any suffix of the page path, like Obsidian), or an attachment suffix (`[[diagram.png]]`) resolve correctly.
- Rule findings (unresolved, missing-page) report `probability: null` in `--json` instead of `1.0`.
- Network errors, timeouts, and malformed API responses print one line instead of a traceback. Retries now cover 429, 529, and other 5xx responses.
- `--dry-run` counts cached questions, no longer refuses over-budget vaults, and exits 2 when the estimate exceeds the budget.
- The report-overwrite check runs before any API call. The cache is written once at the end of the run instead of after every response.
- Building a vault of 2,000 pages took minutes; it now takes seconds.

### Added

- `--output FILE` (`-o`), `--version`, documented exit codes, Ctrl-C exits 130.
- Claims are capped at 2,000 characters before they are sent to Jev.

## 0.1.0 (2026-09-17)

Initial release.
