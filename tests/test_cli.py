import json
import os
import pathlib

import pytest

from jev_lint.cli import JevClient, run

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "vault"


def fake_jev(state, spec):
    if spec["type"] == "noul":
        return {"noul": 0.97}
    return {"score": 2, "confidence": 0.94, "probabilities": {"0": 0.01, "1": 0.03, "2": 0.96}}


def test_finds_all_four_classes(tmp_path):
    result = run(FIXTURE, 1.0, False, ask=fake_jev)
    kinds = {finding["kind"] for finding in result["findings"]}
    assert {"contradiction", "stale", "unresolved", "missing-page"} <= kinds
    contradiction = next(f for f in result["findings"] if f["kind"] == "contradiction")
    assert contradiction["quote"] and contradiction["other_quote"]
    assert contradiction["probability"] == pytest.approx(0.97)
    stale = next(f for f in result["findings"] if f["kind"] == "stale")
    assert stale["probability"] == pytest.approx(0.96)


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


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")
def test_live_fixture_cost_under_two_cents(tmp_path):
    client = JevClient(tmp_path / "cache.json")
    result = run(FIXTURE, 0.02, False, ask=client.ask)
    result["cost"] = client.input_tokens * 0.042 / 1_000_000
    assert result["cost"] < 0.02
