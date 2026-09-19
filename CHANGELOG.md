# Changelog

## 0.1.1 (unreleased)

Review pass after the 0.1.0 launch. See `REVIEW.md` for the findings behind each change.

### Fixed

- Frontmatter with a `- item` list under a scalar key, a UTF-8 BOM, or a closing `---` on the last line no longer crashes or is skipped.
- `~~~` fences are treated like backtick fences; a fence closes only on a run of the same character at least as long, so ```` ```` ```` blocks containing ``` ``` ``` work.
- Markers (`TODO`, `[?]`, …) and wikilinks inside inline code are no longer reported. Code spans follow CommonMark: backtick runs must match in length and an escaped backtick does not open a span. Lines indented four spaces are never fences. On the reference vault this removes 3 false positives (1 missing-page, 2 unresolved) from the 16 findings recorded in the README.
- Wikilinks with an escaped pipe (`[[page\|alias]]`), a folder prefix (`[[notes/page]]` resolves any suffix of the page path, like Obsidian), or an attachment suffix (`[[diagram.png]]`) resolve correctly. Embedded notes (`![[note]]`) are checked like links; `[[page.MD]]` matches case-insensitively.
- Rule findings (unresolved, missing-page) report `probability: null` in `--json` instead of `1.0`.
- Network errors, timeouts, and malformed API responses print one line instead of a traceback, and a malformed answer is never cached. A key with surrounding whitespace is trimmed; a key containing spaces or control characters is rejected without echoing it. Retries now cover 429, 529, and other 5xx responses.
- `--dry-run` counts cached questions, no longer refuses over-budget vaults, and exits 2 when the estimate exceeds the budget.
- The report-overwrite check runs before any API call and again just before writing; report and cache are written through unique temporary files. `--output` pointing at a directory is a clean error, and a closed stdout pipe exits 2 without a traceback. Empty frontmatter (`---` directly followed by `---`) no longer swallows the body up to the next horizontal rule. The cache is written once at the end of the run instead of after every response.
- Building a vault of 2,000 pages took minutes; it now takes seconds.

### Added

- A start line on stderr with the question count and estimate, and a progress counter on a terminal, so a two-minute run is no longer silent.
- `--output FILE` (`-o`), `--version`, documented exit codes, Ctrl-C exits 130. A directory with no Markdown pages is an error (exit 2) instead of an empty report.

## 0.1.0 (2026-09-17)

Initial release.
