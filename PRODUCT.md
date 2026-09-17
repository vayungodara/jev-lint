# jev-lint

jev-lint is an open-source command-line linter for personal Markdown knowledge bases, including ordinary Obsidian vaults and structured LLM wikis. It helps maintainers find contradictions, dated claims that may be stale, unresolved markers, and dangling wikilinks without sending the entire vault to a general-purpose model.

The primary user is a technically comfortable knowledge-base owner who wants an actionable maintenance report, predictable cost, and clear evidence for every flag. The CLI is the product. The generated HTML report is the review surface; the public website explains and installs it.

Trust is the central product requirement. Rule checks and Jev signals must be labeled differently, exact scored quotes must be shown, costs must be bounded before network calls, and the output must remind readers that semantic findings need human verification.
