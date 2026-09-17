from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import os
import pathlib
import re
import math
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from typing import Any, Callable

import certifi

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000
DEFAULT_BUDGET = 1.0
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|20\d{2})\b")
MARKER_RE = re.compile(r"(?:\bTODO\b|\bFIXME\b|\[\?\]|<!--\s*unresolved\s*-->)", re.I)
WORD_RE = re.compile(r"[a-z][a-z0-9-]{2,}", re.I)
STOP = {"about", "after", "also", "been", "being", "between", "could", "from", "have", "into", "more", "only", "other", "should", "than", "that", "their", "there", "these", "this", "those", "through", "under", "using", "when", "where", "which", "while", "with", "would"}


@dataclass
class Page:
    path: str
    title: str
    aliases: list[str]
    up: str | None
    related: list[str]
    updated: str | None
    lines: list[tuple[int, str]]


@dataclass
class Question:
    id: str
    kind: str
    state: Any
    spec: dict[str, Any]
    path: str
    line: int
    quote: str
    other_path: str | None = None
    other_line: int | None = None
    other_quote: str | None = None


@dataclass
class Finding:
    kind: str
    path: str
    line: int
    quote: str
    why: str
    probability: float
    confidence: float | None
    other_path: str | None = None
    other_line: int | None = None
    other_quote: str | None = None


def parse_frontmatter(text: str) -> tuple[dict[str, Any], int]:
    if not text.startswith("---\n"):
        return {}, 0
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, 0
    data: dict[str, Any] = {}
    current: str | None = None
    for raw in text[4:end].splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("- ") and current:
            data.setdefault(current, []).append(stripped[2:].strip().strip('"\''))
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        current = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                data[current] = json.loads(value.replace("'", '"'))
            except json.JSONDecodeError:
                data[current] = [v.strip().strip('"\'') for v in value[1:-1].split(",") if v.strip()]
        elif value:
            data[current] = value.strip('"\'')
        else:
            data[current] = []
    return data, text[: end + 5].count("\n")


def visible_lines(text: str, offset: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    fenced = False
    for number, raw in enumerate(text.splitlines(), 1):
        if number <= offset:
            continue
        if raw.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced and raw.strip():
            out.append((number, raw.rstrip()))
    return out


def load_pages(vault: pathlib.Path) -> list[Page]:
    pages: list[Page] = []
    root = vault.resolve()
    scan_root = vault / "wiki" if (vault / "wiki").is_dir() and (vault / "index.md").is_file() else vault
    for path in sorted(scan_root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(vault).parts):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, offset = parse_frontmatter(text)
        aliases = fm.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        related = [m.group(1) for m in LINK_RE.finditer(str(fm.get("related", "")))]
        up_match = LINK_RE.search(str(fm.get("up", "")))
        pages.append(Page(
            path=str(path.relative_to(vault)),
            title=str(fm.get("title") or path.stem.replace("-", " ").title()),
            aliases=[str(a) for a in aliases],
            up=up_match.group(1) if up_match else None,
            related=related,
            updated=str(fm["updated"]) if fm.get("updated") else None,
            lines=visible_lines(text, offset),
        ))
    return pages


def claims(page: Page) -> list[tuple[int, str]]:
    return [(n, s) for n, s in page.lines if len(s.strip()) >= 28 and not s.lstrip().startswith(("#", ">")) and not LINK_RE.fullmatch(s.strip())][:10]


def words(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text) if w.lower() not in STOP}


def linked_names(page: Page) -> set[str]:
    names = set(page.related)
    if page.up:
        names.add(page.up)
    for _, line in page.lines:
        names.update(m.group(1) for m in LINK_RE.finditer(line))
    return {n.casefold() for n in names}


def build_questions(pages: list[Page]) -> list[Question]:
    questions: list[Question] = []
    for page in pages:
        page_claims = claims(page)
        for line, quote in page_claims:
            date = DATE_RE.search(quote)
            old_page = False
            if page.updated:
                try:
                    old_page = (dt.date.today() - dt.date.fromisoformat(page.updated[:10])).days > 180
                except ValueError:
                    pass
            if not date and not old_page:
                continue
            state = {"page": page.title, "updated": page.updated, "claim": quote, "today": dt.date.today().isoformat()}
            questions.append(Question(
                id=f"stale-{len(questions)}", kind="stale", state=state,
                spec={"type": "score", "instructions": "Is this dated claim likely stale as of `today`? Judge the claim, not merely the age of the page.", "criteria": ["Current or not time-sensitive", "May have changed and needs verification", "Clearly outdated or superseded"]},
                path=page.path, line=line, quote=quote,
            ))

    for i, a in enumerate(pages):
        a_claims = claims(a)
        if not a_claims:
            continue
        a_names = {pathlib.Path(a.path).stem.casefold(), a.title.casefold(), *(x.casefold() for x in a.aliases)}
        for b in pages[i + 1:]:
            b_claims = claims(b)
            if not b_claims:
                continue
            b_names = {pathlib.Path(b.path).stem.casefold(), b.title.casefold(), *(x.casefold() for x in b.aliases)}
            explicit = bool(linked_names(a) & b_names or linked_names(b) & a_names or (a.up and a.up == b.up))
            ranked: list[tuple[int, int, str, int, str]] = []
            for an, aq in a_claims:
                aw = words(aq)
                for bn, bq in b_claims:
                    overlap = len(aw & words(bq))
                    if (explicit and overlap >= 1) or overlap >= 6:
                        ranked.append((overlap, an, aq, bn, bq))
            for _, an, aq, bn, bq in sorted(ranked, reverse=True)[:1]:
                state = {"quote_a": aq, "quote_b": bq}
                questions.append(Question(
                    id=f"contradiction-{len(questions)}", kind="contradiction", state=state,
                    spec={"type": "noul", "instructions": "Do `quote_a` and `quote_b` make incompatible factual claims about the same thing?", "criteria": {"true": "Both cannot be true in the same scope and time", "false": "They agree, discuss different things, or can both be true"}},
                    path=a.path, line=an, quote=aq, other_path=b.path, other_line=bn, other_quote=bq,
                ))
    return questions


def deterministic_findings(pages: list[Page]) -> list[Finding]:
    bare_names: set[str] = set()
    qualified_names: set[str] = set()
    for p in pages:
        path = pathlib.PurePosixPath(p.path)
        qualified_names.add(str(path.with_suffix("")).casefold())
        bare_names.update({path.stem.casefold(), p.title.casefold(), *(a.casefold() for a in p.aliases)})
    findings: list[Finding] = []
    for page in pages:
        for line, text in page.lines:
            if MARKER_RE.search(text):
                findings.append(Finding("unresolved", page.path, line, text, "An unresolved marker remains in the page.", 1.0, 1.0))
            for link in LINK_RE.finditer(text):
                if link.start() and text[link.start() - 1] == "!":
                    continue
                target = link.group(1).removesuffix(".md").strip("/").casefold()
                exists = target in qualified_names if "/" in target else target in bare_names
                if not exists:
                    findings.append(Finding("missing-page", page.path, line, link.group(0), f"Target “{link.group(1)}” was not found among the scanned pages.", 1.0, 1.0))
    return findings


class JevClient:
    def __init__(self, cache_path: pathlib.Path):
        self.cache_path = cache_path
        try:
            self.cache = json.loads(cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            self.cache = {}
        self.lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    @staticmethod
    def key(state: Any, spec: dict[str, Any]) -> str:
        payload = {"state": state, "model": MODEL, "questions": {"check": spec}}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def has(self, state: Any, spec: dict[str, Any]) -> bool:
        return self.key(state, spec) in self.cache

    @staticmethod
    def api_key() -> str:
        if key := os.environ.get("TYPESAFE_API_KEY"):
            return key
        settings = pathlib.Path.home() / ".config/amp/settings.json"
        try:
            return json.loads(settings.read_text())["amp.mcpServers"]["jev"]["env"]["TYPESAFE_API_KEY"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("TYPESAFE_API_KEY is not set and was not found in Amp settings") from exc

    def ask(self, state: Any, spec: dict[str, Any]) -> dict[str, Any]:
        payload = {"state": state, "model": MODEL, "questions": {"check": spec}}
        key = self.key(state, spec)
        with self.lock:
            if key in self.cache:
                return self.cache[key]
        request = urllib.request.Request(API, json.dumps(payload).encode(), {
            "Authorization": f"Bearer {self.api_key()}", "Content-Type": "application/json"})
        context = ssl.create_default_context(cafile=certifi.where())
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=60, context=context) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 529) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"TypeSafe Jev returned HTTP {exc.code}") from exc
        answer = data["answers"]["check"]
        with self.lock:
            usage = data.get("usage", {})
            self.input_tokens += int(usage.get("input_tokens", 0))
            self.output_tokens += int(usage.get("output_tokens", 0))
            self.calls += 1
            self.cache[key] = answer
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.cache, indent=2, sort_keys=True))
            os.replace(temporary, self.cache_path)
        return answer


def estimate_cost(questions: list[Question]) -> tuple[int, float]:
    if not questions:
        return 0, 0.0
    chars = sum(len(json.dumps({"state": q.state, "question": q.spec})) for q in questions)
    tokens = max(1, chars // 4)
    return tokens, tokens * PRICE_PER_INPUT_TOKEN


def score_questions(questions: list[Question], ask: Callable[[Any, dict[str, Any]], dict[str, Any]]) -> list[Finding]:
    def one(q: Question) -> Finding | None:
        answer = ask(q.state, q.spec)
        if q.kind == "contradiction":
            probability = float(answer["noul"])
            if probability < 0.65:
                return None
            return Finding(q.kind, q.path, q.line, q.quote, "These exact quotes crossed the contradiction threshold; verify their scope and dates.", probability, answer.get("confidence"), q.other_path, q.other_line, q.other_quote)
        score = float(answer["score"])
        confidence = float(answer.get("confidence", 0.0))
        probabilities = answer.get("probabilities", {})
        if isinstance(probabilities, dict):
            probability = float(probabilities.get("2", 0.0))
        else:
            probability = float(probabilities[2]) if len(probabilities) > 2 else 0.0
        if score < 1.5 or confidence < 0.5:
            return None
        return Finding(q.kind, q.path, q.line, q.quote, "This exact dated claim crossed the stale threshold; verify it against a current source.", probability, confidence)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return [finding for finding in pool.map(one, questions) if finding]


def report_html(result: dict[str, Any]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for finding in result["findings"]:
        groups.setdefault(finding["path"], []).append(finding)
    cards = []
    labels = {"contradiction": "Possible contradiction", "stale": "Possibly stale claim", "unresolved": "Unresolved marker", "missing-page": "Missing page"}
    navigation = []
    for index, (path, findings) in enumerate(sorted(groups.items())):
        section_id = f"page-{index + 1}"
        navigation.append(f'<a href="#{section_id}">{html.escape(path)} <span>{len(findings)}</span></a>')
        items = []
        for f in findings:
            second = ""
            if f.get("other_quote"):
                second = f'<blockquote><b class="source-location">{html.escape(f["other_path"])}:{f["other_line"]}</b><span class="quote-text">{html.escape(f["other_quote"])}</span></blockquote>'
            conf = "—" if f["confidence"] is None else f'{f["confidence"]:.0%}'
            evidence = "Rule check" if f["kind"] in ("unresolved", "missing-page") else f'Jev probability {f["probability"]:.0%} · confidence {conf}'
            items.append(f'''<article class="finding"><div class="finding-head"><span class="kind">{labels[f["kind"]]}</span><span>{evidence}</span></div><blockquote><b class="source-location">line {f["line"]}</b><span class="quote-text">{html.escape(f["quote"])}</span></blockquote>{second}<p>{html.escape(f["why"])}</p></article>''')
        cards.append(f'<section class="page" id="{section_id}"><h2>{html.escape(path)}</h2>{"".join(items)}<a class="back" href="#pages">Back to pages</a></section>')
    if result["pages"] == 0:
        empty = '<section class="empty"><h2>No Markdown pages scanned</h2><p>Check the vault path and try again.</p></section>'
    else:
        empty = '<section class="empty"><h2>No findings in the checks performed</h2><p>No configured rule or semantic threshold fired.</p></section>' if not cards else ""
    nav = f'<nav id="pages" aria-label="Pages with findings"><h2>Pages with findings</h2>{"".join(navigation)}</nav>' if navigation else ""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>jev-lint report</title><style>
:root{{--paper:#f2ecdf;--ink:#1d211d;--muted:#5e6059;--line:#c9c1b2;--accent:#b64028;--card:#faf6ed}}@media(prefers-color-scheme:dark){{:root{{--paper:#171a17;--ink:#f2ecdf;--muted:#aaa99f;--line:#42463f;--accent:#f17b5f;--card:#20241f}}}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Georgia,serif;line-height:1.55}}::selection{{background:var(--accent);color:var(--paper)}}a{{color:var(--accent);text-underline-offset:3px}}a:focus-visible{{outline:3px solid var(--accent);outline-offset:4px}}main{{width:min(920px,calc(100% - 32px));margin:auto;padding:72px 0}}header{{border-bottom:1px solid var(--line);padding-bottom:32px;margin-bottom:40px}}.eyebrow,.kind,.meta,.finding-head,nav{{font-family:ui-monospace,monospace}}.eyebrow{{color:var(--accent);font-weight:600}}h1{{font-size:clamp(3rem,10vw,6rem);line-height:.9;letter-spacing:-.04em;margin:.2em 0}}.meta{{color:var(--muted);display:flex;gap:18px;flex-wrap:wrap}}.coverage{{max-width:72ch;color:var(--muted);margin-top:20px}}nav{{border-bottom:1px solid var(--line);padding-bottom:32px}}nav a{{display:flex;justify-content:space-between;gap:16px;padding:8px 0}}.page{{margin:54px 0}}h2{{font-size:1.35rem;border-bottom:1px solid var(--line);padding-bottom:10px;overflow-wrap:anywhere}}.finding{{background:var(--card);border:1px solid var(--line);padding:20px;margin:14px 0;border-radius:3px}}.finding-head{{display:flex;justify-content:space-between;gap:16px;color:var(--muted);font-size:.82rem}}.kind{{color:var(--accent);font-weight:600;text-transform:uppercase;letter-spacing:.05em}}blockquote{{margin:18px 0;padding-left:18px;border-left:1px solid var(--accent)}}blockquote b{{display:block;color:var(--muted);font:600 .8rem ui-monospace,monospace;margin-bottom:6px}}.quote-text{{display:block;white-space:pre-wrap;overflow-wrap:anywhere}}.source-location{{overflow-wrap:anywhere}}p{{margin:10px 0 0}}.back{{display:inline-block;margin-top:10px}}footer{{color:var(--muted);border-top:1px solid var(--line);padding-top:24px;margin-top:60px;font-size:.9rem}}@media(max-width:600px){{main{{padding:40px 0}}.finding-head{{display:block}}}}
</style></head><body><main><header><h1>jev-lint</h1><div class="meta"><span>{result["pages"]} pages</span><span>{result["questions"]} Jev questions</span><span>{len(result["findings"])} findings</span><span>{result["seconds"]:.1f}s</span><span>${result["cost"]:.4f} estimated input cost</span></div><p class="coverage">Jev is a second opinion, not a verdict. Semantic checks sample up to ten claims per page and one claim pair per related or high-overlap page pair. Verify every flag against its source.</p></header>{nav}{"".join(cards)}{empty}<footer>Generated {html.escape(result["generated_at"])} from Markdown files in the selected vault scope.</footer></main></body></html>'''


def run(vault: pathlib.Path, budget: float, dry_run: bool, ask: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None, cache_path: pathlib.Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    pages = load_pages(vault)
    questions = build_questions(pages)
    client = None
    billable = questions
    if ask is None and not dry_run:
        client = JevClient(cache_path or pathlib.Path.home() / ".cache/jev-lint/responses.json")
        billable = [q for q in questions if not client.has(q.state, q.spec)]
    estimated_tokens, estimated_cost = estimate_cost(billable)
    if estimated_cost > budget:
        raise RuntimeError(f"Estimated Jev cost ${estimated_cost:.4f} exceeds the ${budget:.2f} budget; raise --budget to continue")
    if dry_run:
        return {"pages": len(pages), "questions": len(questions), "estimated_tokens": estimated_tokens, "estimated_cost": estimated_cost, "dry_run": True}
    findings = deterministic_findings(pages)
    if questions:
        if ask is None:
            assert client is not None
            ask = client.ask
        findings.extend(score_questions(questions, ask))
    findings.sort(key=lambda f: (f.path, f.line, f.kind))
    result = {
        "pages": len(pages), "questions": len(questions), "findings": [asdict(f) for f in findings],
        "input_tokens": client.input_tokens if client else 0,
        "output_tokens": client.output_tokens if client else 0,
        "api_calls": client.calls if client else len(questions),
        "cost": (client.input_tokens * PRICE_PER_INPUT_TOKEN) if client else estimated_cost,
        "estimated_cost": estimated_cost,
        "seconds": time.monotonic() - started,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jev-lint", description="Find contradictions and decay in a Markdown knowledge base.")
    p.add_argument("vault_dir", type=pathlib.Path)
    p.add_argument("--budget", type=float, default=DEFAULT_BUDGET, metavar="USD")
    p.add_argument("--dry-run", action="store_true", help="show question count and estimated cost without calling Jev")
    p.add_argument("--json", action="store_true", help="print machine-readable JSON")
    p.add_argument("--open", action="store_true", dest="open_report", help="open report.html after the run")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    vault = args.vault_dir.expanduser().resolve()
    if not vault.is_dir():
        print(f"jev-lint: vault directory not found: {vault}", file=sys.stderr)
        return 2
    if not math.isfinite(args.budget) or args.budget < 0:
        print("jev-lint: --budget must be non-negative", file=sys.stderr)
        return 2
    try:
        result = run(vault, args.budget, args.dry_run)
    except RuntimeError as exc:
        print(f"jev-lint: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f'{result["pages"]} pages · {result["questions"]} Jev questions · estimated ${result["estimated_cost"]:.4f} ({result["estimated_tokens"]:,} input tokens)')
        return 0
    output = pathlib.Path.cwd() / "report.html"
    if output.is_symlink() or (output.exists() and 'name="generator" content="jev-lint"' not in output.read_text(encoding="utf-8", errors="ignore")[:500]):
        print(f"jev-lint: refusing to overwrite unrelated file: {output}", file=sys.stderr)
        return 2
    rendered = report_html(result).replace("<head>", '<head><meta name="generator" content="jev-lint">', 1)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, output)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f'{result["pages"]} pages · {result["questions"]} Jev questions · {len(result["findings"])} findings')
        for finding in result["findings"]:
            print(f'- {finding["kind"]}: {finding["path"]}:{finding["line"]} — {finding["why"]}')
        print(f'{result["seconds"]:.1f}s · {result["input_tokens"]:,} input tokens · ${result["cost"]:.4f} · {output}')
    if args.open_report:
        webbrowser.open(output.as_uri())
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
