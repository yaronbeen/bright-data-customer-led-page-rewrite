"""Brand-truthfulness and provider-documentation regression tests."""

from __future__ import annotations

import json
import csv
import io
from pathlib import Path

import pytest

from customer_led_page_rewrite.brightdata import (
    AMAZON_DATASET,
    AMAZON_SCRAPER_NAME,
    YOUTUBE_DATASET,
    YOUTUBE_SCRAPER_NAME,
    BrightDataError,
    HttpResponse,
    _manifest_hash,
    collect,
)
from customer_led_page_rewrite.export import render_csv, render_markdown


ROOT = Path(__file__).parents[1]
NOW = "2026-10-05T00:00:00Z"
EXPIRY = "2035-01-01T00:00:00Z"
AMAZON_URL = "https://www.amazon.com/dp/B0CHHSFMRL"
YOUTUBE_URL = "https://www.youtube.com/watch?v=abcdefghijk"


def approval(manifest: dict, urls: list[str], retained: int = 5) -> dict:
    return {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "manifest_sha256": _manifest_hash(manifest),
        "expires_at": EXPIRY,
        "max_requests": len(manifest["jobs"]),
        "max_retained_records": retained,
        "approved_urls": urls,
        "account_budget_confirmed": True,
        "target_permissions_confirmed": True,
        "remote_resolution_risk_accepted": True,
    }


def report_with_citations(provenances: list[str], cited_ids: list[str]) -> dict:
    sources = [
        {
            "id": f"s{index}",
            "url": f"https://example.com/{index}",
            "observed_at": NOW,
            "content_sha256": str(index) * 64,
            "provenance": provenance,
            "record_id": None,
        }
        for index, provenance in enumerate(provenances, 1)
    ]
    refs = [
        {"source_id": source_id, "block_id": "b0001", "quote": f"quote {source_id}"}
        for source_id in cited_ids
    ]
    return {
        "source_index": sources,
        "headlines": [],
        "faqs": [],
        "question_map": [
            {
                "before_refs": refs,
                "audience_refs": [],
                "fact_refs": [],
            }
        ],
        "proof_needed": [],
        "decision": "annotated_rewrite",
        "status": "ok",
        "analysis_method": "deterministic_rules_v1",
        "draft_method": "approved_text_templates_v1",
        "scope": {"product": "Example", "source_ids": [source["id"] for source in sources]},
    }


def test_readme_uses_neutral_workflow_language_and_truthful_template_sources():
    readme = (ROOT / "README.md").read_text()
    opening = "\n".join(readme.splitlines()[:16]).casefold()
    assert "page keeps dodging" not in opening
    assert "customer-led is the workflow name" in opening
    assert "does not establish customer identity or buying intent" in opening
    assert "public-contributor language selected by an operator" in opening
    assert "operator-supplied product and question text" in readme
    assert "approved fact text" in readme


def test_generated_artifact_prominently_disclaims_customer_identity_and_template_inputs():
    report = report_with_citations(["synthetic_fixture"], ["s1"])
    rendered = render_markdown(report)
    prominent = "\n".join(rendered.splitlines()[:14]).casefold()
    assert "customer-led is a workflow name" in prominent
    assert "does not establish customer identity or buying intent" in prominent
    assert "public-contributor language selected by an operator" in prominent
    assert "operator-supplied product/question text" in rendered
    assert "approved fact text" in rendered


def test_uncited_synthetic_source_does_not_trigger_synthetic_banner():
    report = report_with_citations(["synthetic_fixture", "bright_data"], ["s2"])
    rendered = render_markdown(report)
    assert "Synthetic demonstration" not in rendered
    assert "Mixed-provenance evidence" not in rendered


def test_mixed_banner_depends_only_on_cited_source_provenance():
    report = report_with_citations(["synthetic_fixture", "operator_supplied"], ["s1", "s2"])
    rendered = render_markdown(report)
    assert "Mixed-provenance evidence" in rendered
    assert "synthetic and non-synthetic cited sources" in rendered


def test_all_cited_synthetic_sources_keep_synthetic_banner():
    report = report_with_citations(["synthetic_fixture", "bright_data"], ["s1"])
    rendered = render_markdown(report)
    assert "Synthetic demonstration" in rendered
    assert "all cited source content" in rendered


def test_web_unlocker_envelope_is_fail_closed_and_live_shape_remains_unverified(tmp_path):
    url = "https://www.brightdata.com/"
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "landing",
                "kind": "web_page",
                "role": "landing_page",
                "source_id": "landing",
                "url": url,
            }
        ],
    }
    calls = []

    def transport(request):
        calls.append(request)
        envelope = {"status_code": 200, "headers": {"content-type": "text/markdown"}, "body": "# Page"}
        return HttpResponse(200, {"Content-Type": "application/json"}, json.dumps(envelope).encode())

    with pytest.raises(BrightDataError) as caught:
        collect(
            manifest,
            approval=approval(manifest, [url], retained=1),
            api_key="fake",
            zones={"web_unlocker": "zone"},
            transport=transport,
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert caught.value.code == "response_contract_mismatch"
    assert caught.value.receipt["receipt"]["status"] == "failed"
    assert caught.value.receipt["sources"] == []
    assert len(calls) == 1

    readme = (ROOT / "README.md").read_text()
    assert "conflicting response shapes" in readme
    assert "fail-closed" in readme
    assert "live compatibility is unverified" in readme


@pytest.mark.parametrize(
    "kind,url,dataset_id,count_key",
    [
        ("amazon_reviews", AMAZON_URL, "gd_le8e811kzy4ggddlq", "max_reviews"),
        ("youtube_comments", YOUTUBE_URL, "gd_lk9q0ew71spt1mxywf", "num_of_comments"),
    ],
)
def test_named_scraper_adapters_use_current_pinned_dataset_ids(
    tmp_path, kind, url, dataset_id, count_key
):
    assert AMAZON_DATASET == "gd_le8e811kzy4ggddlq"
    assert YOUTUBE_DATASET == "gd_lk9q0ew71spt1mxywf"
    assert AMAZON_SCRAPER_NAME == "Amazon Reviews Scraper API"
    assert YOUTUBE_SCRAPER_NAME == "YouTube Comments Scraper API"
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "records",
                "kind": kind,
                "role": "audience_language",
                "source_prefix": "records",
                "urls": [url],
                count_key: 1,
            }
        ],
    }
    calls = []

    def transport(request):
        calls.append(request)
        return HttpResponse(200, {}, b"[]")

    collect(
        manifest,
        approval=approval(manifest, [url], retained=1),
        api_key="fake",
        zones={},
        transport=transport,
        now=NOW,
        ledger_path=tmp_path / f"{kind}-ledger",
    )
    assert len(calls) == 1
    assert f"dataset_id={dataset_id}" in calls[0].url
    body = json.loads(calls[0].body)
    assert body["input"] == [{"url": url, count_key: 1}]


def test_readme_uses_current_scraper_names_ids_and_direct_docs_links():
    readme = (ROOT / "README.md").read_text()
    assert "Amazon Reviews Scraper API" in readme
    assert "YouTube Comments Scraper API" in readme
    assert "`gd_le8e811kzy4ggddlq`" in readme
    assert "`gd_lk9q0ew71spt1mxywf`" in readme
    assert "https://docs.brightdata.com/api-reference/scrapers/e-commerce-apis/amazon-reviews-collect-by-url" in readme
    assert "https://docs.brightdata.com/api-reference/scrapers/social-media-apis/youtube-comments-collect-by-url" in readme
    assert "https://docs.brightdata.com/api-reference/rest-api/unlocker/unlock-website" in readme
    assert "https://docs.brightdata.com/products/web-unlocker/features#scrape-as-markdown" in readme


def test_detached_csv_rows_disclose_synthetic_real_and_mixed_cited_provenance():
    report = report_with_citations(
        ["synthetic_fixture", "bright_data", "operator_supplied"],
        [],
    )
    synthetic_ref = {"source_id": "s1", "block_id": "b0001", "quote": "invented"}
    real_ref = {"source_id": "s2", "block_id": "b0001", "quote": "collected"}
    mixed_ref = {"source_id": "s3", "block_id": "b0001", "quote": "operator note"}
    report["headlines"] = [
        {"topic_id": "synthetic", "text": "Synthetic draft", "state": "template", "audience_refs": [synthetic_ref], "fact_refs": []},
        {"topic_id": "real", "text": "Collected draft", "state": "template", "audience_refs": [real_ref], "fact_refs": []},
        {"topic_id": "mixed", "text": "Mixed draft", "state": "template", "audience_refs": [synthetic_ref, real_ref], "fact_refs": [mixed_ref]},
    ]
    rows = list(csv.DictReader(io.StringIO(render_csv(report))))
    by_topic = {row["topic_id"]: row for row in rows if row["row_type"] == "headline"}

    assert by_topic["synthetic"]["provenance_state"] == "synthetic"
    assert by_topic["synthetic"]["contains_synthetic_data"] == "true"
    assert by_topic["real"]["provenance_state"] == "non_synthetic"
    assert by_topic["real"]["contains_synthetic_data"] == "false"
    assert by_topic["mixed"]["provenance_state"] == "mixed"
    assert by_topic["mixed"]["contains_synthetic_data"] == "true"


def test_csv_provenance_is_computed_from_row_citations_not_uncited_sources():
    report = report_with_citations(
        ["synthetic_fixture", "bright_data"],
        [],
    )
    report["headlines"] = [
        {"topic_id": "real", "text": "Collected", "state": "template", "audience_refs": [{"source_id": "s2", "block_id": "b0001", "quote": "collected"}], "fact_refs": []}
    ]
    row = next(csv.DictReader(io.StringIO(render_csv(report))))
    assert row["provenance_state"] == "non_synthetic"
    assert row["contains_synthetic_data"] == "false"


def test_uncited_csv_row_does_not_claim_absence_of_synthetic_data():
    report = report_with_citations(["synthetic_fixture"], [])
    report["proof_needed"] = ["Approve evidence before making this claim."]

    row = next(
        row
        for row in csv.DictReader(io.StringIO(render_csv(report)))
        if row["row_type"] == "proof_needed"
    )

    assert row["provenance_state"] == "uncited"
    assert row["contains_synthetic_data"] == "unknown"


def test_readme_explains_standalone_csv_provenance_columns():
    readme = (ROOT / "README.md").read_text()
    assert "`provenance_state`" in readme
    assert "`contains_synthetic_data`" in readme
    assert "per row from only the cited source IDs" in readme
    assert "Uncited rows use `contains_synthetic_data=unknown`" in readme
