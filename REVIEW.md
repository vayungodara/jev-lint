# Review of jev-lint 0.1.0

Independent review of main at 932ab52, done on 2026-09-18. Line numbers below refer to `src/jev_lint/cli.py` on main unless stated. Every fix landed on the `review-fixes` branch with a test that fails on main; the offline suite ran after each commit. Evidence came from running the CLI against the brain snapshot (99 pages), a 2-page sample vault, two generated 2,020-page vaults, and the fixture, plus pipx and uv installs from a clean directory.

Counts: 5 high, 9 medium, 6 low, 7 recorded but not fixed, 1 proposed fix rejected.

## High

### H1. Frontmatter list under a scalar key crashes the whole run
`cli.py:85-86`: `data.setdefault(current, []).append(...)` when `data[current]` is already a string (for example `tags: work` followed by `- home`). AttributeError, traceback, no report. Real Obsidian vaults contain this form. Fix: only append when the current value is a list. Test: `test_frontmatter_bullet_under_scalar_does_not_crash`.

### H2. Question building is quadratic in pages: 2,000 pages took 4 min 34 s in `--dry-run`
`cli.py:166-210`: for every page pair the loop recomputed `linked_names()`, `claims()` and `words()` of both pages, then sorted all overlaps. Measured 274 s on a generated 2,020-page vault. Fix: precompute per-page claims, word sets and link names once, resolve explicit links through a name-to-index map, keep the same pair order and `max()` instead of `sorted()[-1]`. Output verified identical on the brain snapshot (1,267 questions, same order and content). Now 15 s on the dense vault, 5 s on a realistic one.

### H3. `pip install` fails on setuptools older than 77
`pyproject.toml` on main declares `license = "MIT"` (PEP 639) with `requires = ["setuptools>=61"]`. setuptools 68 (Ubuntu 24.04 default) rejects the field: verified by building in a setuptools-68 venv. `pipx install git+…` on such a system fails with an opaque error. Fix: `setuptools>=77`.

### H4. Rule findings carry `probability: 1.0` and `confidence: 1.0` in `--json`
`cli.py:224,231`: unresolved-marker and missing-page findings are constructed with `1.0, 1.0`. The README promises "Mechanical findings never receive model probabilities"; the HTML hides them but the JSON output and any downstream consumer see a Jev-looking probability that Jev never produced. Fix: `probability`/`confidence` are `None` for rule findings (`Finding.probability: float | None`). Tests: `test_finds_all_four_classes`, `test_report_labels_rule_and_jev_findings_differently`.

### H5. Network failures surface as tracebacks
`cli.py:275-284` catches only `HTTPError`. DNS failure, connection refused, TLS errors and read timeouts raise `URLError`/`TimeoutError` inside worker threads and print a multi-thread traceback. A response without `answers.check` raised `KeyError`. Fix: those become `RuntimeError` with one line; 401 gets a "check TYPESAFE_API_KEY" hint; retries cover 429, 529 and other 5xx. Tests: `test_retry_on_429_then_success`, `test_401_and_network_errors_become_clear_messages_without_the_key`.

## Medium

### M1. Markers and wikilinks inside inline code are reported
`cli.py:221-231` scans raw visible lines. On the brain snapshot this produced 3 false positives: `graph-legibility.md:15` (`` `[[wikilinks]]` `` reported as a missing page) and two pages that document the `` `[?]` `` convention. Fix: strip inline code spans before the marker and link scan. Test: `test_markers_inside_inline_code_are_ignored`. Note: the README's recorded run (16 findings) was made with 0.1.0; the same vault now yields 13. The README says so rather than rewriting the recorded run.

### M2. Escaped-pipe aliases, folder paths and attachments resolve wrongly
`LINK_RE` (`cli.py:29`) does not accept `[[page\|alias]]` (the form Obsidian writes inside tables), so those links were never checked. `[[folder/page]]` only matched a page whose full relative path was exactly that, whereas Obsidian resolves any path suffix. `[[diagram.png]]` and `![[file.pdf]]` were reported as missing pages. Fix: regex accepts `\|`, qualified names include every folder suffix, links with an attachment suffix are skipped. Test: `test_wikilink_resolution`.

### M3. `--dry-run` ignored the cache and refused over-budget vaults
`cli.py:366-374`: the client (and thus the cache) was only constructed when not dry-running, so the estimate for an already-scored vault was the full price, and `--dry-run` raised the budget error instead of showing the estimate. A user with a 2,000-page vault could not see the cost that `--dry-run` exists to show. Fix: dry-run reads the cache, reports `cached_questions`, always prints the estimate, and exits 2 when the estimate exceeds the budget. Tests: `test_cache_hits_skip_network_and_budget`, `test_budget_estimate_excludes_cache_hits_only`, `test_cli_exit_codes_and_report`.

### M4. Cache rewritten to disk after every API call
`cli.py:290-295` serialized the whole cache (indent=2, sorted) under the lock after each of the 1,267 responses. O(n²) disk writes; on a 58k-question vault that is gigabytes. Fix: mark dirty, write once in `run()`'s `finally` (also on Ctrl-C and errors), compact JSON. Test: `test_cache_hits_skip_network_and_budget` (asserts a single write).

### M5. Report overwrite check runs after the money is spent
`cli.py:425-428` checked whether `report.html` is a foreign file only after `run()` finished. A user with a hand-written `report.html` in the working directory paid for the run and got an error. Fix: check before `run()`. Test: `test_cli_exit_codes_and_report` asserts the fake client is never called.

### M6. UTF-8 BOM and closing `---` at end of file break frontmatter
`cli.py:76-78`: `text.startswith("---\n")` fails with a BOM (files saved by Windows editors and some sync tools) and `text.find("\n---\n")` misses a file that is only frontmatter or ends with `---` without a trailing newline. Frontmatter then leaks into claims and the title/aliases are lost. Fix: read with `utf-8-sig`, accept `---` at EOF. Test: `test_frontmatter_without_trailing_newline_and_with_bom`.

### M7. `~~~` fences are not recognised
`cli.py:111` only toggles on backtick fences. Content inside tilde fences was sent to Jev and scanned for markers. Fix: treat `~~~` as a fence. Test: `test_line_numbers_skip_frontmatter_and_fences`.

### M8. No claim length limit
A single long paragraph (minified JSON, a pasted log) becomes one claim and is sent in full, repeated in every contradiction pair it takes part in. Fix: claims are capped at 2,000 characters. Test: `test_long_lines_are_truncated_before_scoring`.

### M9. No key → failure only inside the worker threads
The key was resolved lazily on the first `ask()`; with an empty cache the user saw the error after threads spun up and after `deterministic_findings` ran. Fix: `client.api_key` is checked before scoring when there is anything billable; the message names both sources (env and Amp settings) and never includes any key material. Test: `test_missing_key_fails_before_scoring`.

## Low

### L1. Report path is hard-wired to `./report.html`
Added `-o/--output FILE` (parent directory created). README updated.

### L2. No `--version`
Added; version is read from `jev_lint.__version__` and pyproject uses it dynamically.

### L3. Exit codes undocumented
Help text and README now state: 0 no findings, 1 findings, 2 error, 130 interrupted. Ctrl-C printed a traceback; it now prints "interrupted".

### L4. Empty or wrong directory produced an empty report and exit 0
A first-time user pointing at the wrong path saw "0 pages · 0 findings" and a report file. Now: "no Markdown pages found under …", exit 2, nothing written.

### L5. Tiny costs printed as `$0.0000 exceeds the $0.00 budget`
`--budget 0` on a small vault printed a contradiction. `usd()` shows six decimals below $0.00005.

### L6. Silent two-minute run
The reference run takes 114 s with no output. Now prints one stderr line with the billable question count and estimate before scoring, and a progress counter when stderr is a terminal.

### L7. README copy
"configured threshold" replaced by the actual numbers (contradiction ≥ 0.65; stale score ≥ 1.5 on the 0–2 legend with confidence ≥ 0.5, verified against the TypeSafe score-answer docs where legend keys are 0-based). Cache path documented. `Page.path` now uses POSIX separators so `--json` paths are stable on Windows.

## Verified and left as is

- Symlink escape: `load_pages` skips symlinks and anything whose resolved path leaves the resolved vault (`cli.py:132-137`). Test: `test_symlinks_and_hidden_dirs_are_not_scanned`.
- Atomic report write via temp file and `os.replace`; the overwrite guard uses the generator meta tag. Kept.
- `Executor.map` already cancels queued futures when iteration stops on the first exception, so a failing question does not run the rest of the vault first. I initially added `shutdown(cancel_futures=True)`; the test passed on main without it, so the change was dropped (see Rejected).
- Budget math: the estimate uses ⅔ token per serialized character, which overestimated the reference run by about 1.4× (measured 579,006 tokens for 1,267 questions). Conservative by design; left as is.
- Numeric claims in README and PRODUCT.md match `vault-run-final.json` (99 pages, 1,267 questions, 579,006 tokens, $0.0243, 113.9 s, 2 contradiction, 1 stale, 1 missing-page, 12 unresolved).

## Recorded, not fixed

1. **Site copy mismatch (`site/index.html`, out of scope for this branch).** The terminal mock names `wiki/decisions/agent-routing.md:18`, which does not exist in `vault-run-final.json`, and `network-guard.md:14`, whose real path is `wiki/decisions/2026-08-watchdog-network-guard.md:14`. The 91 % Amsterdam/Frankfurt example matches `fixture-run.json`. Another thread owns `site/` today.
2. **Line-fragment claims.** Claims are single visible lines of at least 28 characters, so a sentence wrapped across lines is sent to Jev as fragments and the report quotes fragments. Product decision; changing it changes every recorded number.
3. **Frontmatter `up`/`related` links are not checked for missing pages**, only body wikilinks are. Cheap to add but changes the recorded finding count; left for the owner.
4. **No budget enforcement during the run.** The cap is a preflight estimate; if Jev's real token usage exceeds the estimate the run continues. The estimate is conservative (see above), so this is theoretical.
5. **Question count on `up`-structured vaults.** Pages that share a parent are all paired, so a vault of 2,000 pages under a handful of hubs produces 58k–111k questions (estimated $0.79–$1.45) and would take hours at the observed ~11 questions/s. `--dry-run` now shows this honestly; a per-page pair cap would be the fix.
6. **Windows path in the vault argument.** `pathlib` handles separators; not tested on Windows.
7. **`[[Next.js]]`-style names** end in what looks like an attachment suffix (`.js` is not in the list, but `.md`-less names with dots are fine). Only Obsidian's documented attachment extensions are skipped.

## Rejected

- `pool.shutdown(cancel_futures=True)` in `score_questions`: redundant, `Executor.map`'s result iterator cancels the remaining futures in its `finally` when the consumer stops iterating. Verified by running `test_failure_cancels_queued_questions` against main's code. Dropped to keep the diff minimal.

## Oracle review

Pending; findings and rejections will be appended below.
