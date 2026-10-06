"""PR01-PR10 and applicable common C01-C20 contract coverage."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from customer_led_page_rewrite import InputError
from customer_led_page_rewrite.brightdata import (
    MAX_BYTES,
    BrightDataError,
    HttpResponse,
    TransportError,
    _manifest_hash,
    collect,
    normalize_export,
    validate_live_plan,
    resume,
)
from customer_led_page_rewrite.cli import main
from customer_led_page_rewrite.core import analyze


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures" / "demo.json"
NOW = "2026-10-05T00:00:00Z"
EXPIRY = "2035-01-01T00:00:00Z"
WEB_URL = "https://www.brightdata.com/"
VIDEO_URL = "https://www.youtube.com/watch?v=abcdefghijk"
AMAZON_URL = "https://www.amazon.com/dp/B000000001"


def fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def web_manifest(extra_job: dict | None = None) -> dict:
    jobs = [
        {
            "id": "landing",
            "kind": "web_page",
            "role": "landing_page",
            "source_id": "live_landing",
            "url": WEB_URL,
        }
    ]
    if extra_job:
        jobs.append(extra_job)
    return {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": jobs}


def youtube_job() -> dict:
    return {
        "id": "comments",
        "kind": "youtube_comments",
        "role": "audience_language",
        "source_prefix": "yt",
        "urls": [VIDEO_URL],
        "num_of_comments": 1,
    }


def amazon_job(*, count: int = 1) -> dict:
    return {
        "id": "reviews",
        "kind": "amazon_reviews",
        "role": "audience_language",
        "source_prefix": "amz",
        "urls": [AMAZON_URL],
        "max_reviews": count,
    }


def approval(subject: dict, urls: list[str], *, requests=1, retained=5) -> dict:
    return {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "manifest_sha256": _manifest_hash(subject),
        "expires_at": EXPIRY,
        "max_requests": requests,
        "max_retained_records": retained,
        "approved_urls": urls,
        "account_budget_confirmed": True,
        "target_permissions_confirmed": True,
        "remote_resolution_risk_accepted": True,
    }


def test_demo_uses_only_final_schema_fields():
    data = fixture()
    assert data["schema_version"] == "1.0"
    assert data["project"] == "customer-led-page-rewrite"
    for source in data["sources"]:
        assert "observed_at" in source
        assert "retrieved_at" not in source
        assert {
            "status",
            "record_id",
            "record_id_origin",
        } <= source.keys()


def test_missing_shared_envelope_is_rejected_without_legacy_bypass():
    data = fixture()
    del data["schema_version"]
    del data["project"]
    with pytest.raises(InputError, match="required"):
        analyze(data)


def test_pr02_exact_approved_answer_suppresses_only_setup_faq():
    data = fixture()
    data["sources"][0]["text"] = (
        "## Setup\nStart with a CSV file; no browser extension is required."
        "\n\n## Results\nDesigned for small teams."
    )
    report = analyze(data)
    assert [row["topic_id"] for row in report["faqs"]] == ["sales"]
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    assert setup["page_answer_state"] == "approved_answer_present"
    assert setup["page_answer_refs"][0]["quote"] == (
        "Start with a CSV file; no browser extension is required."
    )


def test_pr03_related_phrase_is_not_an_approved_answer():
    data = fixture()
    data["sources"][0]["text"] = (
        "## Setup\nGet started with Harbor."
        "\n\n## Results\nDesigned for small teams."
    )
    report = analyze(data)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    assert setup["page_answer_state"] == "related_copy_only"
    assert setup["draft"] == "Start with a CSV file; no browser extension is required."


def test_pr05_global_claim_key_conflict_blocks_even_unreferenced_fact():
    data = fixture()
    data["sources"].append(
        {
            "id": "fact_note_2",
            "role": "approved_product_fact",
            "url": None,
            "kind": "operator_note",
            "title": "Second approved fact",
            "text": "Use the setup wizard.",
            "status": "collected",
            "observed_at": NOW,
            "published_at": None,
            "provider_date": None,
            "record_id": None,
            "record_id_origin": "none",
            "provenance": "synthetic_fixture",
        }
    )
    data["facts"].append(
        {
            "id": "f2",
            "topic_id": "setup",
            "claim_key": "setup_requirements",
            "text": "Use the setup wizard.",
            "approval": "approved",
            "evidence": [
                {
                    "source_id": "fact_note_2",
                    "block_id": "b0001",
                    "quote": "Use the setup wizard.",
                }
            ],
        }
    )
    report = analyze(data)
    setup = next(row for row in report["faqs"] if row["topic_id"] == "setup")
    assert setup["draft"] is None
    assert setup["draft_state"] == "conflicting_approved_facts"
    assert all(item["text"] is None for item in report["headlines"])


def test_approved_fact_citation_requires_exact_case_punctuation_and_qualifiers():
    data = fixture()
    data["facts"][0]["evidence"][0]["quote"] = (
        "start with a csv file; no browser extension is required."
    )
    data["sources"][-1]["text"] = data["facts"][0]["evidence"][0]["quote"]
    with pytest.raises(InputError, match="complete matching citation"):
        analyze(data)


def test_fact_citation_rejects_undocumented_excerpt_id_alias():
    data = fixture()
    citation = data["facts"][0]["evidence"][0]
    citation["excerpt_id"] = citation.pop("block_id")
    with pytest.raises(InputError, match="unknown keys"):
        analyze(data)


def test_page_answer_never_joins_fact_text_across_blocks():
    data = fixture()
    data["sources"][0]["text"] = (
        "## Setup\nStart with a\n\nCSV file; no browser extension is required."
        "\n\n## Results\nDesigned for small teams."
    )
    report = analyze(data)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    assert setup["page_answer_state"] != "approved_answer_present"
    assert setup["page_answer_refs"] == []


def test_c06_heading_only_fact_text_is_not_answer_evidence():
    data = fixture()
    data["sources"][0]["text"] = (
        "## Start with a CSV file; no browser extension is required.\n"
        "\n## Setup\nBring your existing work into Harbor."
        "\n\n## Results\nDesigned for small teams."
    )
    data["topics"][0]["target_heading"] = "Start with a CSV file; no browser extension is required."
    report = analyze(data)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    assert setup["page_answer_state"] == "no_matching_answer_in_selected_section"
    assert setup["page_answer_refs"] == []


def test_page_phrase_and_answer_citations_point_to_actual_hit_blocks():
    data = fixture()
    data["sources"][0]["text"] = (
        "## Setup\nUnrelated first block.\n\nGet started with Harbor."
        "\n\nStart with a CSV file; no browser extension is required."
        "\n\n## Results\nDesigned for small teams."
    )
    report = analyze(data)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    assert setup["page_answer_state"] == "approved_answer_present"
    assert setup["page_answer_refs"] == [
        {
            "source_id": "landing",
            "block_id": "b0004",
            "quote": "Start with a CSV file; no browser extension is required.",
        }
    ]


def test_page_evidence_offsets_survive_casefold_expansion_and_whitespace_collapse():
    data = fixture()
    fact = "Straße setup is supported."
    data["facts"][0]["text"] = fact
    data["sources"][-1]["text"] = fact
    data["facts"][0]["evidence"][0]["quote"] = fact
    data["sources"][0]["text"] = (
        "## Setup\nPrefix Straße   setup is supported."
        "\n\n## Results\nDesigned for small teams."
    )
    report = analyze(data)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    citation = setup["page_answer_refs"][0]
    assert citation["quote"] == "Prefix Straße setup is supported."
    assert fact in citation["quote"]


def test_long_page_hit_citation_keeps_entire_fact_within_240_char_limit():
    data = fixture()
    fact = "A" * 240
    data["facts"][0]["text"] = fact
    data["sources"][-1]["text"] = fact
    data["facts"][0]["evidence"][0]["quote"] = fact
    data["sources"][0]["text"] = (
        "## Setup\n" + ("context " * 15) + fact + "\n\n## Results\nDesigned for small teams."
    )
    report = analyze(data)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    quote = setup["page_answer_refs"][0]["quote"]
    assert len(quote) <= 240
    assert fact in quote


def test_pr08_missing_heading_proposes_section_and_duplicate_heading_holds():
    missing = fixture()
    missing["topics"][0]["target_heading"] = "Getting Started"
    report = analyze(missing)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    assert setup["section_action"] == "propose_new_section"
    assert setup["page_answer_state"] == "no_matching_answer_in_selected_section"

    duplicate = fixture()
    duplicate["sources"][0]["text"] += "\n\n## Setup\nDuplicate."
    report = analyze(duplicate)
    setup = next(row for row in report["question_map"] if row["topic_id"] == "setup")
    assert setup["page_answer_state"] == "needs_review"
    assert setup["draft_state"] == "hold_for_page_review"


def test_pr09_no_collected_audience_is_no_data_but_unavailable_is_needs_review():
    no_sources = fixture()
    no_sources["sources"] = [
        source for source in no_sources["sources"] if source["role"] != "audience_language"
    ]
    report = analyze(no_sources)
    assert report["decision"] == "no_audience_evidence"
    assert report["status"] == "no_data"
    assert report["faqs"] == []

    unavailable = fixture()
    for source in unavailable["sources"]:
        if source["role"] == "audience_language":
            source["status"] = "unavailable"
            source["text"] = ""
    report = analyze(unavailable)
    assert report["decision"] == "no_audience_evidence"
    assert report["status"] == "needs_review"


def test_role_count_limits_are_enforced():
    data = fixture()
    template = data["sources"][-1]
    for index in range(10):
        source = copy.deepcopy(template)
        source["id"] = f"fact_extra_{index}"
        data["sources"].append(source)
    with pytest.raises(InputError, match="approved_product_fact"):
        analyze(data)


def test_staleness_boundary_is_exactly_more_than_30_days():
    data = fixture()
    data["as_of"] = "2026-11-03T10:00:00Z"
    report = analyze(data)
    assert not any(warning["code"] == "stale_source" for warning in report["warnings"])

    data["as_of"] = "2026-11-03T10:00:01Z"
    report = analyze(data)
    assert any(warning["code"] == "stale_source" for warning in report["warnings"])


def test_source_library_schema_and_duplicate_ids_fail_before_report_write(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(fixture()))
    invalid = tmp_path / "library.json"
    invalid.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "project": "other-project",
                "transport_contract_version": "1.0",
                "sources": [],
                "receipt": {},
            }
        )
    )
    out = tmp_path / "out"
    assert main(["analyze", str(input_path), "--out-dir", str(out), "--sources", str(invalid)]) == 2
    assert not out.exists()

    malformed_input = tmp_path / "malformed-input.json"
    malformed_input.write_text(json.dumps({"sources": ["not an object"]}))
    valid_empty_library = normalize_export(
        "youtube_comments",
        [],
        role="audience_language",
        source_url=VIDEO_URL,
        observed_at=NOW,
        source_prefix="empty",
    )
    valid_library_path = tmp_path / "valid-library.json"
    valid_library_path.write_text(json.dumps(valid_empty_library))
    assert main(["analyze", str(malformed_input), "--out-dir", str(out), "--sources", str(valid_library_path)]) == 2
    assert not out.exists()

    duplicate = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "transport_contract_version": "1.0",
        "sources": [fixture()["sources"][0]],
        "receipt": {
            "schema_version": "1.0",
            "project": "customer-led-page-rewrite",
            "manifest_sha256": None,
            "status": "complete",
            "requests_made": 0,
            "returned_records": 1,
            "retained_records": 1,
            "excluded_records": 0,
            "jobs": [],
            "warnings": [],
            "provider_cost_usd": None,
        },
    }
    invalid.write_text(json.dumps(duplicate))
    assert main(["analyze", str(input_path), "--out-dir", str(out), "--sources", str(invalid)]) == 2
    assert not out.exists()

    malformed = copy.deepcopy(duplicate)
    malformed["receipt"]["manifest_sha256"] = "not-a-hash"
    malformed["receipt"]["jobs"] = [{"unexpected": "field"}]
    invalid.write_text(json.dumps(malformed))
    assert main(["analyze", str(input_path), "--out-dir", str(out), "--sources", str(invalid)]) == 2
    assert not out.exists()

    no_jobs = copy.deepcopy(duplicate)
    no_jobs["sources"] = []
    no_jobs["receipt"]["returned_records"] = 0
    no_jobs["receipt"]["retained_records"] = 0
    no_jobs["receipt"]["jobs"] = []
    invalid.write_text(json.dumps(no_jobs))
    assert main(["analyze", str(input_path), "--out-dir", str(out), "--sources", str(invalid)]) == 2
    assert not out.exists()


def test_generated_provider_import_library_validates_and_merges_explicitly(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(fixture()))
    library = normalize_export(
        "youtube_comments",
        [{"url": VIDEO_URL, "comment_id": "C3", "comment_text": "Can I export?"}],
        role="audience_language",
        source_url=VIDEO_URL,
        observed_at=NOW,
        source_prefix="import",
    )
    library_path = tmp_path / "library.json"
    library_path.write_text(json.dumps(library))
    out = tmp_path / "out"
    assert main(["analyze", str(input_path), "--out-dir", str(out), "--sources", str(library_path), "--dry-run"]) == 0
    assert not out.exists()


def test_pending_or_empty_attached_library_cannot_yield_no_data_report(tmp_path):
    data = fixture()
    data["sources"] = [source for source in data["sources"] if source["role"] != "audience_language"]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(data))
    manifest = {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": [youtube_job()]}
    library = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(202, {}, b'{"snapshot_id":"snap_123"}'),
        now=NOW,
        ledger_path=tmp_path / "pending-ledger",
    )
    library_path = tmp_path / "pending-library.json"
    library_path.write_text(json.dumps(library))
    out = tmp_path / "report"
    assert main(["analyze", str(input_path), "--out-dir", str(out), "--sources", str(library_path)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["decision"] == "no_audience_evidence"
    assert report["status"] == "needs_review"
    assert any(warning["code"] == "collection_needs_review" for warning in report["warnings"])
    assert "collection\\_needs\\_review" in (out / "rewrite.md").read_text()


def test_fake_collector_library_validates_and_merges_explicitly(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(fixture()))
    manifest = {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": [youtube_job()]}
    library = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(
            200,
            {},
            json.dumps([{"url": VIDEO_URL, "comment_id": "C4", "comment_text": "A comment?"}]).encode(),
        ),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    library_path = tmp_path / "collected-library.json"
    library_path.write_text(json.dumps(library))
    assert main(
        ["analyze", str(input_path), "--out-dir", str(tmp_path / "out"), "--sources", str(library_path), "--dry-run"]
    ) == 0

def test_cli_existing_output_is_rejected_before_transport_or_approval_consumption(
    tmp_path, monkeypatch
):
    manifest = web_manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(approval(manifest, [WEB_URL], retained=1)))
    output = tmp_path / "library.json"
    output.write_text("preserve")
    calls = []
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fake")
    monkeypatch.setenv("BRIGHT_DATA_WEB_UNLOCKER_ZONE", "zone")
    monkeypatch.setattr(
        "customer_led_page_rewrite.cli.urllib_transport",
        lambda request: calls.append(request),
    )
    code = main(
        [
            "collect",
            str(manifest_path),
            "--out",
            str(output),
            "--live",
            "--accept-charges",
            "--approval",
            str(approval_path),
        ]
    )
    assert code == 2
    assert calls == []
    assert output.read_text() == "preserve"
    assert not Path(str(approval_path) + ".ledger").exists()


def test_cli_unwritable_output_preflight_precedes_live_transport(tmp_path, monkeypatch):
    manifest = web_manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(approval(manifest, [WEB_URL], retained=1)))
    output = tmp_path / "library.json"
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fake")
    monkeypatch.setenv("BRIGHT_DATA_WEB_UNLOCKER_ZONE", "zone")
    monkeypatch.setattr(
        "customer_led_page_rewrite.cli.tempfile.NamedTemporaryFile",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("private path")),
    )
    calls = []
    monkeypatch.setattr(
        "customer_led_page_rewrite.cli.urllib_transport",
        lambda request: calls.append(request),
    )
    assert main(
        [
            "collect",
            str(manifest_path),
            "--out",
            str(output),
            "--live",
            "--accept-charges",
            "--approval",
            str(approval_path),
        ]
    ) == 2
    assert calls == []
    assert not Path(str(approval_path) + ".ledger").exists()


@pytest.mark.parametrize("status", [401, 403])
def test_provider_http_failures_return_failed_receipt_stop_once_and_hide_body(
    tmp_path, status
):
    manifest = web_manifest(youtube_job())
    attestation = approval(
        manifest, [WEB_URL, VIDEO_URL], requests=2, retained=2
    )
    calls = []

    def transport(request):
        calls.append(request)
        return HttpResponse(status, {"Retry-After": "9"}, b"private provider detail")

    result = collect(
        manifest,
        approval=attestation,
        api_key="fake-token",
        zones={"web_unlocker": "zone"},
        transport=transport,
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert result["receipt"]["requests_made"] == 1
    assert result["receipt"]["jobs"][0]["state"] == "failed"
    assert result["receipt"]["jobs"][1]["state"] == "not_attempted"
    assert len(calls) == 1
    assert "private provider detail" not in json.dumps(result)
    assert "fake-token" not in json.dumps(result)


def test_parse_failure_after_completed_job_returns_partial_with_not_attempted(tmp_path):
    second = youtube_job()
    third = {
        "id": "reviews",
        "kind": "amazon_reviews",
        "role": "audience_language",
        "source_prefix": "reviews",
        "urls": ["https://www.amazon.com/dp/B0CHHSFMRL"],
        "max_reviews": 1,
    }
    manifest = web_manifest(second)
    manifest["jobs"].append(third)
    attestation = approval(
        manifest,
        [WEB_URL, VIDEO_URL, third["urls"][0]],
        requests=3,
        retained=3,
    )
    responses = [
        HttpResponse(200, {}, b"# Page\n\nBody."),
        HttpResponse(200, {}, b"not-json"),
    ]

    result = collect(
        manifest,
        approval=attestation,
        api_key="fake",
        zones={"web_unlocker": "zone"},
        transport=lambda request: responses.pop(0),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "partial"
    assert result["receipt"]["requests_made"] == 2
    assert [job["state"] for job in result["receipt"]["jobs"]] == [
        "complete",
        "failed",
        "not_attempted",
    ]
    assert result["receipt"]["jobs"][1]["error_code"] == "invalid_response"
    assert len(result["sources"]) == 1


def test_provider_error_record_stops_later_jobs_and_is_failed_or_partial(tmp_path):
    third = {
        "id": "reviews",
        "kind": "amazon_reviews",
        "role": "audience_language",
        "source_prefix": "reviews",
        "urls": ["https://www.amazon.com/dp/B0CHHSFMRL"],
        "max_reviews": 1,
    }
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [youtube_job(), third],
    }
    attestation = approval(
        manifest, [VIDEO_URL, third["urls"][0]], requests=2, retained=2
    )
    calls = []

    def transport(request):
        calls.append(request)
        return HttpResponse(200, {}, b'[{"error_code":"unknown-secret-code"}]')

    result = collect(
        manifest,
        approval=attestation,
        api_key="fake",
        zones={},
        transport=transport,
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert [job["state"] for job in result["receipt"]["jobs"]] == [
        "failed",
        "not_attempted",
    ]
    assert result["receipt"]["jobs"][0]["error_code"] == "record_error"
    assert len(calls) == 1
    assert "unknown-secret-code" not in json.dumps(result)


def test_response_overflow_is_failed_receipt_not_positive_evidence(tmp_path):
    manifest = web_manifest()
    result = collect(
        manifest,
        approval=approval(manifest, [WEB_URL], retained=1),
        api_key="fake",
        zones={"web_unlocker": "zone"},
        transport=lambda request: HttpResponse(200, {}, b"x" * (MAX_BYTES + 1)),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert result["sources"] == []
    assert result["receipt"]["jobs"][0]["error_code"] == "response_too_large"


def test_production_transport_stream_deadline_is_monotonic_and_bounded(monkeypatch):
    from customer_led_page_rewrite import brightdata

    clock = [0.0]
    timeouts = []

    class Socket:
        def settimeout(self, value):
            timeouts.append(value)

    class Stream:
        def __init__(self):
            self.fp = type("FilePointer", (), {})()
            self.fp.raw = type("Raw", (), {})()
            self.fp.raw._sock = Socket()
            self.read_count = 0

        def read(self, _size):
            self.read_count += 1
            clock[0] += 0.4
            return b"x"

    monkeypatch.setattr(brightdata.time, "monotonic", lambda: clock[0])
    with pytest.raises(TransportError, match="transport_error"):
        brightdata._read_bounded(Stream(), deadline=1.0)
    assert timeouts[0] == 1.0
    assert timeouts[1] == pytest.approx(0.6)
    assert timeouts[2] == pytest.approx(0.2)


def test_known_response_overflow_transport_error_is_failed_not_unknown(tmp_path):
    manifest = web_manifest(youtube_job())
    result = collect(
        manifest,
        approval=approval(manifest, [WEB_URL, VIDEO_URL], requests=2, retained=2),
        api_key="fake",
        zones={"web_unlocker": "zone"},
        transport=lambda request: (_ for _ in ()).throw(TransportError("response_too_large")),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert result["receipt"]["jobs"][0]["error_code"] == "response_too_large"
    assert result["receipt"]["jobs"][1]["state"] == "not_attempted"


def test_invalid_pending_snapshot_becomes_partial_receipt_and_marks_rest_not_attempted(tmp_path):
    first = youtube_job()
    second = {
        "id": "reviews",
        "kind": "amazon_reviews",
        "role": "audience_language",
        "source_prefix": "reviews",
        "urls": ["https://www.amazon.com/dp/B0CHHSFMRL"],
        "max_reviews": 1,
    }
    manifest = {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": [first, second]}
    result = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL, second["urls"][0]], requests=2, retained=2),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(202, {}, b'{"snapshot_id":"bad/id"}'),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert [job["state"] for job in result["receipt"]["jobs"]] == ["failed", "not_attempted"]


def test_duplicate_live_page_source_ids_are_rejected_before_request():
    manifest = web_manifest()
    manifest["jobs"].append(
        {
            "id": "second_page",
            "kind": "web_page",
            "role": "landing_page",
            "source_id": "live_landing",
            "url": "https://www.brightdata.com/other",
        }
    )
    with pytest.raises(BrightDataError, match="duplicate_source_id"):
        validate_live_plan(manifest)


def valid_pending_receipt() -> dict:
    job = amazon_job()
    safe_job = job
    approved_hash = hashlib.sha256(AMAZON_URL.encode()).hexdigest()
    return {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "transport_contract_version": "1.0",
        "sources": [],
        "receipt": {
            "schema_version": "1.0",
            "project": "customer-led-page-rewrite",
            "manifest_sha256": "0" * 64,
            "status": "pending",
            "requests_made": 1,
            "returned_records": 0,
            "retained_records": 0,
            "excluded_records": 0,
            "jobs": [
                {
                    "id": "comments",
                    "kind": "amazon_reviews",
                    "state": "pending",
                    "original_job": safe_job,
                    "approved_url_sha256": [approved_hash],
                    "approved_url_binding_sha256": [hashlib.sha256(f"{AMAZON_URL}\0{approved_hash}".encode()).hexdigest()],
                    "requested_records": 1,
                    "returned_records": 0,
                    "retained_records": 0,
                    "excluded_records": 0,
                    "snapshot_id": "snap_123",
                    "error_code": "pending_snapshot",
                    "query_metadata": None,
                }
            ],
            "warnings": [],
            "provider_cost_usd": None,
        },
    }


def test_resume_rejects_unknown_receipt_keys_before_request(tmp_path):
    receipt = valid_pending_receipt()
    receipt["unexpected"] = True
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    calls = []
    with pytest.raises(BrightDataError, match="invalid_receipt"):
        resume(
            receipt,
            approval=approval(receipt, [download], retained=1),
            api_key="fake",
            transport=lambda request: calls.append(request),
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert calls == []


def test_resume_checks_provider_error_headers_before_treating_202_as_pending(tmp_path):
    receipt = valid_pending_receipt()
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    with pytest.raises(BrightDataError) as caught:
        resume(
            receipt,
            approval=approval(receipt, [download], retained=1),
            api_key="fake",
            transport=lambda request: HttpResponse(
                202, {"X-Brd-Error-Code": "private-provider-detail"}, b"{}"
            ),
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert caught.value.code == "provider_target_error"
    assert "private-provider-detail" not in str(caught.value)


@pytest.mark.parametrize("failure", ["http", "json", "dto"])
def test_resume_provider_failures_carry_safe_failed_receipt_and_one_call(tmp_path, failure):
    receipt = valid_pending_receipt()
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    calls = []

    def transport(request):
        calls.append(request)
        if failure == "http":
            return HttpResponse(403, {}, b"private message")
        if failure == "json":
            return HttpResponse(200, {}, b"not-json")
        return None

    with pytest.raises(BrightDataError) as caught:
        resume(
            receipt,
            approval=approval(receipt, [download], retained=1),
            api_key="fake-token",
            transport=transport,
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert len(calls) == 1
    assert caught.value.receipt["receipt"]["status"] == "failed"
    assert caught.value.receipt["receipt"]["jobs"][0]["state"] == "failed"
    serialized = json.dumps(caught.value.receipt)
    assert "private message" not in serialized
    assert "fake-token" not in serialized


def test_resume_rejects_malformed_retained_source_before_network(tmp_path):
    receipt = valid_pending_receipt()
    receipt["sources"] = [{"id": "not-a-source"}]
    receipt["receipt"]["retained_records"] = 1
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    calls = []
    with pytest.raises(BrightDataError, match="invalid_receipt"):
        resume(
            receipt,
            approval=approval(receipt, [download], retained=2),
            api_key="fake",
            transport=lambda request: calls.append(request),
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert calls == []


def test_resume_preserves_prior_completed_jobs_sources_and_aggregate_counts(tmp_path):
    amazon = amazon_job()
    manifest = web_manifest(amazon)
    initial = collect(
        manifest,
        approval=approval(manifest, [WEB_URL, AMAZON_URL], requests=2, retained=2),
        api_key="fake",
        zones={"web_unlocker": "zone"},
        transport=lambda request: HttpResponse(
            200 if request.url == "https://api.brightdata.com/request" else 202,
            {},
            b"# Landing\n\nPage body."
            if request.url == "https://api.brightdata.com/request"
            else b'{"snapshot_id":"snap_123"}',
        ),
        now=NOW,
        ledger_path=tmp_path / "collect-ledger",
    )
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    resumed = resume(
        initial,
        approval=approval(initial, [download], requests=1, retained=2),
        api_key="fake",
        transport=lambda request: HttpResponse(
            200,
            {},
            json.dumps([{"url": AMAZON_URL, "review_id": "R1", "review_text": "Review?"}]).encode(),
        ),
        now=NOW,
        ledger_path=tmp_path / "resume-ledger",
    )
    assert [job["state"] for job in resumed["receipt"]["jobs"]] == ["complete", "complete"]
    assert resumed["receipt"]["requests_made"] == 3
    assert resumed["receipt"]["retained_records"] == 2
    assert len(resumed["sources"]) == 2
    assert resumed["receipt"]["jobs"][1]["approved_url_sha256"] == initial["receipt"]["jobs"][1]["approved_url_sha256"]


def test_resume_provider_error_record_marks_current_job_failed(tmp_path):
    receipt = valid_pending_receipt()
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    result = resume(
        receipt,
        approval=approval(receipt, [download], retained=1),
        api_key="fake",
        transport=lambda request: HttpResponse(200, {}, b'[{"error_code":"dead_page"}]'),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert result["receipt"]["jobs"][0]["state"] == "failed"
    assert result["receipt"]["jobs"][0]["error_code"] == "dead_page"


def test_completed_then_failure_receipt_keeps_exact_job_order_and_count(tmp_path):
    youtube = youtube_job()
    amazon = {
        "id": "reviews",
        "kind": "amazon_reviews",
        "role": "audience_language",
        "source_prefix": "reviews",
        "urls": ["https://www.amazon.com/dp/B0CHHSFMRL"],
        "max_reviews": 1,
    }
    manifest = {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": [youtube, amazon]}
    responses = [
        HttpResponse(200, {}, json.dumps([{"url": VIDEO_URL, "comment_id": "C1", "comment_text": "Question?"}]).encode()),
        HttpResponse(401, {}, b"secret body"),
    ]
    result = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL, amazon["urls"][0]], requests=2, retained=2),
        api_key="fake",
        zones={},
        transport=lambda request: responses.pop(0),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "partial"
    assert result["receipt"]["requests_made"] == 2
    assert result["receipt"]["retained_records"] == 1
    assert [job["state"] for job in result["receipt"]["jobs"]] == ["complete", "failed"]
    assert "secret body" not in json.dumps(result)


def test_module_entrypoint_help_and_version_are_offline():
    env = os.environ.copy()
    env.pop("BRIGHT_DATA_API_KEY", None)
    version = subprocess.run(
        [sys.executable, "-m", "customer_led_page_rewrite", "--version"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    help_result = subprocess.run(
        [sys.executable, "-m", "customer_led_page_rewrite", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert version.returncode == 0 and version.stdout.strip().endswith("0.1.0")
    assert help_result.returncode == 0
    assert "analyze" in help_result.stdout and "collect" in help_result.stdout


def test_dev_lock_and_portable_readme_are_present():
    lock = (ROOT / "requirements-dev.lock").read_text()
    assert "pytest==9.0.2" in lock
    assert "setuptools==81.0.0" in lock
    readme = (ROOT / "docs" / "technical-guide.md").read_text()
    quickstart = readme.split("## Offline Quickstart", 1)[1].split("##", 1)[0]
    assert "/home/yaron/projects" not in quickstart
    assert "Differentiation is scope, not superiority" in readme
    assert "private/collections/" in readme
    assert "private/approvals/" in readme


def test_c02_pure_analysis_never_uses_environment_or_socket(monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)
    monkeypatch.setattr(
        "socket.socket",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )
    report = analyze(fixture())
    assert report["decision"] == "annotated_rewrite"


def test_c03_analysis_is_independent_of_environment_and_wall_clock(monkeypatch):
    data = fixture()
    before = analyze(data)
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "different-secret")
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    after = analyze(data)
    assert json.dumps(before, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(after, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_c04_unknown_dangling_boolean_and_oversize_inputs_fail():
    unknown = fixture()
    unknown["unexpected"] = True
    with pytest.raises(InputError, match="unknown keys"):
        analyze(unknown)

    dangling = fixture()
    dangling["facts"][0]["evidence"][0]["block_id"] = "b9999"
    with pytest.raises(InputError, match="stale"):
        analyze(dangling)

    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "comments",
                "kind": "youtube_comments",
                "role": "audience_language",
                "source_prefix": "yt",
                "urls": [VIDEO_URL],
                "num_of_comments": True,
            }
        ],
    }
    with pytest.raises(BrightDataError, match="invalid_job"):
        validate_live_plan(manifest)

    oversized = fixture()
    oversized["padding"] = "x" * (2 * 1024 * 1024)
    with pytest.raises(InputError, match="2 MiB"):
        analyze(oversized)


def test_c07_provider_metadata_is_allowlisted_out_of_import():
    result = normalize_export(
        "youtube_comments",
        [
            {
                "url": VIDEO_URL,
                "comment_id": "C1",
                "comment_text": "Question?",
                "username": "private name",
                "profile_url": "https://example.com/person",
                "handle_md5": "private hash",
                "avatar": "https://example.com/avatar",
                "replies": [{"text": "private reply"}],
            }
        ],
        role="audience_language",
        source_url=VIDEO_URL,
        observed_at=NOW,
        source_prefix="yt",
    )
    serialized = json.dumps(result)
    for forbidden in ("private name", "profile_url", "private hash", "avatar", "private reply"):
        assert forbidden not in serialized


@pytest.mark.parametrize("missing", ["key", "zone", "approval"])
def test_c09_missing_live_gate_makes_zero_requests_and_does_not_consume(tmp_path, missing):
    manifest = web_manifest()
    attestation = approval(manifest, [WEB_URL], retained=1)
    if missing == "approval":
        attestation["manifest_sha256"] = "0" * 64
    calls = []
    with pytest.raises(BrightDataError):
        collect(
            manifest,
            approval=attestation,
            api_key="" if missing == "key" else "fake",
            zones={} if missing == "zone" else {"web_unlocker": "zone"},
            transport=lambda request: calls.append(request),
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert calls == []
    assert not (tmp_path / "ledger").exists()


def test_c10_live_dry_run_validates_but_never_calls_or_writes(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(web_manifest()))
    output = tmp_path / "library.json"
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fake")
    monkeypatch.setenv("BRIGHT_DATA_WEB_UNLOCKER_ZONE", "zone")
    monkeypatch.setattr(
        "customer_led_page_rewrite.cli.urllib_transport",
        lambda request: (_ for _ in ()).throw(AssertionError("dry-run called transport")),
    )
    assert main(["collect", str(manifest_path), "--out", str(output), "--live", "--dry-run"]) == 0
    assert not output.exists()


@pytest.mark.parametrize("failure", ["redirect", "ndjson", "timeout"])
def test_c12_redirect_ndjson_and_timeout_never_create_evidence(tmp_path, failure):
    manifest = web_manifest() if failure != "ndjson" else {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [youtube_job()],
    }
    urls = [WEB_URL] if failure != "ndjson" else [VIDEO_URL]

    def transport(request):
        if failure == "redirect":
            return HttpResponse(302, {"Location": "https://evil.example/"}, b"")
        if failure == "ndjson":
            return HttpResponse(200, {}, b'{"comment_id":"C1"}\n{"comment_id":"C2"}')
        raise TimeoutError("private timeout detail")

    result = collect(
        manifest,
        approval=approval(manifest, urls, retained=1),
        api_key="fake",
        zones={"web_unlocker": "zone"},
        transport=transport,
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["sources"] == []
    expected = "completion_unknown" if failure == "timeout" else "failed"
    assert result["receipt"]["status"] == expected


def test_c12_outer_200_embedded_429_is_not_positive_evidence(tmp_path):
    manifest = web_manifest()
    with pytest.raises(BrightDataError, match="rate_limited") as caught:
        collect(
            manifest,
            approval=approval(manifest, [WEB_URL], retained=1),
            api_key="fake",
            zones={"web_unlocker": "zone"},
            transport=lambda request: HttpResponse(
                200,
                {"X-Brd-Status-Code": "429", "X-Brd-Error": "private provider body"},
                b"not markdown",
            ),
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert caught.value.receipt["receipt"]["status"] == "failed"
    assert caught.value.receipt["sources"] == []
    assert caught.value.receipt["receipt"]["jobs"][0]["error_code"] == "rate_limited"
    assert "private provider body" not in json.dumps(caught.value.receipt)


def test_c15_resume_409_stays_pending_with_one_request(tmp_path):
    receipt = valid_pending_receipt()
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    calls = []

    def transport(request):
        calls.append(request)
        return HttpResponse(409, {}, b"{}")

    result = resume(
        receipt,
        approval=approval(receipt, [download], retained=1),
        api_key="fake",
        transport=transport,
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "pending"
    assert result["sources"] == []
    assert len(calls) == 1


def test_c16_zero_and_over_return_have_truthful_distinct_states(tmp_path):
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [youtube_job()],
    }
    empty = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(200, {}, b"[]"),
        now=NOW,
        ledger_path=tmp_path / "empty-ledger",
    )
    assert empty["receipt"]["status"] == "complete"
    assert empty["receipt"]["jobs"][0]["state"] == "empty"

    records = [
        {"url": VIDEO_URL, "comment_id": f"C{index}", "comment_text": f"Question {index}?"}
        for index in range(2)
    ]
    over = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(200, {}, json.dumps(records).encode()),
        now=NOW,
        ledger_path=tmp_path / "over-ledger",
    )
    assert over["receipt"]["status"] == "partial"
    assert over["receipt"]["retained_records"] == 1
    assert any(warning["code"] == "provider_limit_exceeded" for warning in over["receipt"]["warnings"])


def test_c16_ambiguous_missing_url_and_conflicting_duplicate_records_are_partial(tmp_path):
    second_url = "https://www.youtube.com/watch?v=zyxwvutsrq0"
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "comments",
                "kind": "youtube_comments",
                "role": "audience_language",
                "source_prefix": "yt",
                "urls": [VIDEO_URL, second_url],
                "num_of_comments": 1,
            }
        ],
    }
    ambiguous = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL, second_url], retained=2),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(200, {}, b'[{"comment_id":"C1","comment_text":"Question?"}]'),
        now=NOW,
        ledger_path=tmp_path / "ambiguous-ledger",
    )
    assert ambiguous["receipt"]["status"] == "partial"
    assert ambiguous["receipt"]["retained_records"] == 0
    assert ambiguous["receipt"]["excluded_records"] == 1
    assert ambiguous["receipt"]["warnings"][0]["code"] == "invalid_record"

    single = {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": [youtube_job()]}
    conflicting = [
        {"url": VIDEO_URL, "comment_id": "C1", "comment_text": "First wording."},
        {"url": VIDEO_URL, "comment_id": "C1", "comment_text": "Different wording."},
    ]
    result = collect(
        single,
        approval=approval(single, [VIDEO_URL], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(200, {}, json.dumps(conflicting).encode()),
        now=NOW,
        ledger_path=tmp_path / "conflict-ledger",
    )
    assert result["receipt"]["status"] == "partial"
    assert result["sources"] == []
    assert any(warning["code"] == "conflicting_record" for warning in result["receipt"]["warnings"])


def test_malformed_provider_error_code_is_safely_mapped_and_stops(tmp_path):
    later = {
        "id": "reviews",
        "kind": "amazon_reviews",
        "role": "audience_language",
        "source_prefix": "reviews",
        "urls": ["https://www.amazon.com/dp/B0CHHSFMRL"],
        "max_reviews": 1,
    }
    manifest = {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": [youtube_job(), later]}
    records = [{"error_code": ["not", "hashable"], "comment_text": "ignored"}]
    result = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL, later["urls"][0]], requests=2, retained=2),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(200, {}, json.dumps(records).encode()),
        now=NOW,
        ledger_path=tmp_path / "malformed-code-ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert result["receipt"]["jobs"][0]["error_code"] == "record_error"
    assert result["receipt"]["jobs"][1]["state"] == "not_attempted"


def test_provider_boolean_record_id_is_excluded_not_stringified(tmp_path):
    manifest = {"schema_version": "1.0", "project": "customer-led-page-rewrite", "jobs": [youtube_job()]}
    result = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(
            200,
            {},
            b'[{"url":"https://www.youtube.com/watch?v=abcdefghijk","comment_id":true,"comment_text":"Question?"}]',
        ),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["sources"] == []
    assert result["receipt"]["status"] == "partial"
    assert result["receipt"]["excluded_records"] == 1


def test_web_page_import_enforces_shared_page_character_limit():
    with pytest.raises(BrightDataError, match="text_too_long"):
        normalize_export(
            "web_page",
            "x" * 50001,
            role="landing_page",
            source_url=WEB_URL,
            observed_at=NOW,
            source_prefix="web",
        )


def test_live_web_page_enforces_shared_page_character_limit(tmp_path):
    manifest = web_manifest()
    result = collect(
        manifest,
        approval=approval(manifest, [WEB_URL], retained=1),
        api_key="fake",
        zones={"web_unlocker": "zone"},
        transport=lambda request: HttpResponse(200, {}, ("x" * 50001).encode()),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["receipt"]["status"] == "failed"
    assert result["sources"] == []
    assert result["receipt"]["jobs"][0]["error_code"] == "text_too_long"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.brightdata.com/",
        "https://" + "user" + ":" + "pass" + "@www.brightdata.com/",
        "https://@www.brightdata.com/",
        "https://:@www.brightdata.com/",
        "https://127.0.0.1/",
        "https://localhost/",
        "https://service.internal/",
        "https://example.com/",
    ],
)
def test_c17_unsafe_live_targets_are_rejected(url):
    manifest = web_manifest()
    manifest["jobs"][0]["url"] = url
    with pytest.raises(BrightDataError):
        validate_live_plan(manifest)


def test_c20_markdown_exposes_scope_method_synthetic_and_limitations():
    from customer_led_page_rewrite.export import render_markdown

    rendered = render_markdown(analyze(fixture()))
    assert "Synthetic demonstration" in rendered
    assert "## Bounded Scope" in rendered
    assert "deterministic_rules_v1" in rendered
    assert "## Evidence Appendix" in rendered
    assert "## Limitations" in rendered
    assert "not conversion promises" in rendered


def test_cli_persists_safe_failed_receipt_for_fail_closed_rate_limit(tmp_path, monkeypatch):
    manifest = web_manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(approval(manifest, [WEB_URL], retained=1)))
    output = tmp_path / "library.json"
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fake-token")
    monkeypatch.setenv("BRIGHT_DATA_WEB_UNLOCKER_ZONE", "zone")
    monkeypatch.setattr(
        "customer_led_page_rewrite.cli.urllib_transport",
        lambda request: HttpResponse(429, {"Retry-After": "7"}, b"private body"),
    )
    code = main(
        [
            "collect",
            str(manifest_path),
            "--out",
            str(output),
            "--live",
            "--accept-charges",
            "--approval",
            str(approval_path),
        ]
    )
    assert code == 3
    library = json.loads(output.read_text())
    assert library["receipt"]["status"] == "failed"
    assert library["receipt"]["jobs"][0]["error_code"] == "rate_limited"
    assert "fake-token" not in output.read_text()
    assert "private body" not in output.read_text()


def test_cli_persists_safe_failed_receipt_on_resume_parse_failure(tmp_path, monkeypatch):
    receipt = valid_pending_receipt()
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(approval(receipt, [download], retained=1)))
    output = tmp_path / "resumed.json"
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fake-token")
    monkeypatch.setattr(
        "customer_led_page_rewrite.cli.urllib_transport",
        lambda request: HttpResponse(200, {}, b"private malformed payload"),
    )
    assert main(
        [
            "resume",
            str(receipt_path),
            "--out",
            str(output),
            "--live",
            "--accept-charges",
            "--approval",
            str(approval_path),
        ]
    ) == 3
    saved = json.loads(output.read_text())
    assert saved["receipt"]["status"] == "failed"
    assert saved["receipt"]["jobs"][0]["error_code"] == "invalid_response"
    assert "private malformed payload" not in output.read_text()
    assert "fake-token" not in output.read_text()
