"""Shared URL secret detection and artifact-safe redaction."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

SENSITIVE_QUERY_KEYS = {
    "accesstoken",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "credentials",
    "password",
    "sas",
    "session",
    "sig",
    "signature",
    "secret",
    "securitytoken",
    "sv",
    "token",
}
SENSITIVE_QUERY_PREFIXES = ("xamz", "xgoog", "xms", "aws")


def _decode_repeatedly(value: str) -> str:
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def normalized_query_key(value: str) -> str:
    """Normalize percent-encoded vendor keys for security comparisons."""
    return re.sub(r"[^a-z0-9]", "", _decode_repeatedly(value).casefold())


def has_sensitive_query(url: str) -> bool:
    query = urlsplit(url).query
    for raw_pair in query.split("&") if query else ():
        raw_key = raw_pair.split("=", 1)[0]
        key = normalized_query_key(raw_key)
        if key in SENSITIVE_QUERY_KEYS or key.startswith(SENSITIVE_QUERY_PREFIXES):
            return True
    return False


def redact_url(url: str | None) -> str | None:
    """Replace every query value while preserving only decoded parameter names."""
    if url is None:
        return None
    parsed = urlsplit(url)
    if not parsed.query:
        return url
    keys = [key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    redacted = urlencode([(key, "REDACTED") for key in keys], doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted, parsed.fragment))


def url_sha256(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def opaque_provider_record_id(record_id: str) -> str:
    """Keep provider IDs matchable without exposing their raw value in artifacts."""
    if re.fullmatch(r"provider-sha256-[0-9a-f]{64}", record_id):
        return record_id
    return "provider-sha256-" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()
