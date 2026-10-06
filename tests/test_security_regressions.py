"""Regression tests for security-review blockers and important hardening nits."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from customer_led_page_rewrite.brightdata import (
    BrightDataError,
    HttpResponse,
    _manifest_hash,
    collect,
    normalize_export,
    plan,
    resume,
    validate_live_plan,
)
from customer_led_page_rewrite.cli import InputError, _atomic_group, _output_reservation, main
from customer_led_page_rewrite.core import analyze
from customer_led_page_rewrite.export import render_csv, render_markdown


NOW = "2026-10-05T00:00:00Z"
EXPIRY = "2035-01-01T00:00:00Z"
WEB_URL = "https://www.brightdata.com/"
VIDEO_URL = "https://www.youtube.com/watch?v=abcdefghijk"


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


def web_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "landing",
                "kind": "web_page",
                "role": "landing_page",
                "source_id": "landing",
                "url": WEB_URL,
            }
        ],
    }


def youtube_manifest(*, count=1, urls=None) -> dict:
    return {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "comments",
                "kind": "youtube_comments",
                "role": "audience_language",
                "source_prefix": "yt",
                "urls": urls or [VIDEO_URL],
                "num_of_comments": count,
            }
        ],
    }


def test_approval_is_single_use_and_ledger_contains_no_secret_or_url(tmp_path):
    manifest = web_manifest()
    attestation = approval(manifest, [WEB_URL], retained=1)
    ledger = tmp_path / "ledger"
    calls = []

    def transport(request):
        calls.append(request)
        return HttpResponse(200, {}, b"# Page\n\nSafe body.")

    collect(
        manifest,
        approval=attestation,
        api_key="top-secret-token",
        zones={"web_unlocker": "zone"},
        transport=transport,
        now=NOW,
        ledger_path=ledger,
    )
    with pytest.raises(BrightDataError, match="approval_replayed"):
        collect(
            manifest,
            approval=attestation,
            api_key="top-secret-token",
            zones={"web_unlocker": "zone"},
            transport=transport,
            now=NOW,
            ledger_path=ledger,
        )

    assert len(calls) == 1
    ledger_text = "".join(path.read_text() for path in ledger.iterdir())
    assert "top-secret-token" not in ledger_text
    assert WEB_URL not in ledger_text


def test_concurrent_approval_consumption_allows_only_one_network_run(tmp_path):
    manifest = web_manifest()
    attestation = approval(manifest, [WEB_URL], retained=1)
    ledger = tmp_path / "ledger"
    calls = []
    lock = threading.Lock()

    def transport(request):
        with lock:
            calls.append(request)
        return HttpResponse(200, {}, b"# Page\n\nSafe body.")

    def run():
        try:
            return collect(
                manifest,
                approval=attestation,
                api_key="fake",
                zones={"web_unlocker": "zone"},
                transport=transport,
                now=NOW,
                ledger_path=ledger,
            )["receipt"]["status"]
        except BrightDataError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))

    assert sorted(results) == ["approval_replayed", "complete"]
    assert len(calls) == 1


def test_retention_cap_counts_pages_and_requested_records_before_network(tmp_path):
    manifest = web_manifest()
    manifest["jobs"].append(youtube_manifest(count=2)["jobs"][0])
    attestation = approval(manifest, [WEB_URL, VIDEO_URL], requests=2, retained=2)
    calls = []

    with pytest.raises(BrightDataError, match="approval_limit_exceeded"):
        collect(
            manifest,
            approval=attestation,
            api_key="fake",
            zones={"web_unlocker": "zone"},
            transport=lambda request: (calls.append(request), HttpResponse(200, {}, b"[]"))[1],
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert calls == []


@pytest.mark.parametrize(
    "query",
    [
        "X-Amz-Credential=secret",
        "%58-Amz-Signature=secret",
        "sig=secret&sv=2024",
        "access_token=secret",
        "apikey=secret",
        "credentials=secret",
        "ordinary=value",
    ],
)
def test_live_web_targets_reject_all_query_strings_without_echoing_values(query):
    manifest = web_manifest()
    manifest["jobs"][0]["url"] = f"https://www.brightdata.com/page?{query}"
    with pytest.raises(BrightDataError) as caught:
        validate_live_plan(manifest)
    assert "secret" not in str(caught.value)
    assert "value" not in str(caught.value)


def test_pending_receipt_redacts_youtube_query_and_carries_only_url_hash(tmp_path):
    manifest = youtube_manifest()
    attestation = approval(manifest, [VIDEO_URL], retained=1)
    result = collect(
        manifest,
        approval=attestation,
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(202, {}, b'{"snapshot_id":"snap_123"}'),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    serialized = json.dumps(result)
    assert "abcdefghijk" not in serialized
    assert "REDACTED" in serialized
    hashes = result["receipt"]["jobs"][0]["approved_url_sha256"]
    assert len(hashes) == 1 and len(hashes[0]) == 64


@pytest.mark.parametrize(
    ("kind", "urls", "changed_url"),
    [
        (
            "amazon_reviews",
            ["https://www.amazon.com/dp/B000000001", "https://www.amazon.com/dp/B000000002"],
            "https://www.amazon.com/dp/B000000009",
        ),
        (
            "youtube_comments",
            ["https://www.youtube.com/watch?v=abcdefghijk", "https://www.youtube.com/watch?v=mnopqrstuvw"],
            "https://www.youtube.com/watch?v=zyxwvutsrqp",
        ),
    ],
)
@pytest.mark.parametrize("index", [0, 1])
def test_resume_rejects_tampered_multi_url_receipt_before_transport(
    tmp_path, kind, urls, changed_url, index
):
    count_key = "max_reviews" if kind == "amazon_reviews" else "num_of_comments"
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "audience",
                "kind": kind,
                "role": "audience_language",
                "source_prefix": "audience",
                "urls": urls,
                count_key: 1,
            }
        ],
    }
    attestation = approval(manifest, urls, requests=2, retained=2)
    receipt = collect(
        manifest,
        approval=attestation,
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(202, {}, b'{"snapshot_id":"snap_123"}'),
        now=NOW,
        ledger_path=tmp_path / f"collect-{kind}-{index}",
    )
    receipt["receipt"]["jobs"][0]["original_job"]["urls"][index] = changed_url
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    resume_approval = approval(receipt, [download], retained=2)
    calls = []

    with pytest.raises(BrightDataError, match="invalid_receipt"):
        resume(
            receipt,
            approval=resume_approval,
            api_key="fake",
            transport=lambda request: calls.append(request),
            now=NOW,
            ledger_path=tmp_path / f"resume-{kind}-{index}",
        )

    assert calls == []


def test_resume_rejects_youtube_receipt_even_if_hash_and_binding_are_recomputed(tmp_path):
    manifest = youtube_manifest()
    receipt = collect(
        manifest,
        approval=approval(manifest, [VIDEO_URL], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(202, {}, b'{"snapshot_id":"snap_123"}'),
        now=NOW,
        ledger_path=tmp_path / "collect-youtube",
    )
    job = receipt["receipt"]["jobs"][0]
    replacement_url = "https://www.youtube.com/watch?v=zyxwvutsrqp"
    replacement_hash = hashlib.sha256(replacement_url.encode()).hexdigest()
    safe_url = job["original_job"]["urls"][0]
    job["approved_url_sha256"][0] = replacement_hash
    job["approved_url_binding_sha256"][0] = hashlib.sha256(
        f"{safe_url}\0{replacement_hash}".encode()
    ).hexdigest()
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    calls = []

    with pytest.raises(BrightDataError, match="invalid_receipt"):
        resume(
            receipt,
            approval=approval(receipt, [download], retained=1),
            api_key="fake",
            transport=lambda request: (calls.append(request), HttpResponse(200, {}, b"[]"))[1],
            now=NOW,
            ledger_path=tmp_path / "resume-youtube",
        )

    assert calls == []


@pytest.mark.parametrize("malformation", ["hash_item", "binding_item", "kind", "state"])
def test_malformed_resume_receipt_is_safe_for_api_and_cli(
    tmp_path, capsys, monkeypatch, malformation
):
    url = "https://www.amazon.com/dp/B000000001"
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "reviews",
                "kind": "amazon_reviews",
                "role": "audience_language",
                "source_prefix": "reviews",
                "urls": [url],
                "max_reviews": 1,
            }
        ],
    }
    receipt = collect(
        manifest,
        approval=approval(manifest, [url], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(202, {}, b'{"snapshot_id":"snap_123"}'),
        now=NOW,
        ledger_path=tmp_path / f"collect-{malformation}",
    )
    job = receipt["receipt"]["jobs"][0]
    if malformation == "hash_item":
        job["approved_url_sha256"][0] = {"not": "a hash"}
    elif malformation == "binding_item":
        job["approved_url_binding_sha256"][0] = ["not-a-hash"]
    elif malformation == "kind":
        job["kind"] = ["amazon_reviews"]
    else:
        job["state"] = {"pending": True}

    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    calls = []
    with pytest.raises(BrightDataError) as caught:
        resume(
            receipt,
            approval=approval(receipt, [download], retained=1),
            api_key="fake",
            transport=lambda request: (calls.append(request), HttpResponse(200, {}, b"[]"))[1],
            now=NOW,
            ledger_path=tmp_path / f"api-{malformation}",
        )
    assert caught.value.code == "invalid_receipt"
    assert calls == []

    receipt_path = tmp_path / f"receipt-{malformation}.json"
    approval_path = tmp_path / f"approval-{malformation}.json"
    receipt_path.write_text(json.dumps(receipt))
    approval_path.write_text(json.dumps(approval(receipt, [download], retained=1)))
    cli_calls = []
    import customer_led_page_rewrite.cli as cli

    monkeypatch.setattr(
        cli,
        "urllib_transport",
        lambda request: (cli_calls.append(request), HttpResponse(200, {}, b"[]"))[1],
    )
    exit_code = main(
        [
            "resume",
            str(receipt_path),
            "--out",
            str(tmp_path / f"out-{malformation}.json"),
            "--approval",
            str(approval_path),
            "--live",
            "--accept-charges",
        ]
    )
    error_output = capsys.readouterr().err
    assert exit_code == 2
    assert json.loads(error_output)["code"] == "invalid_receipt"
    assert "Traceback" not in error_output
    assert cli_calls == []


def test_plan_redacts_every_query_value_but_keeps_manifest_hash():
    manifest = youtube_manifest()
    result = plan(manifest)
    serialized = json.dumps(result)
    assert "abcdefghijk" not in serialized
    assert result["approved_targets_required"] == [
        "https://www.youtube.com/watch?v=REDACTED"
    ]
    assert result["manifest_sha256"] == _manifest_hash(manifest)


def test_provider_record_url_must_match_an_approved_batch_input(tmp_path):
    manifest = youtube_manifest()
    attestation = approval(manifest, [VIDEO_URL], retained=1)
    records = [
        {
            "url": "https://tracker.example.org/profile?access_token=stolen",
            "comment_id": "C1",
            "comment_text": "How do I start?",
        }
    ]
    result = collect(
        manifest,
        approval=attestation,
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(200, {}, json.dumps(records).encode()),
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert result["sources"] == []
    assert result["receipt"]["excluded_records"] == 1
    assert "stolen" not in json.dumps(result)


@pytest.mark.parametrize(
    ("kind", "url", "id_key", "text_key"),
    [
        ("amazon_reviews", "https://www.amazon.com/dp/B000000001", "review_id", "review_text"),
        ("youtube_comments", VIDEO_URL, "comment_id", "comment_text"),
    ],
)
def test_provider_credential_like_record_ids_are_opaque_in_all_outputs(
    tmp_path, kind, url, id_key, text_key
):
    secret_id = "ghp_" + "0123456789abcdefghijklmnopqrstuvwxyzABCD"
    manifest = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "jobs": [
            {
                "id": "audience",
                "kind": kind,
                "role": "audience_language",
                "source_prefix": "audience",
                "urls": [url],
                ("max_reviews" if kind == "amazon_reviews" else "num_of_comments"): 1,
            }
        ],
    }
    provider_record = {
        "url": url,
        id_key: secret_id,
        text_key: "What do I need to get started?",
    }
    collected = collect(
        manifest,
        approval=approval(manifest, [url], retained=1),
        api_key="fake",
        zones={},
        transport=lambda request: HttpResponse(200, {}, json.dumps([provider_record]).encode()),
        now=NOW,
        ledger_path=tmp_path / f"ledger-{kind}",
    )
    report_input = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "demo.json").read_text()
    )
    report_source = copy.deepcopy(collected["sources"][0])
    report_source["record_id"] = secret_id
    report_input["sources"].append(report_source)
    report = analyze(report_input)
    outputs = "\n".join(
        [
            json.dumps(collected, sort_keys=True),
            json.dumps(report, sort_keys=True),
            render_markdown(report),
            render_csv(report),
        ]
    )

    opaque_id = collected["sources"][0]["record_id"]
    assert secret_id not in outputs
    assert opaque_id == "provider-sha256-" + hashlib.sha256(secret_id.encode()).hexdigest()
    assert collected["sources"][0]["record_id_origin"] == "provider"
    assert collected["sources"][0]["provenance"] == "bright_data"
    assert next(
        source for source in report["source_index"] if source["id"] == report_source["id"]
    )["record_id"] == opaque_id


def test_resume_cap_includes_sources_already_retained_and_consumes_no_request(tmp_path):
    job = {
        "id": "reviews",
        "kind": "amazon_reviews",
        "role": "audience_language",
        "source_prefix": "reviews",
        "urls": ["https://www.amazon.com/dp/B000000001"],
        "max_reviews": 2,
    }
    amazon_hash = hashlib.sha256(job["urls"][0].encode()).hexdigest()
    receipt = {
        "schema_version": "1.0",
        "project": "customer-led-page-rewrite",
        "transport_contract_version": "1.0",
        "sources": [
            {
                "id": "already-retained",
                "kind": "question",
                "role": "audience_language",
                "url": "https://www.amazon.com/dp/B000000001",
                "title": "Public comment",
                "text": "Previously retained text.",
                "status": "collected",
                "observed_at": NOW,
                "published_at": None,
                "provider_date": None,
                "record_id": "C0",
                "record_id_origin": "provider",
                "provenance": "bright_data",
            }
        ],
        "receipt": {
            "schema_version": "1.0",
            "project": "customer-led-page-rewrite",
            "manifest_sha256": "0" * 64,
            "status": "pending",
            "requests_made": 1,
            "returned_records": 1,
            "retained_records": 1,
            "excluded_records": 0,
            "jobs": [
                {
                    "id": "reviews",
                    "kind": "amazon_reviews",
                    "state": "pending",
                    "original_job": job,
                    "approved_url_sha256": [amazon_hash],
                    "approved_url_binding_sha256": [hashlib.sha256(f"{job['urls'][0]}\0{amazon_hash}".encode()).hexdigest()],
                    "requested_records": 2,
                    "returned_records": 1,
                    "retained_records": 1,
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
    download = "https://api.brightdata.com/datasets/v3/snapshot/snap_123?format=json"
    attestation = approval(receipt, [download], retained=2)
    calls = []
    with pytest.raises(BrightDataError, match="approval_limit_exceeded"):
        resume(
            receipt,
            approval=attestation,
            api_key="fake",
            transport=lambda request: calls.append(request),
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert calls == []


def test_artifacts_redact_query_values_from_operator_sources():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures" / "demo.json").read_text())
    fixture["sources"][0]["url"] = "https://example.com/harbor?access_token=do-not-publish"
    report = analyze(fixture)
    rendered = render_markdown(report)
    serialized = json.dumps(report)
    assert "do-not-publish" not in serialized
    assert "do-not-publish" not in rendered
    assert "access_token=REDACTED" in serialized


def test_markdown_escapes_all_active_metacharacters_and_collapses_lines():
    hostile = "# heading\n![alt](javascript:alert(1)) [link](https://evil) *bold* _em_ > quote \\ `code` | cell"
    report = {
        "source_index": [
            {
                "id": "q",
                "url": "https://example.com/q",
                "observed_at": NOW,
                "content_sha256": "0" * 64,
                "provenance": "synthetic_fixture",
                "record_id": None,
            }
        ],
        "headlines": [],
        "faqs": [
            {
                "topic_id": "t",
                "question": hostile,
                "question_origin": "observed",
                "target_heading": hostile,
                "page_answer_state": "related_copy_only",
                "before_refs": [{"source_id": "q", "block_id": "b0001", "quote": hostile}],
                "audience_refs": [],
                "fact_refs": [],
                "draft": hostile,
                "draft_state": "approved_text_ready",
                "proof_needed": [],
            }
        ],
        "question_map": [],
        "proof_needed": [hostile],
        "decision": "annotated_rewrite",
        "status": "needs_review",
        "analysis_method": "deterministic_rules_v1",
        "draft_method": "approved_text_templates_v1",
        "scope": {"product": hostile, "source_ids": []},
    }
    rendered = render_markdown(report)
    assert "javascript:alert\\(1\\)" in rendered
    assert "![alt](" not in rendered
    assert "[link](" not in rendered
    assert "\n![alt]" not in rendered
    assert "\\# heading" in rendered
    assert "\\!\\[alt\\]\\(" in rendered
    assert "\\*bold\\*" in rendered
    assert "\\_em\\_" in rendered
    assert "&gt; quote" in rendered
    assert "\\\\" in rendered
    assert "\\`code\\`" in rendered
    assert "\\| cell" in rendered


@pytest.mark.parametrize("prefix", ["", "\t", "\ufeff", "\u200b", "\u2060"])
@pytest.mark.parametrize("operator", ["=", "+", "-", "@", "＝"])
def test_csv_formula_variants_are_prefixed(prefix, operator):
    report = {
        "source_index": [],
        "headlines": [],
        "faqs": [],
        "question_map": [],
        "proof_needed": [prefix + operator + "COMMAND()"],
    }
    rows = list(csv.DictReader(io.StringIO(render_csv(report))))
    assert rows[0]["proof_needed"].startswith("'")


def test_rate_limit_reports_numeric_retry_after_and_never_retries(tmp_path):
    manifest = web_manifest()
    attestation = approval(manifest, [WEB_URL], retained=1)
    calls = []

    def transport(request):
        calls.append(request)
        return HttpResponse(429, {"Retry-After": "17", "X-Provider-Message": "secret"}, b"private provider body")

    with pytest.raises(BrightDataError) as caught:
        collect(
            manifest,
            approval=attestation,
            api_key="fake",
            zones={"web_unlocker": "zone"},
            transport=transport,
            now=NOW,
            ledger_path=tmp_path / "ledger",
        )
    assert caught.value.code == "rate_limited"
    assert caught.value.retry_after_seconds == 17
    assert caught.value.receipt["receipt"]["status"] == "failed"
    assert caught.value.receipt["receipt"]["jobs"][0]["state"] == "failed"
    assert len(calls) == 1
    assert "secret" not in str(caught.value)


def test_web_transport_serialization_is_exact_and_authorization_is_not_retained(tmp_path):
    manifest = web_manifest()
    attestation = approval(manifest, [WEB_URL], retained=1)
    calls = []

    def transport(request):
        calls.append(request)
        return HttpResponse(200, {}, b"# Public page\n\nVisible copy.")

    result = collect(
        manifest,
        approval=attestation,
        api_key="fake-token",
        zones={"web_unlocker": "selected-zone"},
        transport=transport,
        now=NOW,
        ledger_path=tmp_path / "ledger",
    )
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].url == "https://api.brightdata.com/request"
    assert calls[0].timeout_seconds == 75
    assert json.loads(calls[0].body) == {
        "zone": "selected-zone",
        "url": WEB_URL,
        "format": "raw",
        "data_format": "markdown",
    }
    assert "fake-token" not in json.dumps(result)


def test_atomic_report_group_rolls_back_all_files_on_commit_failure(tmp_path, monkeypatch):
    originals = {
        "report.json": "old json",
        "rewrite.md": "old markdown",
        "rewrite.csv": "old csv",
    }
    for name, content in originals.items():
        (tmp_path / name).write_text(content)
    real_replace = __import__("os").replace
    failed = False

    def fail_once(source, destination):
        nonlocal failed
        source_path = Path(source)
        destination_path = Path(destination)
        if not failed and source_path.name.startswith(".rewrite.md.") and destination_path.name == "rewrite.md":
            failed = True
            raise OSError("injected commit failure")
        return real_replace(source, destination)

    monkeypatch.setattr("customer_led_page_rewrite.cli.os.replace", fail_once)
    with pytest.raises(OSError, match="injected commit failure"):
        _atomic_group(
            tmp_path,
            {name: "new " + content for name, content in originals.items()},
            overwrite=True,
        )
    assert {name: (tmp_path / name).read_text() for name in originals} == originals
    assert not (tmp_path / ".customer-led-page-rewrite.lock").exists()


def test_atomic_report_group_rejects_collision_without_changes(tmp_path):
    target = tmp_path / "report.json"
    target.write_text("original")
    with pytest.raises(InputError, match="already exist"):
        _atomic_group(tmp_path, {"report.json": "replacement"}, overwrite=False)
    assert target.read_text() == "original"


def test_output_reservation_blocks_concurrent_paid_run_and_cleans_lock(tmp_path):
    output = tmp_path / "library.json"
    with _output_reservation(output, overwrite=False):
        with pytest.raises(InputError, match="reserved"):
            with _output_reservation(output, overwrite=False):
                raise AssertionError("second reservation entered")
        assert not output.exists()
    assert not (tmp_path / ".library.json.reservation").exists()


def test_offline_import_redacts_query_values():
    result = normalize_export(
        "youtube_comments",
        [{"comment_id": "C1", "comment_text": "Question?"}],
        role="audience_language",
        source_url="https://www.youtube.com/watch?v=abcdefghijk&access_token=secret",
        observed_at=NOW,
        source_prefix="yt",
    )
    serialized = json.dumps(result)
    assert "secret" not in serialized
    assert "abcdefghijk" not in serialized
    assert "REDACTED" in serialized
