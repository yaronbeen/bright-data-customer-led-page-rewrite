"""Acceptance tests for the approved customer-led page rewrite contract."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "demo.json"
MODULE = "customer_led_page_rewrite"


def analyze(input_path: Path, out_dir: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(ROOT), env.get("PYTHONPATH")])
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "analyze",
            str(input_path),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report_path = out_dir / "report.json"
    assert report_path.is_file(), "analyze must write report.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def source_fixture(tmp_path: Path, mutate) -> Path:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def topic_result(report: dict, topic_id: str) -> dict:
    topics = report["question_map"]
    if isinstance(topics, dict):
        return topics[topic_id]
    return next(topic for topic in topics if topic["topic_id"] == topic_id)


def faq_result(report: dict, topic_id: str) -> dict:
    return next(edit for edit in report["faq_edits"] if edit["topic_id"] == topic_id)


def test_positive_fixture_has_approved_draft_citations_and_two_headlines(tmp_path):
    report = analyze(FIXTURE, tmp_path / "out")

    assert len(report["headline_alternatives"]) == 2
    assert all(item["text"] for item in report["headline_alternatives"])
    assert all(
        "no browser extension is required" in item["text"].casefold()
        for item in report["headline_alternatives"]
    )
    setup = faq_result(report, "setup")
    assert setup["draft"] == "Start with a CSV file; no browser extension is required."
    assert setup["draft_state"] not in {"needs_approved_fact", "conflicting_approved_facts"}
    assert setup["audience_refs"]
    assert setup["fact_refs"]
    assert setup["before_refs"]


def test_match_any_is_not_an_exact_question_observation(tmp_path):
    path = source_fixture(
        tmp_path,
        lambda data: data["sources"].__setitem__(
            1,
            {
                **data["sources"][1],
                "text": "People ask how to get started.",
            },
        ),
    )
    report = analyze(path, tmp_path / "out")

    setup = topic_result(report, "setup")
    assert setup["question_origin"] == "operator_framed_from_observed_language"
    assert setup["audience_refs"]
    assert "What do I need to get started?" not in setup.get("verbatim_quotes", [])


def test_punctuation_inside_question_must_match_even_when_phrase_matches(tmp_path):
    path = source_fixture(
        tmp_path,
        lambda data: (
            data["topics"][0].update(question="What do I need to get started!"),
            data["topics"][0].update(match_any=["get started"]),
        ),
    )
    report = analyze(path, tmp_path / "out")
    setup = topic_result(report, "setup")

    assert setup["question_origin"] == "operator_framed_from_observed_language"
    assert setup["audience_refs"]


@pytest.mark.parametrize(
    "sentence,expected_origin,has_phrase_evidence",
    [
        (
            "  WHAT   DO I NEED TO GET STARTED?  ",
            "observed",
            True,
        ),
        (
            "I wondered: what do I need to get started?",
            "observed",
            True,
        ),
        (
            "The campaign started after launch.",
            "operator_inferred",
            False,
        ),
    ],
)
def test_question_origin_uses_full_normalized_question_and_boundaries(
    tmp_path, sentence, expected_origin, has_phrase_evidence
):
    path = source_fixture(
        tmp_path,
        lambda data: data["sources"].__setitem__(
            1, {**data["sources"][1], "text": sentence}
        ),
    )
    report = analyze(path, tmp_path / "out")
    setup = topic_result(report, "setup")

    assert setup["question_origin"] == expected_origin
    assert bool(setup["audience_refs"]) is has_phrase_evidence


@pytest.mark.parametrize("approval", ["unverified", "withdrawn"])
def test_unapproved_facts_never_enter_drafts_or_headlines(tmp_path, approval):
    path = source_fixture(
        tmp_path,
        lambda data: data["facts"][0].update(approval=approval),
    )
    report = analyze(path, tmp_path / "out")

    setup = faq_result(report, "setup")
    assert setup["draft"] is None
    assert setup["draft_state"] == "needs_approved_fact"
    serialized = json.dumps(report).casefold()
    assert "start with a csv file; no browser extension is required." not in serialized


def test_audience_claim_is_not_promoted_to_product_copy_and_missing_proof_is_visible(
    tmp_path,
):
    report = analyze(FIXTURE, tmp_path / "out")
    sales = faq_result(report, "sales")

    assert sales["draft"] is None
    assert sales["draft_state"] == "needs_approved_fact"
    assert sales["proof_needed"]
    for headline in report["headline_alternatives"]:
        assert "guarantee more sales" not in headline["text"].casefold()


def test_unknown_page_evidence_is_not_reported_as_no_matching_answer(tmp_path):
    path = source_fixture(
        tmp_path,
        lambda data: data["sources"].__setitem__(
            0, {**data["sources"][0], "text": None}
        ),
    )
    report = analyze(path, tmp_path / "out")
    setup = faq_result(report, "setup")

    assert setup["page_answer_state"] == "page_unavailable"
    assert setup["draft_state"] == "hold_for_page_review"


def test_identical_input_produces_byte_identical_artifacts(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    analyze(FIXTURE, first)
    analyze(FIXTURE, second)

    for name in ("report.json", "rewrite.md", "rewrite.csv"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
