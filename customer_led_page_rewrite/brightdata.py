"""Bounded optional Bright Data retrieval and offline export normalization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from .security import has_sensitive_query, opaque_provider_record_id, redact_url, url_sha256

PROJECT = "customer-led-page-rewrite"
API_HOST = "api.brightdata.com"
API_ROOT = f"https://{API_HOST}"
AMAZON_DATASET = "gd_le8e811kzy4ggddlq"
YOUTUBE_DATASET = "gd_lk9q0ew71spt1mxywf"
MAPS_DATASET = "gd_luzfs1dn2oa0teb81"
AMAZON_SCRAPER_NAME = "Amazon Reviews Scraper API"
YOUTUBE_SCRAPER_NAME = "YouTube Comments Scraper API"
MAX_BYTES = 2 * 1024 * 1024
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PREFIX_RE = re.compile(r"^[a-z][a-z0-9_-]{0,46}$")
SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9_]{1,128}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
RESERVED_SUFFIXES = (".localhost", ".local", ".internal", ".invalid", ".example", ".test")
FIXTURE_HOSTS = {"example.com", "example.org", "example.net"}


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes
    timeout_seconds: int


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class BrightDataError(ValueError):
    def __init__(self, code: str, *, provider_failure: bool = False, requests_made: int = 0, retry_after_seconds: int | None = None):
        super().__init__(code)
        self.code = code
        self.provider_failure = provider_failure
        self.requests_made = requests_made
        self.retry_after_seconds = retry_after_seconds
        self.receipt = None


class TransportError(BrightDataError):
    def __init__(self, code: str = "transport_error", *, requests_made: int = 0):
        super().__init__(code, provider_failure=True, requests_made=requests_made)


def _error(code: str, *, provider: bool = False, requests: int = 0, retry_after_seconds: int | None = None):
    raise BrightDataError(code, provider_failure=provider, requests_made=requests, retry_after_seconds=retry_after_seconds)


def _timestamp(value: str, name: str = "timestamp") -> str:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        _error(f"invalid_{name}")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _error(f"invalid_{name}")
    return value


def _now(value) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            _error("invalid_now")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _timestamp(value, "now")


def _canonical_url(value: str, *, live: bool) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        _error("invalid_url")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _error("invalid_url")
    if parsed.scheme.lower() != "https" or not parsed.hostname or "@" in parsed.netloc or parsed.username or parsed.password or parsed.fragment or port not in (None, 443):
        _error("invalid_url")
    host = parsed.hostname.lower().rstrip(".")
    labels = host.split(".")
    if len(labels) < 2 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label) for label in labels) or labels[-1].isdigit():
        _error("invalid_url")
    if re.fullmatch(r"\d+(?:\.\d+){3}", host) or ":" in host or host == "localhost" or host.endswith(RESERVED_SUFFIXES):
        _error("invalid_url")
    if live and has_sensitive_query(value):
        _error("sensitive_url")
    if live and (host in FIXTURE_HOSTS or any(host.endswith("." + item) for item in FIXTURE_HOSTS)):
        _error("fixture_url_not_live")
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


def _id(value, *, prefix: bool = False) -> str:
    pattern = PREFIX_RE if prefix else ID_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        _error("invalid_id")
    return value


def _compact_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _manifest_hash(manifest: dict) -> str:
    return _compact_hash(manifest)


def _canonical_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text or any(ord(c) < 32 and c not in "\t\n" for c in text):
        _error("invalid_record")
    blocks = []
    current = []
    for line in text.split("\n"):
        if re.fullmatch(r"#{1,6}[ \t]+.+", line.strip()):
            if current:
                blocks.append(" ".join("\n".join(current).split()))
                current = []
            blocks.append(" ".join(line.strip().split()))
        elif not line.strip():
            if current:
                blocks.append(" ".join("\n".join(current).split()))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(" ".join("\n".join(current).split()))
    return "\n\n".join(blocks)


def _published(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source(*, sid, kind, role, url, title, text, observed_at, published_at=None, provider_date=None, record_id=None, origin="none", provenance="operator_supplied") -> dict:
    status = "collected" if text.strip() else "empty"
    return {
        "id": sid, "kind": kind, "role": role, "url": url, "title": title[:200], "text": text,
        "status": status, "observed_at": observed_at, "published_at": published_at,
        "provider_date": provider_date[:100] if isinstance(provider_date, str) else None,
        "record_id": record_id, "record_id_origin": origin, "provenance": provenance,
    }


def _warning(code: str, source_ids: list[str] | None = None, note: str = "") -> dict:
    return {"code": code, "source_ids": source_ids or [], "note": note or code.replace("_", " ")}


def _normalize_records(
    kind: str,
    records: list,
    *,
    role: str,
    source_url: str,
    observed_at: str,
    source_prefix: str,
    provenance: str,
    limit: int = 50,
    batch_urls: list[str] | None = None,
    approved_url_hashes: list[str] | None = None,
) -> tuple[list[dict], dict]:
    if not isinstance(records, list):
        _error("invalid_response")
    sources, warnings = [], []
    excluded = 0
    provider_error_code = None
    seen: dict[tuple, tuple[str, int]] = {}
    conflicts: set[tuple] = set()
    mappings = {
        "amazon_reviews": ("review_text", "review_header", "review_posted_date", "review_id", "review", "Review"),
        "youtube_comments": ("comment_text", None, "date", "comment_id", "question", "Public question/comment"),
        "google_maps_reviews": ("review", None, "review_date", "review_id", "review", "Public review"),
    }
    parents = batch_urls or [source_url]
    parent_hashes = approved_url_hashes or [url_sha256(url) for url in parents]
    allowed_hashes = set(parent_hashes)
    text_key, title_key, date_key, id_key, source_kind, fallback_title = mappings[kind]
    for record in records:
        if not isinstance(record, dict):
            excluded += 1
            warnings.append(_warning("invalid_record"))
            continue
        if record.get("error_code") is not None:
            excluded += 1
            code = record.get("error_code")
            safe = code if isinstance(code, str) and code in {"dead_page", "bucket_rate_limit", "global_rate_limit"} else "record_error"
            if provider_error_code is None:
                provider_error_code = safe
            warnings.append(_warning(safe))
            continue
        text = record.get(text_key)
        if not isinstance(text, str) or not text.strip():
            excluded += 1
            warnings.append(_warning("invalid_record"))
            continue
        max_len = 5000
        if len(text) > max_len:
            excluded += 1
            warnings.append(_warning("text_too_long"))
            continue
        try:
            canonical = _canonical_text(text)
        except BrightDataError:
            excluded += 1
            warnings.append(_warning("invalid_record"))
            continue
        candidate_url = record.get("url")
        if candidate_url is None:
            if len(parents) != 1:
                excluded += 1
                warnings.append(_warning("invalid_record", note="A multi-input record omitted its source URL."))
                continue
            url = parents[0]
            identity_hash = parent_hashes[0]
        else:
            try:
                canonical_candidate = _canonical_url(candidate_url, live=False)
            except BrightDataError:
                excluded += 1
                warnings.append(_warning("invalid_record"))
                continue
            identity_hash = url_sha256(canonical_candidate)
            if identity_hash not in allowed_hashes:
                excluded += 1
                warnings.append(_warning("unmapped_record_url"))
                continue
            url = canonical_candidate
        artifact_url = redact_url(url)
        record_id = record.get(id_key)
        if record_id is not None and (not isinstance(record_id, str) or not record_id.strip() or len(record_id) > 200):
            excluded += 1
            warnings.append(_warning("invalid_record"))
            continue
        if record_id is None:
            record_id = "content-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
            origin = "content_hash"
        else:
            record_id = str(record_id)
            origin = "provider" if provenance == "bright_data" else "operator"
        key = (source_kind, identity_hash, record_id)
        if key in seen:
            prior_text, prior_index = seen[key]
            excluded += 1
            if prior_text != canonical:
                conflicts.add(key)
                warnings.append(_warning("conflicting_record"))
            else:
                warnings.append(_warning("duplicate_record"))
            continue
        seen[key] = (canonical, len(sources))
        sid = f"{source_prefix}-{hashlib.sha256(json.dumps([source_kind, identity_hash, record_id], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:16]}"
        title = record.get(title_key) if title_key else None
        if not isinstance(title, str) or not title.strip():
            title = fallback_title
        raw_date = record.get(date_key)
        iso_candidate = record.get("date_iso") if kind == "youtube_comments" else raw_date
        published_at = _published(iso_candidate)
        stored_record_id = opaque_provider_record_id(record_id) if origin == "provider" else record_id
        sources.append(_source(sid=sid, kind=source_kind, role=role, url=artifact_url, title=title, text=canonical, observed_at=observed_at, published_at=published_at, provider_date=raw_date if isinstance(raw_date, str) else None, record_id=stored_record_id, origin=origin, provenance=provenance))
    if conflicts:
        bad_indices = {seen[key][1] for key in conflicts}
        sources = [source for index, source in enumerate(sources) if index not in bad_indices]
        excluded += len(bad_indices)
    over = max(0, len(sources) - limit)
    if over:
        sources = sources[:limit]
        excluded += over
        warnings.append(_warning("provider_limit_exceeded"))
    return sources, {
        "returned": len(records), "retained": len(sources), "excluded": excluded,
        "warnings": warnings,
        "partial": bool(over or conflicts or provider_error_code or any(warning["code"] != "duplicate_record" for warning in warnings)),
        "provider_error_code": provider_error_code,
    }


def _receipt(*, status: str, sources: list[dict], returned: int, excluded: int, warnings: list[dict], manifest_hash: str | None = None, requests: int = 0, jobs: list[dict] | None = None) -> dict:
    safe_sources = []
    for source in sources:
        safe_source = dict(source)
        if "url" in safe_source:
            safe_source["url"] = redact_url(safe_source["url"])
        safe_sources.append(safe_source)
    return {
        "schema_version": "1.0", "project": PROJECT, "transport_contract_version": "1.0",
        "sources": safe_sources,
        "receipt": {"schema_version": "1.0", "project": PROJECT, "manifest_sha256": manifest_hash,
                    "status": status, "requests_made": requests, "returned_records": returned,
                    "retained_records": len(safe_sources), "excluded_records": excluded, "jobs": jobs or [],
                    "warnings": warnings, "provider_cost_usd": None},
    }


def normalize_export(kind, records, *, role, source_url, observed_at, source_prefix) -> dict:
    """Normalize a previously authorized local export without HTTP."""
    _timestamp(observed_at, "observed_at")
    _id(source_prefix, prefix=True)
    source_url = _canonical_url(source_url, live=False)
    supported = {"web_page": {"landing_page", "approved_product_fact"}, "amazon_reviews": {"audience_language"}, "youtube_comments": {"audience_language"}, "google_maps_reviews": {"audience_language"}}
    if kind not in supported or role not in supported[kind]:
        _error("unsupported_kind_role")
    if kind == "web_page":
        if not isinstance(records, str):
            _error("invalid_response")
        stripped = records.lstrip().casefold()
        if stripped.startswith(("<!doctype html", "<html", "<body")):
            _error("unsupported_content_format")
        text = _canonical_text(records)
        if len(text) > 50000:
            _error("text_too_long")
        heading = next((re.sub(r"^#\s+", "", line).strip() for line in records.splitlines() if re.match(r"^#\s+", line)), "Selected public page")
        sid = f"{source_prefix}-{hashlib.sha256(source_url.encode()).hexdigest()[:16]}"
        sources = [_source(sid=sid, kind="page", role=role, url=redact_url(source_url), title=heading, text=text, observed_at=observed_at)]
        stats = {"returned": 1, "retained": 1, "excluded": 0, "warnings": [], "partial": False}
    else:
        sources, stats = _normalize_records(kind, records, role=role, source_url=source_url, observed_at=observed_at, source_prefix=source_prefix, provenance="operator_supplied", batch_urls=[source_url])
    status = "partial" if stats["partial"] else "complete"
    job = {"id": "offline-import", "kind": kind, "state": "complete" if sources else "empty", "original_job": {}, "approved_url_sha256": [], "approved_url_binding_sha256": [], "requested_records": None, "returned_records": stats["returned"], "retained_records": stats["retained"], "excluded_records": stats["excluded"], "snapshot_id": None, "error_code": None, "query_metadata": None}
    return _receipt(status=status, sources=sources, returned=stats["returned"], excluded=stats["excluded"], warnings=stats["warnings"], jobs=[job])


def _validate_manifest(manifest: dict, *, live: bool) -> tuple[list[dict], list[str], int]:
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "project", "jobs"} or manifest.get("schema_version") != "1.0" or manifest.get("project") != PROJECT:
        _error("invalid_manifest")
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 3:
        _error("manifest_call_limit")
    seen, source_ids, targets, requested_total = set(), set(), [], 0
    counts = {"web_page": 0, "amazon_reviews": 0, "youtube_comments": 0}
    for job in jobs:
        if not isinstance(job, dict):
            _error("invalid_job")
        jid = _id(job.get("id"))
        if jid in seen:
            _error("duplicate_job_id")
        seen.add(jid)
        kind = job.get("kind")
        if kind not in counts:
            _error("unsupported_job_kind")
        counts[kind] += 1
        if kind == "web_page":
            allowed = {"id", "kind", "role", "source_id", "url", "country"}
            if set(job) - allowed or job.get("role") != "landing_page":
                _error("unsupported_kind_role")
            source_id = _id(job.get("source_id"))
            if source_id in source_ids:
                _error("duplicate_source_id")
            source_ids.add(source_id)
            target = _canonical_url(job.get("url"), live=live)
            if live and urlsplit(target).query:
                _error("live_target_query_not_allowed")
            targets.append(target)
            country = job.get("country")
            if country is not None and not isinstance(country, str) or isinstance(country, str) and not re.fullmatch(r"[a-z]{2}", country):
                _error("invalid_country")
        else:
            count_key = "max_reviews" if kind == "amazon_reviews" else "num_of_comments"
            allowed = {"id", "kind", "role", "source_prefix", "urls", count_key}
            if set(job) != allowed or job.get("role") != "audience_language":
                _error("unsupported_kind_role")
            _id(job.get("source_prefix"), prefix=True)
            urls = job.get("urls")
            count = job.get(count_key)
            if not isinstance(urls, list) or not 1 <= len(urls) <= 2 or isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 25:
                _error("invalid_job")
            for value in urls:
                url = _canonical_url(value, live=live)
                parsed = urlsplit(url)
                if kind == "amazon_reviews":
                    if parsed.hostname not in {"amazon.com", "www.amazon.com"} or parsed.query or not re.fullmatch(r"/(?:dp|gp/product|product-reviews)/[A-Z0-9]{10}/?|/gp/customer-reviews/[A-Za-z0-9]{1,100}/?", parsed.path):
                        _error("invalid_amazon_url")
                else:
                    params = parse_qsl(parsed.query, keep_blank_values=True)
                    if parsed.hostname not in {"youtube.com", "www.youtube.com"} or parsed.path != "/watch" or len(params) != 1 or params[0][0] != "v" or not re.fullmatch(r"[A-Za-z0-9_-]{11}", params[0][1]):
                        _error("invalid_youtube_url")
                targets.append(url)
            requested_total += count * len(urls)
    if counts["web_page"] > 1 or counts["amazon_reviews"] > 1 or counts["youtube_comments"] > 1 or requested_total > 50:
        _error("manifest_scope_limit")
    return jobs, targets, requested_total


def plan(manifest: dict) -> dict:
    jobs, targets, requested = _validate_manifest(manifest, live=False)
    return {"schema_version": "1.0", "project": PROJECT, "manifest_sha256": _manifest_hash(manifest), "planned_requests": len(jobs), "requested_records": requested, "approved_targets_required": [redact_url(target) for target in targets], "requests_made": 0}


def validate_live_plan(manifest: dict) -> dict:
    """Validate live-only target restrictions without credentials or requests."""
    jobs, targets, requested = _validate_manifest(manifest, live=True)
    return {"schema_version": "1.0", "project": PROJECT, "manifest_sha256": _manifest_hash(manifest), "planned_requests": len(jobs), "requested_records": requested, "approved_targets_required": [redact_url(target) for target in targets], "requests_made": 0}


def _validate_approval(approval: dict, hashed: dict, targets: list[str], calls: int, requested: int, now: str) -> None:
    required = {"schema_version", "project", "manifest_sha256", "expires_at", "max_requests", "max_retained_records", "approved_urls", "account_budget_confirmed", "target_permissions_confirmed", "remote_resolution_risk_accepted"}
    if not isinstance(approval, dict) or set(approval) != required or approval.get("schema_version") != "1.0" or approval.get("project") != PROJECT:
        _error("invalid_approval")
    if approval.get("manifest_sha256") != _manifest_hash(hashed):
        _error("approval_hash_mismatch")
    expiry = _timestamp(approval.get("expires_at"), "approval_expiry")
    if datetime.fromisoformat(expiry[:-1] + "+00:00") <= datetime.fromisoformat(now[:-1] + "+00:00"):
        _error("approval_expired")
    max_requests = approval.get("max_requests")
    max_records = approval.get("max_retained_records")
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < calls or isinstance(max_records, bool) or not isinstance(max_records, int) or not 1 <= max_records <= 50 or requested > max_records:
        _error("approval_limit_exceeded")
    if any(approval.get(name) is not True for name in ("account_budget_confirmed", "target_permissions_confirmed", "remote_resolution_risk_accepted")):
        _error("approval_attestation_missing")
    approved = approval.get("approved_urls")
    if not isinstance(approved, list) or any(_canonical_url(url, live=True) != url for url in approved) or any(target not in approved for target in targets):
        _error("target_not_approved")


def _consume_approval(approval: dict, ledger_path, *, operation: str, now: str) -> None:
    """Atomically consume an approval fingerprint before the first request."""
    if not isinstance(ledger_path, (str, os.PathLike)):
        _error("approval_ledger_required")
    ledger = Path(ledger_path)
    try:
        ledger.mkdir(mode=0o700, parents=False, exist_ok=True)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(ledger, flags)
        if os.fstat(directory_fd).st_mode & 0o077:
            os.close(directory_fd)
            _error("approval_ledger_permissions")
    except OSError:
        _error("approval_ledger_error")
    fingerprint = _compact_hash(approval)
    marker = f"{fingerprint}.used"
    content = json.dumps(
        {
            "approval_sha256": fingerprint,
            "consumed_at": now,
            "max_requests": approval["max_requests"],
            "operation": operation,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    marker_fd = None
    try:
        marker_fd = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        remaining = memoryview(content)
        while remaining:
            written = os.write(marker_fd, remaining)
            if written <= 0:
                raise OSError("approval marker write failed")
            remaining = remaining[written:]
        os.fsync(marker_fd)
        os.fsync(directory_fd)
    except FileExistsError:
        _error("approval_replayed")
    except OSError:
        _error("approval_ledger_error")
    finally:
        if marker_fd is not None:
            os.close(marker_fd)
        os.close(directory_fd)


def _decode_json(response: HttpResponse, requests: int):
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        _error("invalid_response", provider=True, requests=requests)


def _check_response(response: HttpResponse, requests: int) -> None:
    if isinstance(response.status, bool) or not isinstance(response.status, int) or not isinstance(response.headers, dict) or not isinstance(response.body, bytes):
        _error("invalid_response", provider=True, requests=requests)
    headers = {str(k).casefold(): str(v) for k, v in response.headers.items()}
    raw_retry_after = headers.get("retry-after", "")
    retry_after = int(raw_retry_after) if raw_retry_after.isdigit() and 0 <= int(raw_retry_after) <= 86400 else None
    if response.status == 429:
        _error("rate_limited", provider=True, requests=requests, retry_after_seconds=retry_after)
    if 300 <= response.status < 400:
        _error("provider_http_error", provider=True, requests=requests)
    embedded = headers.get("x-brd-status-code") or headers.get("x-luminati-status-code")
    if embedded is not None:
        if not embedded.isdigit():
            _error("invalid_response", provider=True, requests=requests)
        if int(embedded) == 429:
            _error("rate_limited", provider=True, requests=requests, retry_after_seconds=retry_after)
        if not 200 <= int(embedded) < 300:
            _error("provider_target_error", provider=True, requests=requests)
    if any(key in headers for key in ("x-brd-error-code", "x-brd-err-code", "x-luminati-error-code", "x-brd-error", "x-brd-err-msg", "x-luminati-error")):
        _error("provider_target_error", provider=True, requests=requests)
    if not 200 <= response.status < 300:
        _error("provider_http_error", provider=True, requests=requests)
    if len(response.body) > MAX_BYTES:
        _error("response_too_large", provider=True, requests=requests)


def _job_receipt(job, state, requested, returned=0, retained=0, excluded=0, snapshot=None, error=None):
    urls = [job["url"]] if job.get("kind") == "web_page" else list(job.get("urls", []))
    safe_job = dict(job)
    if "url" in safe_job:
        safe_job["url"] = redact_url(safe_job["url"])
    if "urls" in safe_job:
        safe_job["urls"] = [redact_url(url) for url in safe_job["urls"]]
    approved_hashes = [url_sha256(url) for url in urls]
    return {
        "id": job["id"], "kind": job["kind"], "state": state,
        "original_job": safe_job, "approved_url_sha256": approved_hashes,
        "approved_url_binding_sha256": [
            hashlib.sha256(f"{safe_url}\0{approved_hash}".encode("utf-8")).hexdigest()
            for safe_url, approved_hash in zip(
                safe_job.get("urls", [safe_job.get("url")]), approved_hashes
            )
        ],
        "requested_records": requested, "returned_records": returned,
        "retained_records": retained, "excluded_records": excluded,
        "snapshot_id": snapshot, "error_code": error, "query_metadata": None,
    }


def _web_source_from_response(response: HttpResponse, job: dict, now: str) -> dict:
    try:
        text = response.body.decode("utf-8")
    except UnicodeError:
        _error("invalid_response", provider=True)
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            candidate = json.loads(stripped)
        except json.JSONDecodeError:
            candidate = None
        # Feature examples show a raw body, while the REST OpenAPI models an
        # envelope. Reject the envelope until an authorized live check settles it.
        if isinstance(candidate, dict) and {"status_code", "headers", "body"}.issubset(candidate):
            _error("response_contract_mismatch", provider=True)
    if stripped.casefold().startswith(("<!doctype html", "<html", "<body")):
        _error("unsupported_content_format", provider=True)
    canonical = _canonical_text(text) if text.strip() else ""
    if len(canonical) > 50000:
        _error("text_too_long", provider=True)
    heading = next(
        (re.sub(r"^#\s+", "", line).strip() for line in text.splitlines() if re.match(r"^#\s+", line)),
        "Selected public page",
    )
    return _source(
        sid=job["source_id"], kind="page", role=job["role"],
        url=redact_url(job["url"]), title=heading, text=canonical,
        observed_at=now, provenance="bright_data",
    )


def _collection_failure(
    *, error: BrightDataError, job: dict, requested, remaining_jobs: list[dict],
    sources: list[dict], receipts: list[dict], warnings: list[dict],
    returned: int, excluded: int, manifest_hash: str, requests: int,
) -> dict:
    receipts.append(_job_receipt(job, "failed", requested, error=error.code))
    for remaining in remaining_jobs:
        receipts.append(_job_receipt(remaining, "not_attempted", None))
    return _receipt(
        status="partial" if sources else "failed", sources=sources,
        returned=returned, excluded=excluded,
        warnings=warnings + [_warning(error.code)], manifest_hash=manifest_hash,
        requests=requests, jobs=receipts,
    )


def collect(manifest, *, approval, api_key, zones, transport, now, ledger_path) -> dict:
    jobs, targets, requested_total = _validate_manifest(manifest, live=True)
    now = _now(now)
    retained_upper_bound = requested_total + sum(job["kind"] == "web_page" for job in jobs)
    _validate_approval(approval, manifest, targets, len(jobs), retained_upper_bound, now)
    if not isinstance(api_key, str) or not api_key:
        _error("missing_api_key")
    if not callable(transport):
        _error("invalid_transport")
    if any(job["kind"] == "web_page" for job in jobs) and (not isinstance(zones, dict) or not zones.get("web_unlocker")):
        _error("missing_web_unlocker_zone")
    _consume_approval(approval, ledger_path, operation="collect", now=now)
    sources, receipts, warnings = [], [], []
    returned = excluded = requests = 0
    manifest_hash = _manifest_hash(manifest)
    for index, job in enumerate(jobs):
        job = dict(job)
        kind = job["kind"]
        if kind == "web_page":
            job["url"] = _canonical_url(job["url"], live=True)
        else:
            job["urls"] = [_canonical_url(url, live=True) for url in job["urls"]]
        requested = None if kind == "web_page" else (job.get("max_reviews") or job.get("num_of_comments")) * len(job["urls"])
        if kind == "web_page":
            body = {"zone": zones["web_unlocker"], "url": job["url"], "format": "raw", "data_format": "markdown"}
            if job.get("country") is not None:
                body["country"] = job["country"]
            endpoint = API_ROOT + "/request"
        else:
            dataset = AMAZON_DATASET if kind == "amazon_reviews" else YOUTUBE_DATASET
            count_key = "max_reviews" if kind == "amazon_reviews" else "num_of_comments"
            projection = "url|review_id|review_text|review_header|review_posted_date" if kind == "amazon_reviews" else "url|comment_id|comment_text|date_iso|date"
            body = {"input": [{"url": url, count_key: job[count_key]} for url in job["urls"]], "custom_output_fields": projection}
            endpoint = f"{API_ROOT}/datasets/v3/scrape?dataset_id={dataset}&format=json&include_errors=true"
        request = HttpRequest("POST", endpoint, {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(), 75)
        try:
            response = transport(request)
        except Exception as exc:
            if isinstance(exc, BrightDataError) and exc.code == "response_too_large":
                return _collection_failure(error=exc, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests + 1)
            receipts.append(_job_receipt(job, "completion_unknown", requested, error="transport_error"))
            for rest in jobs[index + 1:]:
                receipts.append(_job_receipt(rest, "not_attempted", None))
            return _receipt(status="completion_unknown", sources=sources, returned=returned, excluded=excluded, warnings=warnings + [_warning("transport_error")], manifest_hash=manifest_hash, requests=requests + 1, jobs=receipts)
        requests += 1
        if not isinstance(response, HttpResponse):
            failure = BrightDataError("invalid_response", provider_failure=True, requests_made=requests)
            return _collection_failure(error=failure, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
        try:
            _check_response(response, requests)
        except BrightDataError as error:
            if error.code in {"rate_limited", "response_contract_mismatch"} and not sources:
                error.receipt = _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
                raise
            return _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
        if response.status == 202 and kind != "web_page":
            try:
                data = _decode_json(response, requests)
            except BrightDataError as error:
                return _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
            snapshot = data.get("snapshot_id") if isinstance(data, dict) else None
            if not isinstance(snapshot, str) or not SNAPSHOT_RE.fullmatch(snapshot):
                error = BrightDataError("invalid_response", provider_failure=True, requests_made=requests)
                return _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
            receipts.append(_job_receipt(job, "pending", requested, snapshot=snapshot, error="pending_snapshot"))
            for rest in jobs[index + 1:]:
                receipts.append(_job_receipt(rest, "not_attempted", None))
            return _receipt(status="pending", sources=sources, returned=returned, excluded=excluded, warnings=warnings + [_warning("pending_snapshot")], manifest_hash=manifest_hash, requests=requests, jobs=receipts)
        if kind == "web_page":
            try:
                source = _web_source_from_response(response, job, now)
            except BrightDataError as error:
                error.requests_made = requests
                if error.code == "response_contract_mismatch" and not sources:
                    error.receipt = _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
                    raise
                return _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
            if len(sources) + 1 > approval["max_retained_records"]:
                _error("approval_limit_exceeded", requests=requests)
            sources.append(source)
            receipts.append(_job_receipt(job, "complete" if source["status"] == "collected" else "empty", None, returned=1, retained=1))
            returned += 1
        else:
            try:
                data = _decode_json(response, requests)
            except BrightDataError as error:
                return _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
            if not isinstance(data, list):
                error = BrightDataError("invalid_response", provider_failure=True, requests_made=requests)
                return _collection_failure(error=error, job=job, requested=requested, remaining_jobs=jobs[index + 1:], sources=sources, receipts=receipts, warnings=warnings, returned=returned, excluded=excluded, manifest_hash=manifest_hash, requests=requests)
            limit = min(requested, approval["max_retained_records"] - len(sources))
            normalized, stats = _normalize_records(kind, data, role=job["role"], source_url=job["urls"][0], observed_at=now, source_prefix=job["source_prefix"], provenance="bright_data", limit=limit, batch_urls=job["urls"])
            if len(sources) + len(normalized) > approval["max_retained_records"]:
                _error("approval_limit_exceeded", requests=requests)
            sources.extend(normalized)
            returned += stats["returned"]
            excluded += stats["excluded"]
            warnings.extend(stats["warnings"])
            if stats["provider_error_code"]:
                receipts.append(_job_receipt(job, "failed", requested, stats["returned"], stats["retained"], stats["excluded"], error=stats["provider_error_code"]))
                for rest in jobs[index + 1:]:
                    receipts.append(_job_receipt(rest, "not_attempted", None))
                return _receipt(status="partial" if sources else "failed", sources=sources, returned=returned, excluded=excluded, warnings=warnings, manifest_hash=manifest_hash, requests=requests, jobs=receipts)
            receipts.append(_job_receipt(job, "complete" if normalized else "empty", requested, stats["returned"], stats["retained"], stats["excluded"]))
            if stats["partial"] or len(data) > requested:
                if len(data) > requested:
                    warnings.append(_warning("provider_limit_exceeded"))
                for rest in jobs[index + 1:]:
                    receipts.append(_job_receipt(rest, "not_attempted", None))
                return _receipt(status="partial", sources=sources, returned=returned, excluded=excluded, warnings=warnings, manifest_hash=manifest_hash, requests=requests, jobs=receipts)
    return _receipt(status="complete", sources=sources, returned=returned, excluded=excluded, warnings=warnings, manifest_hash=manifest_hash, requests=requests, jobs=receipts)


def _validate_resume_receipt_unchecked(container) -> tuple[dict, dict, dict]:
    top_keys = {"schema_version", "project", "transport_contract_version", "sources", "receipt"}
    if not isinstance(container, dict) or set(container) != top_keys:
        _error("invalid_receipt")
    if container.get("schema_version") != "1.0" or container.get("project") != PROJECT or container.get("transport_contract_version") != "1.0" or not isinstance(container.get("sources"), list) or len(container["sources"]) > 100:
        _error("invalid_receipt")
    source_keys = {"id", "kind", "role", "url", "title", "text", "status", "observed_at", "published_at", "provider_date", "record_id", "record_id_origin", "provenance"}
    source_ids = set()
    allowed_source_pairs = {("page", "landing_page"), ("review", "audience_language"), ("question", "audience_language"), ("page", "approved_product_fact"), ("operator_note", "approved_product_fact"), ("operator_note", "context_note")}
    for source in container["sources"]:
        if not isinstance(source, dict) or set(source) != source_keys:
            _error("invalid_receipt")
        source_id = source.get("id")
        kind, role = source.get("kind"), source.get("role")
        if not isinstance(source_id, str) or not ID_RE.fullmatch(source_id) or source_id in source_ids or not isinstance(kind, str) or not isinstance(role, str) or (kind, role) not in allowed_source_pairs:
            _error("invalid_receipt")
        source_ids.add(source_id)
        title, text = source.get("title"), source.get("text")
        if not isinstance(title, str) or not 1 <= len(title) <= 200 or not isinstance(text, str):
            _error("invalid_receipt")
        text_limit = 50000 if kind == "page" else 5000 if kind in {"review", "question"} else 2000
        if len(text) > text_limit:
            _error("invalid_receipt")
        status = source.get("status")
        if not isinstance(status, str) or status not in {"collected", "empty", "unavailable", "pending"} or (status == "collected" and not text.strip()) or (status != "collected" and text):
            _error("invalid_receipt")
        url = source.get("url")
        if role == "context_note" or (kind == "operator_note"):
            if url is not None:
                _error("invalid_receipt")
        else:
            try:
                if _canonical_url(url, live=False) != url:
                    _error("invalid_receipt")
            except BrightDataError:
                _error("invalid_receipt")
        try:
            _timestamp(source.get("observed_at"), "receipt_source_date")
            if source.get("published_at") is not None:
                _timestamp(source["published_at"], "receipt_source_date")
        except BrightDataError:
            _error("invalid_receipt")
        provider_date, record_id, origin = source.get("provider_date"), source.get("record_id"), source.get("record_id_origin")
        if provider_date is not None and (not isinstance(provider_date, str) or len(provider_date) > 100):
            _error("invalid_receipt")
        if not isinstance(origin, str) or origin not in {"provider", "operator", "content_hash", "none"} or ((origin == "none") != (record_id is None)):
            _error("invalid_receipt")
        if record_id is not None and (not isinstance(record_id, str) or not 1 <= len(record_id) <= 200):
            _error("invalid_receipt")
        if not isinstance(source.get("provenance"), str) or source["provenance"] not in {"synthetic_fixture", "operator_supplied", "bright_data"}:
            _error("invalid_receipt")
    inner = container.get("receipt")
    receipt_keys = {"schema_version", "project", "manifest_sha256", "status", "requests_made", "returned_records", "retained_records", "excluded_records", "jobs", "warnings", "provider_cost_usd"}
    if not isinstance(inner, dict) or set(inner) != receipt_keys:
        _error("invalid_receipt")
    if inner.get("schema_version") != "1.0" or inner.get("project") != PROJECT or inner.get("status") != "pending" or inner.get("provider_cost_usd") is not None:
        _error("invalid_receipt")
    if not isinstance(inner.get("manifest_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", inner["manifest_sha256"]):
        _error("invalid_receipt")
    for key in ("requests_made", "returned_records", "retained_records", "excluded_records"):
        value = inner.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _error("invalid_receipt")
    if inner["retained_records"] != len(container["sources"]) or not isinstance(inner.get("warnings"), list) or not isinstance(inner.get("jobs"), list):
        _error("invalid_receipt")
    job_keys = {"id", "kind", "state", "original_job", "approved_url_sha256", "approved_url_binding_sha256", "requested_records", "returned_records", "retained_records", "excluded_records", "snapshot_id", "error_code", "query_metadata"}
    receipt_job_ids = set()
    for job_receipt in inner["jobs"]:
        if not isinstance(job_receipt, dict) or set(job_receipt) != job_keys:
            _error("invalid_receipt")
        jid, kind, state = job_receipt.get("id"), job_receipt.get("kind"), job_receipt.get("state")
        if not isinstance(jid, str) or not ID_RE.fullmatch(jid) or jid in receipt_job_ids or not isinstance(kind, str) or kind not in {"web_page", "amazon_reviews", "youtube_comments"} or not isinstance(state, str) or state not in {"complete", "empty", "failed", "pending", "completion_unknown", "not_attempted"}:
            _error("invalid_receipt")
        receipt_job_ids.add(jid)
        for key in ("returned_records", "retained_records", "excluded_records"):
            value = job_receipt.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _error("invalid_receipt")
        if job_receipt["retained_records"] > job_receipt["returned_records"]:
            _error("invalid_receipt")
        original = job_receipt.get("original_job")
        hashes = job_receipt.get("approved_url_sha256")
        bindings = job_receipt.get("approved_url_binding_sha256")
        if (
            not isinstance(original, dict)
            or not isinstance(hashes, list)
            or not isinstance(bindings, list)
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in bindings)
        ):
            _error("invalid_receipt")
        if job_receipt.get("query_metadata") is not None:
            _error("invalid_receipt")
        snapshot_id = job_receipt.get("snapshot_id")
        if (state == "pending") != (snapshot_id is not None):
            _error("invalid_receipt")
        if snapshot_id is not None and (not isinstance(snapshot_id, str) or not SNAPSHOT_RE.fullmatch(snapshot_id)):
            _error("invalid_receipt")
        requested_count = job_receipt.get("requested_records")
        error_code = job_receipt.get("error_code")
        if state == "not_attempted":
            if requested_count is not None or error_code is not None:
                _error("invalid_receipt")
        elif kind == "web_page":
            if requested_count is not None:
                _error("invalid_receipt")
        elif isinstance(requested_count, bool) or not isinstance(requested_count, int) or requested_count < 1:
            _error("invalid_receipt")
        allowed_errors = {"provider_http_error", "provider_target_error", "invalid_response", "response_contract_mismatch", "response_too_large", "unsupported_content_format", "transport_error", "pending_snapshot", "provider_limit_exceeded", "conflicting_record", "invalid_record", "text_too_long", "rate_limited", "record_error", "dead_page", "bucket_rate_limit", "global_rate_limit"}
        if error_code is not None and (not isinstance(error_code, str) or error_code not in allowed_errors):
            _error("invalid_receipt")
        if state in {"failed", "completion_unknown"} and error_code is None:
            _error("invalid_receipt")
        if state == "pending" and error_code != "pending_snapshot":
            _error("invalid_receipt")
        if state in {"complete", "empty", "not_attempted"} and error_code is not None:
            _error("invalid_receipt")
        if kind == "web_page":
            if set(original) - {"id", "kind", "role", "source_id", "url", "country"} or not {"id", "kind", "role", "source_id", "url"} <= set(original) or original.get("role") != "landing_page":
                _error("invalid_receipt")
            try:
                _id(original.get("id"))
                _id(original.get("source_id"))
                if _canonical_url(original.get("url"), live=False) != original["url"]:
                    _error("invalid_receipt")
            except BrightDataError:
                _error("invalid_receipt")
            expected_binding = hashlib.sha256(f"{original['url']}\0{hashes[0]}".encode("utf-8")).hexdigest() if len(hashes) == 1 else None
            if len(hashes) != 1 or hashes[0] != url_sha256(original["url"]) or bindings != [expected_binding]:
                _error("invalid_receipt")
        else:
            count_key = "max_reviews" if kind == "amazon_reviews" else "num_of_comments"
            if set(original) != {"id", "kind", "role", "source_prefix", "urls", count_key} or original.get("kind") != kind or original.get("role") != "audience_language" or not isinstance(original.get("urls"), list) or not 1 <= len(original["urls"]) <= 2 or len(hashes) != len(original["urls"]) or len(bindings) != len(hashes):
                _error("invalid_receipt")
            try:
                _id(original.get("id"))
                _id(original.get("source_prefix"), prefix=True)
            except BrightDataError:
                _error("invalid_receipt")
            per_url = original.get(count_key)
            if isinstance(per_url, bool) or not isinstance(per_url, int) or not 1 <= per_url <= 25 or (state != "not_attempted" and requested_count != per_url * len(original["urls"])):
                _error("invalid_receipt")
            if kind == "youtube_comments":
                # Receipts redact the required video ID, so the approved URL hash cannot
                # be checked against an authoritative target before resuming.
                _error("invalid_receipt")
            for index, original_url in enumerate(original["urls"]):
                try:
                    canonical_url = _canonical_url(original_url, live=False)
                    parsed_url = urlsplit(canonical_url)
                    valid_url = parsed_url.hostname in {"amazon.com", "www.amazon.com"} and not parsed_url.query and bool(re.fullmatch(r"/(?:dp|gp/product|product-reviews)/[A-Z0-9]{10}/?|/gp/customer-reviews/[A-Za-z0-9]{1,100}/?", parsed_url.path))
                    if not valid_url:
                        _error("invalid_receipt")
                    expected_binding = hashlib.sha256(f"{canonical_url}\0{hashes[index]}".encode("utf-8")).hexdigest()
                    if bindings[index] != expected_binding:
                        _error("invalid_receipt")
                except BrightDataError:
                    _error("invalid_receipt")
                if hashes[index] != url_sha256(canonical_url):
                    _error("invalid_receipt")
    if (
        sum(job["returned_records"] for job in inner["jobs"]) != inner["returned_records"]
        or sum(job["retained_records"] for job in inner["jobs"]) != inner["retained_records"]
        or sum(job["excluded_records"] for job in inner["jobs"]) != inner["excluded_records"]
    ):
        _error("invalid_receipt")
    pending = [job for job in inner["jobs"] if job.get("state") == "pending" and job.get("snapshot_id")]
    if len(pending) != 1:
        _error("invalid_receipt")
    job_receipt = pending[0]
    if job_receipt.get("kind") != "amazon_reviews" or not isinstance(job_receipt.get("snapshot_id"), str) or not SNAPSHOT_RE.fullmatch(job_receipt["snapshot_id"]):
        _error("invalid_receipt")
    requested = job_receipt.get("requested_records")
    hashes = job_receipt.get("approved_url_sha256")
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1 or not isinstance(hashes, list) or not 1 <= len(hashes) <= 2 or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
        _error("invalid_receipt")
    job = job_receipt.get("original_job")
    count_key = "max_reviews" if job_receipt["kind"] == "amazon_reviews" else "num_of_comments"
    if not isinstance(job, dict) or set(job) != {"id", "kind", "role", "source_prefix", "urls", count_key} or job.get("kind") != job_receipt["kind"] or job.get("role") != "audience_language" or not isinstance(job.get("urls"), list) or len(job["urls"]) != len(hashes):
        _error("invalid_receipt")
    try:
        _id(job.get("id"))
        _id(job.get("source_prefix"), prefix=True)
    except BrightDataError:
        _error("invalid_receipt")
    count = job.get(count_key)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 25 or count * len(job["urls"]) != requested:
        _error("invalid_receipt")
    for url in job["urls"]:
        try:
            canonical = _canonical_url(url, live=False)
            parsed = urlsplit(canonical)
            if job_receipt["kind"] == "amazon_reviews":
                valid = parsed.hostname in {"amazon.com", "www.amazon.com"} and not parsed.query and bool(re.fullmatch(r"/(?:dp|gp/product|product-reviews)/[A-Z0-9]{10}/?|/gp/customer-reviews/[A-Za-z0-9]{1,100}/?", parsed.path))
            else:
                params = parse_qsl(parsed.query, keep_blank_values=True)
                valid = parsed.hostname in {"youtube.com", "www.youtube.com"} and parsed.path == "/watch" and len(params) == 1 and params[0][0] == "v" and bool(re.fullmatch(r"[A-Za-z0-9_-]{11}|REDACTED", params[0][1]))
            if not valid:
                _error("invalid_receipt")
        except BrightDataError:
            _error("invalid_receipt")
    return inner, job_receipt, job


def _validate_resume_receipt(container) -> tuple[dict, dict, dict]:
    try:
        return _validate_resume_receipt_unchecked(container)
    except BrightDataError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, IndexError):
        _error("invalid_receipt")


def _resume_failure(error: BrightDataError, container: dict, inner: dict, job_receipt: dict, job: dict) -> dict:
    failed_job = {
        **job_receipt,
        "state": "failed",
        "error_code": error.code,
        "returned_records": 0,
        "retained_records": 0,
        "excluded_records": 0,
        "snapshot_id": None,
    }
    jobs = [failed_job if prior["id"] == job_receipt["id"] else prior for prior in inner["jobs"]]
    error.receipt = _receipt(
        status="partial" if container["sources"] else "failed",
        sources=container["sources"], returned=inner["returned_records"],
        excluded=inner["excluded_records"], warnings=inner["warnings"] + [_warning(error.code)],
        manifest_hash=inner["manifest_sha256"], requests=inner["requests_made"] + 1,
        jobs=jobs,
    )
    return error


def resume(receipt, *, approval, api_key, transport, now, ledger_path) -> dict:
    container = receipt
    inner, job_receipt, job = _validate_resume_receipt(container)
    pending = [job for job in inner.get("jobs", []) if job.get("state") == "pending" and job.get("snapshot_id")]
    download = f"{API_ROOT}/datasets/v3/snapshot/{job_receipt['snapshot_id']}?format=json"
    now = _now(now)
    existing_sources = container.get("sources", [])
    requested_records = job_receipt.get("requested_records") or 0
    _validate_approval(approval, receipt, [download], 1, len(existing_sources) + requested_records, now)
    if not api_key or not callable(transport):
        _error("missing_api_key")
    _consume_approval(approval, ledger_path, operation="resume", now=now)
    request = HttpRequest("GET", download, {"Authorization": f"Bearer {api_key}"}, b"", 75)
    try:
        response = transport(request)
    except Exception:
        unknown_job = {
            **job_receipt,
            "state": "completion_unknown",
            "error_code": "transport_error",
            "returned_records": 0,
            "retained_records": 0,
            "excluded_records": 0,
            "snapshot_id": None,
        }
        jobs = [unknown_job if prior["id"] == job_receipt["id"] else prior for prior in inner["jobs"]]
        return _receipt(status="completion_unknown", sources=container["sources"], returned=inner["returned_records"], excluded=inner["excluded_records"], warnings=inner["warnings"] + [_warning("transport_error")], manifest_hash=inner["manifest_sha256"], requests=inner["requests_made"] + 1, jobs=jobs)
    if not isinstance(response, HttpResponse):
        raise _resume_failure(BrightDataError("invalid_response", provider_failure=True, requests_made=1), container, inner, job_receipt, job)
    if response.status in {202, 409}:
        try:
            _check_response(HttpResponse(202, response.headers, response.body), 1)
        except BrightDataError as error:
            raise _resume_failure(error, container, inner, job_receipt, job)
        pending_job = {**job_receipt, "state": "pending", "error_code": "pending_snapshot"}
        jobs = [pending_job if prior["id"] == job_receipt["id"] else prior for prior in inner["jobs"]]
        return _receipt(status="pending", sources=container["sources"], returned=inner["returned_records"], excluded=inner["excluded_records"], warnings=inner["warnings"] + [_warning("pending_snapshot")], manifest_hash=inner["manifest_sha256"], requests=inner["requests_made"] + 1, jobs=jobs)
    try:
        _check_response(response, 1)
        data = _decode_json(response, 1)
    except BrightDataError as error:
        raise _resume_failure(error, container, inner, job_receipt, job)
    kind = job["kind"]
    normalized, stats = _normalize_records(
        kind, data, role=job["role"], source_url=job["urls"][0], observed_at=now,
        source_prefix=job["source_prefix"], provenance="bright_data",
        limit=job_receipt["requested_records"], batch_urls=job["urls"],
        approved_url_hashes=job_receipt.get("approved_url_sha256"),
    )
    if len(existing_sources) + len(normalized) > approval["max_retained_records"]:
        _error("approval_limit_exceeded", requests=1)
    resumed_job = {
        **job_receipt,
        "state": "complete" if normalized else "empty",
        "error_code": None,
        "returned_records": stats["returned"],
        "retained_records": stats["retained"],
        "excluded_records": stats["excluded"],
        "snapshot_id": None,
    }
    status = "partial" if stats["partial"] else "complete"
    if stats["provider_error_code"]:
        resumed_job["state"] = "failed"
        resumed_job["error_code"] = stats["provider_error_code"]
        status = "partial" if existing_sources or normalized else "failed"
    jobs = [resumed_job if prior["id"] == job_receipt["id"] else prior for prior in inner["jobs"]]
    return _receipt(status=status, sources=existing_sources + normalized, returned=inner["returned_records"] + stats["returned"], excluded=inner["excluded_records"] + stats["excluded"], warnings=inner["warnings"] + stats["warnings"], manifest_hash=inner["manifest_sha256"], requests=inner["requests_made"] + 1, jobs=jobs)


class _NoRedirect(HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        raise HTTPError(req.full_url, code, msg, headers, fp)
    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def _read_bounded(stream, deadline: float) -> bytes:
    chunks = []
    total = 0
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise TransportError("transport_error")
        raw = getattr(getattr(stream, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            sock.settimeout(remaining_seconds)
        chunk = stream.read(min(65536, MAX_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_BYTES:
            raise TransportError("response_too_large")


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """Production stdlib transport: verified TLS, no proxy/redirect, 2 MiB cap."""
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
    raw = Request(request.url, data=request.body if request.method != "GET" else None, headers=request.headers, method=request.method)
    deadline = time.monotonic() + request.timeout_seconds
    try:
        with opener.open(raw, timeout=request.timeout_seconds) as response:
            body = _read_bounded(response, deadline)
            return HttpResponse(response.status, dict(response.headers.items()), body)
    except HTTPError as exc:
        body = _read_bounded(exc, deadline)
        return HttpResponse(exc.code, dict(exc.headers.items()) if exc.headers else {}, body)
    except (URLError, TimeoutError, socket.timeout, OSError):
        raise TransportError()
