# Review of jev-lint 0.1.0

Independent review of main at 932ab52, done on 2026-09-18. Line numbers below refer to `src/jev_lint/cli.py` on main unless stated. Every fix landed on the `review-fixes` branch with a test that fails on main; the offline suite ran after each commit. Evidence came from running the CLI against the brain snapshot (99 pages), a 2-page sample vault, two generated 2,020-page vaults, and the fixture, plus pipx and uv installs from a clean directory.

Counts: 5 high, 12 medium (11 fixed, M8 withdrawn), 9 low, 11 recorded but not fixed, 4 proposed fixes rejected. The oracle pass (bottom) added H6, M10–M12 and L8, downgraded H3 to L9, and overturned two of my fixes.

## High

### H1. Frontmatter list under a scalar key crashes the whole run
`cli.py:85-86`: `data.setdefault(current, []).append(...)` when `data[current]` is already a string (for example `tags: work` followed by `- home`). AttributeError, traceback, no report. Real Obsidian vaults contain this form. Fix: only append when the current value is a list. Test: `test_frontmatter_bullet_under_scalar_does_not_crash`.

### H2. Question building is quadratic in pages: 2,000 pages took 4 min 34 s in `--dry-run`
`cli.py:166-210`: for every page pair the loop recomputed `linked_names()`, `claims()` and `words()` of both pages, then sorted all overlaps. Measured 274 s on a generated 2,020-page vault. Fix: precompute per-page claims, word sets and link names once, resolve explicit links through a name-to-index map, keep the same pair order and `max()` instead of `sorted()[-1]`. Output verified identical on the brain snapshot (1,267 questions, same order and content). Now 15 s on the dense vault, 5 s on a realistic one.

### H3 → downgraded to L9. Build backend minimum cannot build the project
`pyproject.toml` on main declares `license = "MIT"` (PEP 639) with `requires = ["setuptools>=68"]`. setuptools 68 rejects the field (verified in a setuptools-68 venv). With isolated builds pip fetches the newest setuptools, so `pipx install git+…` normally succeeds; the failure only appears with `--no-build-isolation`, offline wheels, or a pinned setuptools. Fix: `setuptools>=77`, the first version that supports the field.

### H4. Rule findings carry `probability: 1.0` and `confidence: 1.0` in `--json`
`cli.py:224,231`: unresolved-marker and missing-page findings are constructed with `1.0, 1.0`. The README promises "Mechanical findings never receive model probabilities"; the HTML hides them but the JSON output and any downstream consumer see a Jev-looking probability that Jev never produced. Fix: `probability`/`confidence` are `None` for rule findings (`Finding.probability: float | None`). Tests: `test_finds_all_four_classes`, `test_report_labels_rule_and_jev_findings_differently`. Verified on the snapshot run: all 10 rule findings now carry `null`.

### H5. Network failures surface as tracebacks
`cli.py:275-284` catches only `HTTPError`. DNS failure, connection refused, TLS errors and read timeouts raise `URLError`/`TimeoutError` inside worker threads and print a multi-thread traceback. A response without `answers.check` raised `KeyError`. Fix: those become `RuntimeError` with one line; 401 gets a "check TYPESAFE_API_KEY" hint; retries cover 429, 529 and other 5xx. Tests: `test_retry_on_429_then_success`, `test_401_and_network_errors_become_clear_messages_without_the_key`.

### H6 (oracle). A key with whitespace is echoed by urllib
`http.client.putheader` raises `ValueError("Invalid header value 'Bearer …'")` when the key contains a newline or other control character, and nothing caught it: the full key went to the terminal in a traceback. A copied key with a trailing newline in Amp settings is a realistic mistake. Fix: both key sources are stripped; a key that is still not a printable ASCII token without spaces is rejected with a fixed message that never includes it. Test: `test_key_is_stripped_and_never_echoed`.

## Medium

### M1. Markers and wikilinks inside inline code are reported
`cli.py:221-231` scans raw visible lines. On the brain snapshot this produced 3 false positives: `graph-legibility.md:15` (`` `[[wikilinks]]` `` reported as a missing page) and two pages that document the `` `[?]` `` convention. Fix: strip inline code spans before the marker and link scan. Test: `test_markers_inside_inline_code_are_ignored`. Note: the README's recorded run (16 findings) was made with 0.1.0; the same vault now yields 13. The README says so rather than rewriting the recorded run.

### M2. Escaped-pipe aliases, folder paths and attachments resolve wrongly
`LINK_RE` (`cli.py:29`) captured `page\` as the target of `[[page\|alias]]` (the form Obsidian writes inside tables), so those links were reported as missing and did not count as links when nominating contradiction pairs. `[[folder/page]]` only matched a page whose full relative path was exactly that, whereas Obsidian's shortest-path setting resolves any trailing path segment. `[[diagram.png]]` was reported as a missing page (embeds `![[…]]` were skipped entirely, including embedded notes). Fix: regex accepts `\|`, qualified names include every folder suffix, links whose extension is one of Obsidian's accepted attachment formats are skipped, embedded notes are checked like links, `.md`/`.MD` is stripped case-insensitively after the attachment check so `[[missing.pdf.md]]` is a page. The rules are my reading of Obsidian's documented behaviour, checked against the test cases, not against Obsidian itself. Test: `test_wikilink_resolution`.

### M3. `--dry-run` ignored the cache and refused over-budget vaults
`cli.py:366-374`: the client (and thus the cache) was only constructed when not dry-running, so the estimate for an already-scored vault was the full price, and `--dry-run` raised the budget error instead of showing the estimate. A user with a 2,000-page vault could not see the cost that `--dry-run` exists to show. Fix: dry-run reads the cache, reports `cached_questions`, always prints the estimate, and exits 2 when the estimate exceeds the budget. Tests: `test_cache_hits_skip_network_and_budget`, `test_budget_estimate_excludes_cache_hits_only`, `test_cli_exit_codes_and_report`. Note: staleness questions embed the run date, so they miss the cache on a new day by design (194 of 1,267 on the snapshot); the README now says so.

### M4. Cache rewritten to disk after every API call
`cli.py:290-295` serialized the whole cache (indent=2, sorted) under the lock after each of the 1,267 responses. O(n²) disk writes; on a 58k-question vault that is gigabytes. Fix: mark dirty, write once in `run()`'s `finally` (also on Ctrl-C and errors), compact JSON. Test: `test_cache_hits_skip_network_and_budget` spies on `atomic_write` and asserts exactly one write for the whole run.

### M5. Report overwrite check runs after the money is spent
`cli.py:425-428` checked whether `report.html` is a foreign file only after `run()` finished. A user with a hand-written `report.html` in the working directory paid for the run and got an error. Fix: check before `run()`, and again immediately before the write (oracle: a file can appear during a two-minute run). Test: `test_cli_exit_codes_and_report` patches `JevClient.ask` to fail if scoring starts, and has a fake client that creates the output file mid-run.

### M6. UTF-8 BOM and closing `---` at end of file break frontmatter
`cli.py:76-78`: `text.startswith("---\n")` fails with a BOM (files saved by Windows editors and some sync tools) and `text.find("\n---\n")` misses a file that is only frontmatter or ends with `---` without a trailing newline. Frontmatter then leaks into claims and the title/aliases are lost. Fix: read with `utf-8-sig`, accept `---` at EOF. Test: `test_frontmatter_without_trailing_newline_and_with_bom`.

### M7. `~~~` fences are not recognised
`cli.py:111` only toggles on backtick fences. Content inside tilde fences was sent to Jev and scanned for markers. Fix: treat `~~~` as a fence. Test: `test_line_numbers_skip_frontmatter_and_fences`.

### M8. No claim length limit — fix withdrawn
A single long paragraph (minified JSON, a pasted log) becomes one claim and is sent in full, repeated in every contradiction pair it takes part in. I capped claims at 2,000 characters; the oracle pointed out that truncation runs before `DATE_RE` and `words()`, so it can change which pairs are nominated and can cut a negation or qualifier out of the text Jev judges. Reverted. The budget estimate already bounds the cost; the limitation is recorded below.

### M9. No key → failure only inside the worker threads
The key was resolved lazily on the first `ask()`; with an empty cache the user saw the error after threads spun up and after `deterministic_findings` ran. Fix: `client.api_key` is checked before scoring when there is anything billable; the message names both sources (env and Amp settings) and never includes any key material. Test: `test_missing_key_fails_before_scoring` patches `JevClient.ask` to fail, proving scoring never starts.

### M10 (oracle). Malformed answers were cached and crashed later
`ask()` only required `answers.check` to exist. An answer like `{}` or `{"noul": "high"}` was cached, then raised `KeyError`/`ValueError` inside `score_questions` on this and every later run until the cache was deleted; a score answer without `probabilities` produced a finding with an invented probability of 0.0; `NaN` passed both thresholds. Fix: `answer_values()` reads exactly the fields the tool uses (noul; or score, confidence, probabilities["2"]), requires finite numbers, and runs before caching. Test: `test_malformed_answers_are_errors_and_never_cached` (5 shapes).

### M11 (oracle). `~~~` fix let a tilde line close a backtick fence
My first fence fix toggled on either marker, so `~~~` inside a ```` ``` ```` block ended the block and the rest of the code became claim text. Main did not have this bug. Fix: `visible_lines` records the opening run (character and length) and closes only on a run of the same character at least as long, which also handles ```` ```` ```` fences that contain ```` ``` ````. Inline spans now match any backtick run (```` ``x`` ````) and are masked with spaces instead of removed, so `TO`x`DO` no longer collapses into a marker and link positions stay aligned with the original line. Tests: `test_line_numbers_skip_frontmatter_and_fences`, `test_markers_inside_inline_code_are_ignored`, `test_wikilink_resolution` line 8.

### M12 (oracle). Empty frontmatter swallowed the body
`---\n---\n` has its closing delimiter at index 3, but the search started at 4, so the next horizontal rule in the body was taken as the end of frontmatter and everything before it vanished from linting. Fix: search from 3. Test: `test_empty_frontmatter_does_not_swallow_body`.

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

### L8 (oracle). `-o some-directory` and other preflight I/O errors printed tracebacks
The overwrite guard ran outside the `try` that maps `OSError` to exit 2, and read the whole existing file to check 500 bytes. Fix: `main()` wraps the whole CLI body (`lint()`) in one error boundary; the guard reads only 500 characters; report and cache go through `atomic_write()` (`tempfile.mkstemp` in the target directory, so a stale or symlinked `.tmp` is never truncated). Test: `test_cli_exit_codes_and_report` (`-o <dir>` exits 2 with "Is a directory").

### L7. README copy
"configured threshold" replaced by the actual numbers (contradiction ≥ 0.65; stale score ≥ 1.5 on the 0–2 legend with confidence ≥ 0.5, verified against the TypeSafe score-answer docs where legend keys are 0-based). Cache path documented. `Page.path` now uses POSIX separators so `--json` paths are stable on Windows.

## Verified and left as is

- Symlink escape: `load_pages` skips symlinks and anything whose resolved path leaves the resolved vault (`cli.py:132-137`). Test: `test_symlinks_and_hidden_dirs_are_not_scanned`.
- Atomic report write via temp file and `os.replace`; the overwrite guard uses the generator meta tag. Kept.
- `Executor.map` cancels queued futures when the consumer stops iterating after an observed exception, so a failing question does not run the rest of the vault first. I initially added `shutdown(cancel_futures=True)`; `test_failure_cancels_queued_questions` passed on main without it, so the change was dropped. The oracle notes the remaining gap (see Recorded 8).
- Numeric claims in README and PRODUCT.md match `vault-run-final.json` (99 pages, 1,267 questions, 579,006 tokens, $0.0243, 113.9 s, 2 contradiction, 1 stale, 1 missing-page, 12 unresolved). A rerun on 2026-09-18 with this branch and the owner's cache gave 10 unresolved, 1 stale (0.89/0.79 instead of 0.91/0.83, re-asked because the date changed), and 3 contradictions: the two recorded pairs at 0.83 and 0.68 (recorded 0.84 and 0.71, so the cache holds a later run than the recorded one) plus `wiki/decisions/2026-09-amp-agent-routing.md:18` at exactly 0.65. Jev answers vary by a few hundredths between runs; the README now says a pair near the threshold can flip.
- Budget math: the estimate uses ⅔ token per serialized character, which overestimated the reference run by about 1.4× (measured 579,006 tokens for 1,267 questions). Conservative by design; left as is.

## Recorded, not fixed

1. **Site copy mismatch (`site/index.html`, out of scope for this branch).** The terminal mock names `wiki/decisions/agent-routing.md:18`, which does not exist in `vault-run-final.json`, and `network-guard.md:14`, whose real path is `wiki/decisions/2026-08-watchdog-network-guard.md:14`. The 91 % Amsterdam/Frankfurt example matches `fixture-run.json`. Another thread owns `site/` today.
2. **Line-fragment claims.** Claims are single visible lines of at least 28 characters, so a sentence wrapped across lines is sent to Jev as fragments and the report quotes fragments. Product decision; changing it changes every recorded number.
3. **Frontmatter `up`/`related` links are not checked for missing pages**, only body wikilinks are. Cheap to add but changes the recorded finding count; left for the owner.
4. **No budget enforcement during the run.** The cap is a preflight estimate; if Jev's real token usage exceeds the estimate the run continues. The estimate is conservative (see above), so this is theoretical.
5. **Question count on `up`-structured vaults.** Pages that share a parent are all paired, so a vault of 2,000 pages under a handful of hubs produces 58k–111k questions (estimated $0.79–$1.45) and would take hours at the observed ~11 questions/s. `--dry-run` now shows this honestly; a per-page pair cap would be the fix.
6. **Windows path in the vault argument.** `pathlib` handles separators; not tested on Windows.
7. **`[[Next.js]]`-style names** end in what looks like an attachment suffix (`.js` is not in the list, but `.md`-less names with dots are fine). Only the extensions in Obsidian's accepted-formats list are skipped (`.oga`/`.opus`, which are not on that list, were removed after the oracle pass).
8. **Fail-fast has a gap (oracle).** `Executor.map` yields in submission order: if question 0 is slow (up to the 60 s timeout) while question 1 fails, the other 7 workers keep issuing billable requests until question 0 returns. Ctrl-C during the submission phase also waits for queued work. Bounded by 8 in-flight requests per 60 s; the fix (`as_completed` with explicit cancellation) is more code than it saves at this scale.
9. **Very long lines** are sent to Jev in full (see M8). A 50 KB pasted line in ten pairs is about $0.02; the preflight estimate includes it.
10. **Duplicate concurrent misses (oracle).** Two workers can miss the same cache key at once and both pay for it. The preflight counts both, so the budget is not underestimated.
11. **Stale questions send the page title and `updated` value** with the claim. The README wording "only selected claim text" was corrected to say so.

## Rejected

- `pool.shutdown(cancel_futures=True)` in `score_questions`: redundant for the observed-exception case, `Executor.map`'s result iterator cancels the remaining futures in its `finally` when the consumer stops iterating. Verified by running `test_failure_cancels_queued_questions` against main's code. Dropped to keep the diff minimal; the residual gap is Recorded 8.
- Oracle: "confine the corrected `LINK_RE` to rule checks so pair nomination stays byte-compatible with main." Rejected. Main's regex captured `page\` for `[[page\|alias]]`, which is a parsing bug, not a nomination rule; the corrected target is what Obsidian links to. On the recorded vault the question list is identical either way (verified: 1,267 questions, same order and content), and keeping two link parsers would be the wrong abstraction.
- Oracle: rewrite `score_questions` around `as_completed` with explicit cancellation. Rejected as Recorded 8: bounded cost, more code.
- Oracle: coalesce duplicate in-flight cache misses. Rejected as Recorded 10.

## Oracle review

The oracle reviewed REVIEW.md, the diff against main, and the intended behaviour. It kept the question-building rewrite, null rule probabilities, cache-aware dry runs, budget-before-key ordering and end-of-run cache flushing. It added H6, M10, M11, M12 and L8 (all fixed above) and asked for the REVIEW corrections now applied: H3 downgraded and its evidence narrowed; M4/M5/M9 tests gained spies so a wrong ordering or per-answer writes fail them; M2's description of main corrected; the Obsidian-parity wording narrowed; the privacy sentence in the README corrected (Recorded 11). It overturned two fixes: the claim truncation (M8, reverted) and the boolean fence toggle (M11, replaced). Three suggestions were rejected with reasons above.
