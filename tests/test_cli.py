import datetime as dt
import io
import json
import os
import pathlib
import time
import urllib.error

import pytest

from jev_lint import cli
from jev_lint.cli import JevClient, build_questions, deterministic_findings, load_pages, main, parse_frontmatter, run

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "vault"
CLAIM = "The Atlas platform serves every API request from Frankfurt since the migration"


def fake_jev(state, spec):
    if spec["type"] == "noul":
        return {"noul": 0.97}
    return {"score": 2, "confidence": 0.94, "probabilities": {"0": 0.01, "1": 0.03, "2": 0.96}}


def write(vault, files):
    for name, text in files.items():
        path = vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return vault


def test_finds_all_four_classes(tmp_path):
    result = run(FIXTURE, 1.0, False, ask=fake_jev)
    kinds = {finding["kind"] for finding in result["findings"]}
    assert {"contradiction", "stale", "unresolved", "missing-page"} <= kinds
    contradiction = next(f for f in result["findings"] if f["kind"] == "contradiction")
    assert contradiction["quote"] and contradiction["other_quote"]
    assert contradiction["probability"] == pytest.approx(0.97)
    stale = next(f for f in result["findings"] if f["kind"] == "stale")
    assert stale["probability"] == pytest.approx(0.96)
    rule = next(f for f in result["findings"] if f["kind"] == "unresolved")
    assert rule["probability"] is None and rule["confidence"] is None, "rule checks must not carry model probabilities"


def test_dry_run_does_not_call_jev():
    def fail(*_):
        raise AssertionError("Jev called during dry run")

    result = run(FIXTURE, 1.0, True, ask=fail)
    assert result["questions"] >= 2
    assert result["estimated_cost"] < 0.02


def test_budget_refusal_happens_before_api_call():
    with pytest.raises(RuntimeError, match="exceeds"):
        run(FIXTURE, 0.0, False, ask=fake_jev)


def test_report_has_no_external_resources():
    from jev_lint.cli import report_html

    rendered = report_html({"pages": 0, "questions": 0, "findings": [], "seconds": 0, "cost": 0, "generated_at": "now"})
    assert "https://" not in rendered


# --- frontmatter and page loading -------------------------------------------------


def test_frontmatter_forms():
    text = '---\ntitle: "A: B"\nup: "[[moc]]"\nrelated: ["[[x]]", \'[[y]]\']\naliases:\n  - One\n  - "Two"\ntags: [wiki/concept]\nupdated: 2026-01-02\n---\n\nbody\n'
    data, offset = parse_frontmatter(text)
    assert data["title"] == "A: B"
    assert data["up"] == "[[moc]]"
    assert data["related"] == ["[[x]]", "[[y]]"]
    assert data["aliases"] == ["One", "Two"]
    assert data["updated"] == "2026-01-02"
    assert offset == 10  # opening ---, eight keys/items, closing ---


def test_frontmatter_without_trailing_newline_and_with_bom(tmp_path):
    write(tmp_path, {"eof.md": "---\ntitle: Foo\n---", "bom.md": b"\xef\xbb\xbf---\ntitle: Bar\n---\nbody\n"})
    pages = {p.path: p for p in load_pages(tmp_path)}
    assert pages["eof.md"].title == "Foo" and pages["eof.md"].lines == []
    assert pages["bom.md"].title == "Bar" and [l for _, l in pages["bom.md"].lines] == ["body"]


def test_frontmatter_bullet_under_scalar_does_not_crash():
    data, _ = parse_frontmatter("---\ntitle: Foo\ndescription: >\n  text\n  - not a list item\n---\n")
    assert data["title"] == "Foo" and data["description"] == ">"


def test_line_numbers_skip_frontmatter_and_fences(tmp_path):
    write(tmp_path, {"a.md": "---\nupdated: 2020-01-01\n---\n# H\n\n```\nTODO inside backtick fence is code\n```\n~~~\nTODO inside tilde fence is code\n~~~\nTODO real marker on line twelve\n````md\n~~~\nTODO: a tilde line does not close a backtick fence\n```\nTODO: three backticks do not close four\n````\nTODO real marker on line nineteen\n"})
    findings = deterministic_findings(load_pages(tmp_path))
    assert [(f.kind, f.line) for f in findings] == [("unresolved", 12), ("unresolved", 19)]


def test_fence_edge_cases_follow_commonmark(tmp_path):
    write(tmp_path, {"a.md": "```md\n    ```\nTODO still code: an indented closer does not close\n```\nTODO prose on line five\n```example```\nTODO prose on line seven, the line above is an inline span\n"})
    page = load_pages(tmp_path)[0]
    assert [n for n, _ in page.lines] == [5, 6, 7]
    assert [f.line for f in deterministic_findings([page])] == [5, 7]


def test_empty_frontmatter_does_not_swallow_body(tmp_path):
    write(tmp_path, {"a.md": "---\n---\nTODO first body line\n\n---\n\nafter a horizontal rule\n"})
    page = load_pages(tmp_path)[0]
    assert page.lines[0] == (3, "TODO first body line") and len(page.lines) == 3


def test_symlinks_and_hidden_dirs_are_not_scanned(tmp_path):
    outside = tmp_path / "outside"
    write(outside, {"secret.md": "SECRET-CONTENT TODO"})
    vault = write(tmp_path / "vault", {"a.md": "ok", ".obsidian/plugin.md": "TODO hidden", ".trash/old.md": "TODO trash"})
    (vault / "link.md").symlink_to(outside / "secret.md")
    (vault / "dir").symlink_to(outside)
    pages = load_pages(vault)
    assert [p.path for p in pages] == ["a.md"]


def test_page_paths_are_posix(tmp_path):
    write(tmp_path, {"sub/dir/x.md": "hi"})
    assert load_pages(tmp_path)[0].path == "sub/dir/x.md"


# --- wikilinks ---------------------------------------------------------------------


def test_wikilink_resolution(tmp_path):
    write(tmp_path, {
        "a.md": "\n".join([
            "[[b]] [[B]] [[b.md]] [[b|alias]] [[b#Heading]] [[b#^block]] [[b\\|table alias]]",  # 1: all resolve to b.md
            "[[My Note]] [[my note]] [[Alt Name]] [[Titled Page]]",  # 2: spaces, case, alias, frontmatter title
            "[[sub/c]] [[deep/sub/c]] [[c]]",  # 3: shortest-path folder links
            "![[diagram.png]] [[diagram.png]] [[paper.pdf]] [[#local heading]]",  # 4: attachments and self links
            "`[[in code]]` and TODO `[[also code]]` [[really missing]]",  # 5: only the last one is a page link
            "![[embedded-missing]] ![[b]]",  # 6: embedded notes are links too
            "[[Next.js]] [[b.MD]] [[missing.pdf.md]]",  # 7: dotted names; case-insensitive .md; a Markdown page named like a PDF
            "``[[double]]`` and ``TODO `x` ``",  # 8: double-backtick spans
        ]),
        "b.md": "x", "My Note.md": "x", "deep/sub/c.md": "x",
        "t.md": "---\ntitle: Titled Page\naliases: [Alt Name]\n---\nx",
    })
    findings = deterministic_findings(load_pages(tmp_path))
    assert [(f.kind, f.line, f.quote) for f in findings] == [
        ("unresolved", 5, "`[[in code]]` and TODO `[[also code]]` [[really missing]]"), ("missing-page", 5, "[[really missing]]"),
        ("missing-page", 6, "[[embedded-missing]]"),
        ("missing-page", 7, "[[Next.js]]"), ("missing-page", 7, "[[missing.pdf.md]]"),
    ]


def test_markers_inside_inline_code_are_ignored(tmp_path):
    write(tmp_path, {"a.md": "Pages keep their `[?]` marker until checked.\nStill open [?] here.\nTO`x`DO is not a marker.\n"})
    assert [f.line for f in deterministic_findings(load_pages(tmp_path))] == [2]


@pytest.mark.parametrize("line,masked", [
    ("``TODO`` and ``TODO `x` ``", True),  # double-backtick spans, one containing a single backtick
    ("``TODO [[missing]]`", False),  # unequal runs: not a span
    ("`before ```` TODO after`", True),  # one single-backtick span containing a four-backtick run
    ("\\`TODO [[missing]]`", False),  # escaped opener: not a span
    ("`a` TODO `b`", False),  # marker between two spans
])
def test_code_span_runs_must_match_exactly(tmp_path, line, masked):
    write(tmp_path, {"a.md": line + "\n"})
    assert (deterministic_findings(load_pages(tmp_path)) == []) is masked


# --- question construction ---------------------------------------------------------


def test_contradiction_candidates_need_links_or_six_shared_words(tmp_path):
    five = "alpha bravo charlie delta echo"
    write(tmp_path, {
        "p1.md": f"{five} foxtrot golf hotel india juliet kilo lima.",
        "p2.md": f"{five} mike november oscar papa quebec romeo sierra.",  # 5 shared words, unlinked
        "p3.md": f"{five} foxtrot tango uniform victor whiskey xray yankee.",  # 6 shared with p1, unlinked
        "p4.md": "See [[p2]] for the alpha details and nothing else here.",  # linked to p2, 1 shared word
    })
    questions = build_questions(load_pages(tmp_path))
    pairs = {(q.path, q.other_path) for q in questions if q.kind == "contradiction"}
    assert pairs == {("p1.md", "p3.md"), ("p2.md", "p4.md")}
    q = next(q for q in questions if q.path == "p1.md")
    assert q.spec["type"] == "noul" and q.state == {"quote_a": q.quote, "quote_b": q.other_quote}


def test_stale_candidates_from_dates_or_old_pages(tmp_path):
    today = dt.date.today()
    write(tmp_path, {
        "dated.md": "The service moved to Frankfurt on 2024-03-01 and stayed there.",
        "year.md": "Since 2023 the Atlas platform has served only European traffic.",
        "old.md": f"---\nupdated: {today - dt.timedelta(days=181)}\n---\nThe platform serves every request from Amsterdam today.",
        "edge.md": f"---\nupdated: {today - dt.timedelta(days=180)}\n---\nThe platform serves every request from Amsterdam today.",
        "fresh.md": "The platform serves every request from Amsterdam right now.",
    })
    questions = build_questions(load_pages(tmp_path))
    stale = {q.path for q in questions if q.kind == "stale"}
    assert stale == {"dated.md", "year.md", "old.md"}
    q = next(q for q in questions if q.path == "old.md")
    assert q.spec["type"] == "score" and len(q.spec["criteria"]) == 3
    assert q.state["today"] == today.isoformat() and q.state["claim"] == q.quote


# --- answer thresholds -------------------------------------------------------------


@pytest.mark.parametrize("answer,flagged", [
    ({"noul": 0.64}, False),
    ({"noul": 0.65}, True),
])
def test_contradiction_threshold(tmp_path, answer, flagged):
    write(tmp_path, {"a.md": "See [[b]]. Atlas serves every request from Amsterdam now.", "b.md": "Atlas serves every request from Frankfurt now."})
    result = run(tmp_path, 1.0, False, ask=lambda *_: answer)
    found = [f for f in result["findings"] if f["kind"] == "contradiction"]
    assert bool(found) is flagged
    if flagged:
        assert found[0]["probability"] == 0.65 and found[0]["confidence"] is None


@pytest.mark.parametrize("answer,flagged", [
    ({"score": 1.49, "confidence": 0.9, "probabilities": {"0": 0.0, "1": 0.51, "2": 0.49}}, False),
    ({"score": 1.6, "confidence": 0.49, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}}, False),
    ({"score": 1.5, "confidence": 0.5, "probabilities": {"0": 0.0, "1": 0.5, "2": 0.5}}, True),
])
def test_stale_threshold_needs_score_and_confidence(tmp_path, answer, flagged):
    write(tmp_path, {"a.md": "The service moved to Frankfurt on 2024-03-01 and stayed there.\n"})
    result = run(tmp_path, 1.0, False, ask=lambda *_: answer)
    found = [f for f in result["findings"] if f["kind"] == "stale"]
    assert bool(found) is flagged
    if flagged:
        assert found[0]["probability"] == answer["probabilities"]["2"] and found[0]["confidence"] == 0.5


# --- client: cache, budget, retries, key handling ----------------------------------


def fake_http(monkeypatch, responses):
    """Replace urlopen with a queue of responses; an int is an HTTP error code, an Exception is raised."""
    calls = []

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    def urlopen(request, timeout=None, context=None):
        calls.append(json.loads(request.data))
        assert request.get_header("Authorization").startswith("Bearer ")
        item = responses.pop(0)
        if isinstance(item, int):
            raise urllib.error.HTTPError(cli.API, item, "err", {}, io.BytesIO(b"{}"))
        if isinstance(item, Exception):
            raise item
        return Reply(json.dumps(item).encode())

    monkeypatch.setattr(cli.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cli.time, "sleep", lambda s: calls.append(("sleep", s)))
    return calls


def reply(answer, tokens=100):
    return {"answers": {"check": answer}, "usage": {"input_tokens": tokens, "output_tokens": 3}}


def test_retry_on_429_then_success(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    calls = fake_http(monkeypatch, [429, 529, 503, reply({"noul": 0.9})])
    client = JevClient(tmp_path / "cache.json")
    assert client.ask("s", {"type": "noul"}) == {"noul": 0.9}
    assert [c for c in calls if isinstance(c, tuple)] == [("sleep", 1), ("sleep", 2), ("sleep", 4)]
    assert client.input_tokens == 100 and client.calls == 1


def test_401_and_network_errors_become_clear_messages_without_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-secret-value")
    fake_http(monkeypatch, [401, urllib.error.URLError("name resolution failed")])
    client = JevClient(tmp_path / "cache.json")
    with pytest.raises(RuntimeError, match="HTTP 401") as info:
        client.ask("s", {"type": "noul"})
    assert "sk-secret-value" not in str(info.value)
    with pytest.raises(RuntimeError, match="could not reach"):
        client.ask("s", {"type": "noul"})


def test_missing_key_fails_before_scoring(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(cli.pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(cli.JevClient, "ask", lambda *a: pytest.fail("scoring started without a key"))
    monkeypatch.chdir(tmp_path)
    assert main([str(FIXTURE)]) == 2
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "report.html").exists()


def test_key_is_stripped_and_never_echoed(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", " sk-trailing-newline\n")
    assert JevClient(tmp_path / "c.json").api_key == "sk-trailing-newline"
    for bad in ("sk-a\nb", "sk-a\rb", "sk-a\x7fb", "sk-ключ", "sk-a b"):  # urllib echoes the header value for the first three
        monkeypatch.setenv("TYPESAFE_API_KEY", bad)
        with pytest.raises(RuntimeError) as info:
            JevClient(tmp_path / "c.json").api_key
        assert "sk-" not in str(info.value)
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    monkeypatch.setattr(cli.pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".config/amp").mkdir(parents=True)
    (tmp_path / ".config/amp/settings.json").write_text(json.dumps({"amp.mcpServers": {"jev": {"env": {"TYPESAFE_API_KEY": "from-settings "}}}}))
    assert JevClient(tmp_path / "c.json").api_key == "from-settings"


@pytest.mark.parametrize("answer", [{}, {"noul": "high"}, {"noul": float("nan")}, {"score": 2, "confidence": 0.9}, {"score": 2, "confidence": 0.9, "probabilities": [0.1, 0.1, 0.8]}])
def test_malformed_answers_are_errors_and_never_cached(tmp_path, monkeypatch, answer):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    spec = {"type": "noul"} if "noul" in answer or not answer else {"type": "score"}
    fake_http(monkeypatch, [reply(answer)])
    client = JevClient(tmp_path / "cache.json")
    with pytest.raises(RuntimeError, match="unexpected answer"):
        client.ask("s", spec)
    assert not client.has("s", spec) and not client.dirty


def test_cache_hits_skip_network_and_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    cache = tmp_path / "cache.json"
    n = run(FIXTURE, 1.0, True, cache_path=cache)["questions"]
    # Workers consume replies in arrival order, so every reply must satisfy either question type.
    fake_http(monkeypatch, [reply({"noul": 0.97, **fake_jev(None, {"type": "score"})}) for _ in range(n)])
    writes = []
    monkeypatch.setattr(cli, "atomic_write", lambda path, text: writes.append(path) or path.write_text(text))
    first = run(FIXTURE, 1.0, False, cache_path=cache)
    assert writes == [cache]  # once at the end, not after every answer
    assert first["api_calls"] == n and first["input_tokens"] == 100 * n
    assert first["cost"] == pytest.approx(100 * n * 0.042 / 1_000_000)
    assert json.loads(cache.read_text()) and len(json.loads(cache.read_text())) == n

    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network call on cache hit"))
    dry = run(FIXTURE, 0.0, True, cache_path=cache)
    assert dry["cached_questions"] == n and dry["estimated_cost"] == 0
    second = run(FIXTURE, 0.0, False, cache_path=cache)
    assert second["api_calls"] == 0 and second["cost"] == 0
    assert [f["kind"] for f in second["findings"]] == [f["kind"] for f in first["findings"]]


def test_budget_estimate_excludes_cache_hits_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    cache = tmp_path / "cache.json"
    questions = build_questions(load_pages(FIXTURE))
    client = JevClient(cache)
    client.cache[client.key(questions[0].state, questions[0].spec)] = {"noul": 0.1}
    client.dirty = True
    client.save()
    tokens, cost = cli.estimate_cost(questions[1:])
    assert run(FIXTURE, 1.0, True, cache_path=cache)["estimated_tokens"] == tokens
    with pytest.raises(RuntimeError, match="exceeds"):
        run(FIXTURE, cost * 0.99, False, cache_path=cache)


def test_failure_cancels_queued_questions(tmp_path):
    write(tmp_path, {f"p{i}.md": f"Claim number {i} was recorded on 2024-01-0{i % 9 + 1} for the record." for i in range(40)})
    calls = []

    def flaky(state, spec):
        calls.append(1)
        time.sleep(0.2)
        raise RuntimeError("boom")

    total = len(build_questions(load_pages(tmp_path)))
    assert total > 100
    with pytest.raises(RuntimeError, match="boom"):
        run(tmp_path, 1.0, False, ask=flaky)
    assert len(calls) < 40, "queued questions kept running after the first failure"


def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / "cache.json").write_text("[1, 2]")
    assert JevClient(tmp_path / "cache.json").cache == {}


# --- CLI surface -------------------------------------------------------------------


def test_cli_exit_codes_and_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setattr(cli.JevClient, "ask", lambda self, state, spec: fake_jev(state, spec))
    monkeypatch.setattr(cli.pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.chdir(tmp_path)
    assert main(["/nonexistent/vault"]) == 2
    assert main([str(FIXTURE), "--budget", "-1"]) == 2

    (tmp_path / "empty").mkdir()
    assert main([str(tmp_path / "empty")]) == 2
    assert "no Markdown pages" in capsys.readouterr().err
    assert not (tmp_path / "report.html").exists()

    (tmp_path / "mine.html").write_text("<p>hand written</p>")
    monkeypatch.setattr(cli.JevClient, "ask", lambda *a: pytest.fail("spent money before the overwrite check"))
    assert main([str(FIXTURE), "-o", "mine.html"]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert (tmp_path / "mine.html").read_text() == "<p>hand written</p>"
    assert main([str(FIXTURE), "-o", str(tmp_path)]) == 2  # a directory: exit 2, no traceback
    assert "Is a directory" in capsys.readouterr().err

    def appear_during_run(*a, **k):
        (tmp_path / "late.html").write_text("<p>appeared during the run</p>")
        return fake_jev(*a[1:], **k)
    monkeypatch.setattr(cli.JevClient, "ask", appear_during_run)
    assert main([str(FIXTURE), "-o", "late.html"]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert (tmp_path / "late.html").read_text() == "<p>appeared during the run</p>"
    assert not list(tmp_path.glob("*.tmp"))
    monkeypatch.setattr(cli.JevClient, "ask", lambda self, state, spec: fake_jev(state, spec))

    assert main([str(FIXTURE), "-o", "out/report.html", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["findings"] and (tmp_path / "out" / "report.html").exists()
    assert main([str(FIXTURE), "-o", "out/report.html"]) == 1, "own report must be overwritable"

    assert main([str(FIXTURE), "--dry-run", "--budget", "0"]) == 2
    assert "exceeds the $0.0000 budget" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0 and cli.__version__ in capsys.readouterr().out


def test_report_labels_rule_and_jev_findings_differently(tmp_path):
    result = run(FIXTURE, 1.0, False, ask=fake_jev)
    html = cli.report_html(result)
    assert html.count("Rule check") == sum(f["kind"] in ("unresolved", "missing-page") for f in result["findings"])
    assert "Jev probability 97%" in html and "confidence —" in html
    assert "Jev probability 96% · confidence 94%" in html


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")
def test_live_fixture_cost_under_two_cents(tmp_path):
    client = JevClient(tmp_path / "cache.json")
    result = run(FIXTURE, 0.02, False, ask=client.ask)
    result["cost"] = client.input_tokens * 0.042 / 1_000_000
    assert result["cost"] < 0.02
    contradiction = next(f for f in result["findings"] if f["kind"] == "contradiction")
    assert contradiction["confidence"] is None, "noul answers carry no confidence; do not invent one"


def test_atomic_write_failure_leaves_destination_and_no_temp(tmp_path, monkeypatch):
    target = tmp_path / "out.txt"
    target.write_text("old")
    monkeypatch.setattr(cli.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        cli.atomic_write(target, "new")
    assert target.read_text() == "old" and list(tmp_path.iterdir()) == [target]


def test_closed_stdout_exits_cleanly_without_traceback():
    import subprocess, sys as _sys
    for argv in (["--version"], [str(FIXTURE), "--dry-run"]):
        r, w = os.pipe()
        os.close(r)
        proc = subprocess.run([_sys.executable, "-m", "jev_lint.cli", *argv], stdout=w, stderr=subprocess.PIPE, text=True, env={**os.environ, "HOME": str(FIXTURE.parent)})
        os.close(w)
        assert proc.returncode in (0, 2) and "Traceback" not in proc.stderr and "Exception ignored" not in proc.stderr, (argv, proc.returncode, proc.stderr)


def test_usd_never_hides_a_nonzero_cost():
    assert cli.usd(0) == "$0.0000"
    assert cli.usd(0.024318) == "$0.0243"
    assert cli.usd(3.4356e-05) == "$0.000034"
