"""Pure validation and deterministic rewrite analysis."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from .security import opaque_provider_record_id, redact_url

PROJECT = "customer-led-page-rewrite"
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
SENTENCE_RE = re.compile(r".*?(?:[.?!](?=\s|$)|$)", re.S)


class InputError(ValueError):
    """Safe, operator-actionable input error."""

    code = "invalid_input"


def _fail(message: str) -> None:
    raise InputError(message)


def _obj(value, name: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    return value


def _list(value, name: str, low: int, high: int) -> list:
    if not isinstance(value, list) or not low <= len(value) <= high:
        _fail(f"{name} must contain {low}..{high} items")
    return value


def _string(value, name: str, low: int, high: int) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high or not value.strip():
        _fail(f"{name} must be a non-blank string of length {low}..{high}")
    if "\x00" in value or any(ord(c) < 32 and c not in "\t\n\r" for c in value):
        _fail(f"{name} contains unsupported control characters")
    return value


def _id(value, name: str) -> str:
    value = _string(value, name, 1, 64)
    if not ID_RE.fullmatch(value):
        _fail(f"{name} is not a valid ID")
    return value


def _timestamp(value, name: str) -> str:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        _fail(f"{name} must be a UTC RFC3339 timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(f"{name} is not a valid timestamp")
    return value


def _canonical_url(value, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        _fail(f"{name} must be an HTTPS URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _fail(f"{name} must be an HTTPS URL")
    if parsed.scheme.lower() != "https" or not parsed.hostname or "@" in parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        _fail(f"{name} must be credential-free HTTPS without a fragment")
    if port not in (None, 443):
        _fail(f"{name} may only use port 443")
    host = parsed.hostname.lower().rstrip(".")
    netloc = host if port is None or port == 443 else f"{host}:{port}"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, ""))


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _compare(value: str) -> str:
    return _collapse(value).casefold()


def _phrase_hit(text: str, phrase: str) -> int | None:
    haystack, needle = _compare(text), _compare(phrase)
    start = 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return None
        before_ok = not needle[0].isalnum() or at == 0 or not haystack[at - 1].isalnum()
        end = at + len(needle)
        after_ok = not needle[-1].isalnum() or end == len(haystack) or not haystack[end].isalnum()
        if before_ok and after_ok:
            return at
        start = at + 1


def _blocks(text: str) -> tuple[str, list[dict]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text or any(ord(c) < 32 and c not in "\t\n" for c in text):
        _fail("source text contains unsupported control characters")
    stripped = text.lstrip().casefold()
    if stripped.startswith(("<!doctype html", "<html", "<body")):
        _fail("unsupported_content_format")
    chunks: list[tuple[str, int | None]] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            normalized = _collapse("\n".join(current))
            if normalized:
                chunks.append((normalized, None))
            current.clear()

    for line in text.split("\n"):
        heading = HEADING_RE.fullmatch(line.strip())
        if heading:
            flush()
            chunks.append((_collapse(heading.group(2)), len(heading.group(1))))
        elif not line.strip():
            flush()
        else:
            current.append(line)
    flush()
    blocks = [
        {"id": f"b{i:04d}", "text": value, "heading_level": level}
        for i, (value, level) in enumerate(chunks, 1)
    ]
    return "\n\n".join(item["text"] for item in blocks), blocks


def _sentences(block: dict) -> list[str]:
    if block["heading_level"] is not None:
        return []
    return [m.group(0).strip() for m in SENTENCE_RE.finditer(block["text"]) if m.group(0).strip()]


def _excerpt(text: str, hit: int = 0, phrase: str | None = None) -> str:
    if len(text) <= 240:
        return text
    start = max(0, hit - 80)
    if phrase is not None and len(phrase) <= 240 and start + 240 < hit + len(phrase):
        start = hit + len(phrase) - 240
    return text[start : start + 240]


def _citation(source_id: str, block_id: str, quote: str) -> dict:
    return {"source_id": source_id, "block_id": block_id, "quote": quote}


def _normalize_source(raw: dict, seen: set[str]) -> dict:
    raw = _obj(raw, "source")
    allowed = {
        "id", "kind", "role", "url", "title", "text", "status", "observed_at",
        "published_at", "provider_date", "record_id", "record_id_origin",
        "provenance",
    }
    unknown = set(raw) - allowed
    if unknown:
        _fail(f"source has unknown keys: {', '.join(sorted(unknown))}")
    required = {"id", "kind", "role", "url", "title", "text", "status", "observed_at", "published_at", "provider_date", "record_id", "record_id_origin", "provenance"}
    missing = required - set(raw)
    if missing:
        _fail(f"source is missing required keys: {', '.join(sorted(missing))}")
    sid = _id(raw.get("id"), "source.id")
    if sid in seen:
        _fail(f"duplicate source ID: {sid}")
    seen.add(sid)
    kind = raw.get("kind")
    role = raw.get("role")
    pairs = {
        ("page", "landing_page"), ("review", "audience_language"),
        ("question", "audience_language"), ("page", "approved_product_fact"),
        ("operator_note", "approved_product_fact"), ("operator_note", "context_note"),
    }
    if (kind, role) not in pairs:
        _fail(f"unsupported source kind/role for {sid}")
    title = _string(raw.get("title"), f"source {sid} title", 1, 200)
    url = _canonical_url(raw.get("url"), f"source {sid} url", nullable=kind == "operator_note")
    if kind != "operator_note" and url is None:
        _fail(f"source {sid} requires a URL")
    text = raw.get("text")
    if text is not None and not isinstance(text, str):
        _fail(f"source {sid} text must be a string or null")
    limit = 50000 if kind == "page" else 5000 if kind in {"review", "question"} else 2000
    if isinstance(text, str) and len(text) > limit:
        _fail(f"source {sid} text is too long")
    status = raw.get("status")
    if text is None:
        status = "unavailable"
        text = ""
    if status not in {"collected", "empty", "unavailable", "pending"}:
        _fail(f"source {sid} has invalid status")
    if status == "collected" and (not isinstance(text, str) or not text.strip()):
        _fail(f"collected source {sid} requires text")
    if status != "collected" and isinstance(text, str) and text:
        _fail(f"non-collected source {sid} must have empty text")
    canonical, blocks = ("", []) if status != "collected" else _blocks(text)
    observed = raw.get("observed_at")
    observed = _timestamp(observed, f"source {sid} observed_at")
    published = raw.get("published_at")
    if published is not None:
        published = _timestamp(published, f"source {sid} published_at")
    provider_date = raw.get("provider_date")
    if provider_date is not None and (not isinstance(provider_date, str) or len(provider_date) > 100):
        _fail(f"source {sid} provider_date is invalid")
    record_id = raw.get("record_id")
    origin = raw.get("record_id_origin")
    if origin not in {"provider", "operator", "content_hash", "none"}:
        _fail(f"source {sid} record_id_origin is invalid")
    if (origin == "none") != (record_id is None):
        _fail(f"source {sid} record ID and origin disagree")
    if record_id is not None:
        _string(record_id, f"source {sid} record_id", 1, 200)
        if origin == "provider":
            record_id = opaque_provider_record_id(record_id)
    provenance = raw.get("provenance")
    if provenance not in {"synthetic_fixture", "operator_supplied", "bright_data"}:
        _fail(f"source {sid} provenance is invalid")
    return {
        "id": sid, "kind": kind, "role": role, "url": url, "title": title,
        "status": status, "observed_at": observed, "published_at": published,
        "provider_date": provider_date, "record_id": record_id,
        "record_id_origin": origin, "provenance": provenance,
        "canonical_text": canonical, "blocks": blocks,
        "content_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def _validate_fact_citation(raw: dict, sources: dict, fact_text: str) -> dict:
    raw = _obj(raw, "fact evidence")
    if set(raw) - {"source_id", "block_id", "quote"}:
        _fail("fact evidence contains unknown keys")
    sid = _id(raw.get("source_id"), "fact evidence source_id")
    source = sources.get(sid)
    if source is None or source["role"] != "approved_product_fact":
        _fail(f"fact evidence references invalid source {sid}")
    block_id = raw.get("block_id")
    if not isinstance(block_id, str) or not re.fullmatch(r"b\d{4}", block_id):
        _fail("fact evidence block_id is invalid")
    block = next((b for b in source["blocks"] if b["id"] == block_id), None)
    quote = _string(raw.get("quote"), "fact evidence quote", 1, 240)
    if block is None or quote not in block["text"]:
        _fail("fact evidence quote is stale or does not match its block")
    return _citation(sid, block_id, quote)


def _section(source: dict, heading: str) -> tuple[str, list[dict]]:
    matches = [i for i, b in enumerate(source["blocks"]) if b["heading_level"] is not None and _compare(b["text"]) == _compare(heading)]
    if not matches:
        return "new_section", []
    if len(matches) > 1:
        return "ambiguous", []
    start = matches[0]
    level = source["blocks"][start]["heading_level"]
    body = []
    for block in source["blocks"][start + 1 :]:
        if block["heading_level"] is not None and block["heading_level"] <= level:
            break
        if block["heading_level"] is None:
            body.append(block)
    return "existing_section", body


def analyze(payload: dict) -> dict:
    """Validate and analyze one payload without I/O, environment, or network access."""
    payload = _obj(payload, "payload")
    if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) > 2 * 1024 * 1024:
        _fail("input exceeds 2 MiB")
    allowed = {"schema_version", "project", "sources", "as_of", "product", "page_source_id", "topics", "facts", "headline_topic_id"}
    unknown = set(payload) - allowed
    if unknown:
        _fail(f"payload has unknown keys: {', '.join(sorted(unknown))}")
    if "schema_version" not in payload or "project" not in payload:
        _fail("schema_version and project are required")
    if payload.get("schema_version") != "1.0":
        _fail("schema_version must be 1.0")
    if payload.get("project") != PROJECT:
        _fail(f"project must be {PROJECT}")
    source_values = _list(payload.get("sources"), "sources", 1, 100)
    product = _string(payload.get("product"), "product", 1, 120)
    seen: set[str] = set()
    normalized = [_normalize_source(value, seen) for value in source_values]
    dedup_warnings = []
    conclusion_excluded: set[str] = set()
    record_keys: dict[tuple, dict] = {}
    for source in normalized:
        if source["kind"] not in {"review", "question"}:
            continue
        local_id = source["record_id"] or source["content_sha256"]
        key = (source["kind"], source["url"], local_id)
        previous = record_keys.get(key)
        if previous is None:
            record_keys[key] = source
        elif previous["canonical_text"] == source["canonical_text"]:
            conclusion_excluded.add(source["id"])
            dedup_warnings.append({"code": "duplicate_record", "source_ids": [previous["id"], source["id"]], "note": "Identical record identity and text were counted once."})
        else:
            conclusion_excluded.update({previous["id"], source["id"]})
            dedup_warnings.append({"code": "conflicting_record", "source_ids": [previous["id"], source["id"]], "note": "Conflicting text for one record identity was excluded from conclusions."})
    sources = {source["id"]: source for source in normalized}
    page_id = _id(payload.get("page_source_id"), "page_source_id")
    page = sources.get(page_id)
    if page is None or page["kind"] != "page" or page["role"] != "landing_page":
        _fail("page_source_id must reference the landing page")
    if sum(s["role"] == "landing_page" for s in normalized) != 1:
        _fail("exactly one landing page is required")
    if sum(s["role"] == "audience_language" for s in normalized) > 50:
        _fail("at most 50 audience sources are allowed")
    approved_fact_source_count = sum(s["role"] == "approved_product_fact" for s in normalized)
    context_count = sum(s["role"] == "context_note" for s in normalized)
    if approved_fact_source_count > 10:
        _fail("at most 10 approved_product_fact sources are allowed")
    if context_count > 5:
        _fail("at most 5 context_note sources are allowed")
    topics_raw = _list(payload.get("topics"), "topics", 1, 8)
    facts_raw = _list(payload.get("facts", []), "facts", 0, 20)
    topic_ids: set[str] = set()
    topics = []
    for raw in topics_raw:
        raw = _obj(raw, "topic")
        if set(raw) != {"id", "question", "match_any", "target_heading", "fact_ids"}:
            _fail("topic keys do not match the contract")
        tid = _id(raw["id"], "topic.id")
        if tid in topic_ids:
            _fail(f"duplicate topic ID: {tid}")
        topic_ids.add(tid)
        phrases = _list(raw["match_any"], "topic.match_any", 1, 8)
        phrases = [_string(v, "topic phrase", 1, 80) for v in phrases]
        fact_ids = _list(raw["fact_ids"], "topic.fact_ids", 0, 5)
        if len(set(fact_ids)) != len(fact_ids):
            _fail("topic fact IDs must be unique")
        topics.append({"id": tid, "question": _string(raw["question"], "topic.question", 1, 160), "match_any": phrases, "target_heading": _string(raw["target_heading"], "topic.target_heading", 1, 120), "fact_ids": [_id(v, "topic.fact_id") for v in fact_ids]})
    fact_ids: set[str] = set()
    facts = {}
    for raw in facts_raw:
        raw = _obj(raw, "fact")
        if set(raw) != {"id", "topic_id", "claim_key", "text", "approval", "evidence"}:
            _fail("fact keys do not match the contract")
        fid = _id(raw["id"], "fact.id")
        if fid in fact_ids:
            _fail(f"duplicate fact ID: {fid}")
        fact_ids.add(fid)
        tid = _id(raw["topic_id"], "fact.topic_id")
        if tid not in topic_ids:
            _fail(f"fact {fid} has a dangling topic")
        text = _collapse(_string(raw["text"], "fact.text", 1, 240))
        evidence = [_validate_fact_citation(v, sources, text) for v in _list(raw["evidence"], "fact.evidence", 1, 3)]
        if not any(c["quote"] == text for c in evidence):
            _fail(f"fact {fid} lacks a complete matching citation")
        approval = raw["approval"]
        if approval not in {"approved", "unverified", "withdrawn"}:
            _fail(f"fact {fid} approval is invalid")
        facts[fid] = {"id": fid, "topic_id": tid, "claim_key": _id(raw["claim_key"], "fact.claim_key"), "text": text, "approval": approval, "evidence": evidence}
    if facts and approved_fact_source_count < 1:
        _fail("facts require at least one approved_product_fact source")
    global_claim_texts: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["approval"] == "approved":
            global_claim_texts.setdefault(fact["claim_key"], set()).add(fact["text"])
    global_conflicts = {
        claim_key for claim_key, texts in global_claim_texts.items() if len(texts) > 1
    }
    for topic in topics:
        for fid in topic["fact_ids"]:
            if fid not in facts or facts[fid]["topic_id"] != topic["id"]:
                _fail(f"topic {topic['id']} has an invalid fact reference")
    headline_topic_id = _id(payload.get("headline_topic_id"), "headline_topic_id")
    if headline_topic_id not in topic_ids:
        _fail("headline_topic_id is dangling")
    as_of = payload.get("as_of")
    if as_of is not None:
        as_of = _timestamp(as_of, "as_of")
    elif normalized:
        as_of = max(
            normalized,
            key=lambda source: datetime.fromisoformat(source["observed_at"][:-1] + "+00:00"),
        )["observed_at"]

    warnings = list(dedup_warnings)
    if as_of:
        current = datetime.fromisoformat(as_of[:-1] + "+00:00")
        stale = [s["id"] for s in normalized if current - datetime.fromisoformat(s["observed_at"][:-1] + "+00:00") > timedelta(days=30)]
        if stale:
            warnings.append({"code": "stale_source", "source_ids": stale, "note": "These snapshots are more than 30 days older than as_of."})
    audience_sources = [s for s in normalized if s["role"] == "audience_language" and s["status"] == "collected" and s["id"] not in conclusion_excluded]
    topic_rows = []
    faq_edits = []
    proof_needed = []
    eligible_by_topic: dict[str, list[dict]] = {}
    for topic in topics:
        audience_refs = []
        observed = False
        verbatim = []
        for source in audience_sources:
            for block in source["blocks"]:
                for sentence in _sentences(block):
                    phrase_positions = [_phrase_hit(sentence, phrase) for phrase in topic["match_any"]]
                    hits = [(position, phrase) for phrase, position in zip(topic["match_any"], phrase_positions) if position is not None]
                    if hits and len(audience_refs) < 3:
                        position, phrase = min(hits, key=lambda hit: hit[0])
                        audience_refs.append(_citation(source["id"], block["id"], _excerpt(sentence, position, phrase)))
                    if _phrase_hit(sentence, topic["question"]) is not None:
                        observed = True
                        if sentence not in verbatim:
                            verbatim.append(sentence)
        origin = "observed" if observed else "operator_framed_from_observed_language" if audience_refs else "operator_inferred"
        section_kind, section_blocks = ("unavailable", []) if page["status"] != "collected" else _section(page, topic["target_heading"])
        selected_facts = [facts[fid] for fid in topic["fact_ids"]]
        approved = [fact for fact in selected_facts if fact["approval"] == "approved"]
        conflicts = {fact["claim_key"] for fact in approved if fact["claim_key"] in global_conflicts}
        eligible = [fact for fact in approved if fact["claim_key"] not in conflicts]
        eligible_by_topic[topic["id"]] = eligible
        fact_refs = [citation for fact in eligible for citation in fact["evidence"]]
        page_answer_refs = []
        related_copy_refs = []
        for block in section_blocks:
            for fact in eligible:
                hit = _phrase_hit(block["text"], fact["text"])
                if hit is not None and not any(ref["source_id"] == page_id and ref["block_id"] == block["id"] for ref in page_answer_refs):
                    page_answer_refs.append(_citation(page_id, block["id"], _excerpt(block["text"], hit, fact["text"])))
            for phrase in topic["match_any"]:
                hit = _phrase_hit(block["text"], phrase)
                if hit is not None and not any(ref["source_id"] == page_id and ref["block_id"] == block["id"] for ref in related_copy_refs):
                    related_copy_refs.append(_citation(page_id, block["id"], _excerpt(block["text"], hit, phrase)))
        before_refs = (page_answer_refs or related_copy_refs or [_citation(page_id, b["id"], _excerpt(b["text"])) for b in section_blocks[:2]])[:2]
        if section_kind in {"unavailable"}:
            answer_state = "page_unavailable"
        elif section_kind == "ambiguous" or conflicts:
            answer_state = "needs_review"
        elif page_answer_refs:
            answer_state = "approved_answer_present"
        elif related_copy_refs:
            answer_state = "related_copy_only"
        else:
            answer_state = "no_matching_answer_in_selected_section"
        if section_kind in {"unavailable", "ambiguous"}:
            draft = None
            draft_state = "hold_for_page_review"
        elif conflicts:
            draft = None
            draft_state = "conflicting_approved_facts"
        elif not eligible:
            draft = None
            draft_state = "needs_approved_fact"
        else:
            draft = " ".join(fact["text"] for fact in eligible)
            draft_state = "approved_text_ready" if answer_state != "approved_answer_present" else "already_present"
        topic_proof = []
        if not audience_refs:
            topic_proof.append(f"Confirm whether public contributors actually ask: {topic['question']}")
        if conflicts:
            topic_proof.append(f"Resolve conflicting approved facts for {topic['id']}: {', '.join(sorted(conflicts))}.")
        elif not eligible:
            topic_proof.append(f"Approve a product fact before answering: {topic['question']}")
        if answer_state == "page_unavailable":
            topic_proof.append(f"Review the unavailable page before changing the {topic['target_heading']} section.")
        if answer_state == "needs_review" and section_kind == "ambiguous":
            topic_proof.append(f"Resolve duplicate {topic['target_heading']} headings before editing.")
        proof_needed.extend(topic_proof)
        row = {
            "topic_id": topic["id"], "question": topic["question"], "question_origin": origin,
            "verbatim_quotes": verbatim if observed else [], "target_heading": topic["target_heading"],
            "section_action": "propose_new_section" if section_kind == "new_section" else "review_existing_section",
            "page_answer_state": answer_state, "before_refs": before_refs, "audience_refs": audience_refs,
            "page_answer_refs": page_answer_refs, "related_copy_refs": related_copy_refs,
            "fact_refs": fact_refs, "draft": draft, "draft_state": draft_state, "proof_needed": topic_proof,
        }
        topic_rows.append(row)
        if audience_refs and answer_state != "approved_answer_present" and len(faq_edits) < 3:
            faq_edits.append({**row, "rationale": "Observed language is linked to the selected section; only approved product facts may supply the draft."})
    headline_topic = next(row for row in topic_rows if row["topic_id"] == headline_topic_id)
    headline_fact = eligible_by_topic[headline_topic_id][0] if eligible_by_topic[headline_topic_id] else None
    if headline_fact and headline_topic["audience_refs"]:
        headline_alternatives = [
            {"topic_id": headline_topic_id, "text": f"{product}: {headline_fact['text']}", "state": "approved_text_template", "audience_refs": headline_topic["audience_refs"], "fact_refs": headline_fact["evidence"]},
            {"topic_id": headline_topic_id, "text": f"{headline_topic['question']} {headline_fact['text']}", "state": "approved_text_template", "audience_refs": headline_topic["audience_refs"], "fact_refs": headline_fact["evidence"]},
        ]
    else:
        state = "needs_audience_evidence" if not headline_topic["audience_refs"] else "needs_approved_fact"
        headline_alternatives = [{"topic_id": headline_topic_id, "text": None, "state": state, "audience_refs": headline_topic["audience_refs"], "fact_refs": []} for _ in range(2)]
    unavailable = [s["id"] for s in normalized if s["status"] != "collected"]
    if unavailable:
        warnings.append({"code": "source_unavailable", "source_ids": unavailable, "note": "Non-collected sources cannot support findings."})
    decision = "annotated_rewrite" if any(row["audience_refs"] for row in topic_rows) else "no_audience_evidence"
    status = "needs_review" if unavailable or (decision != "no_audience_evidence" and (proof_needed or any(w["code"] == "conflicting_record" for w in warnings))) else "no_data" if decision == "no_audience_evidence" else "ok"
    source_index = []
    for source in normalized:
        item = {key: source[key] for key in ("id", "kind", "role", "url", "status", "observed_at", "published_at", "provider_date", "record_id", "record_id_origin", "provenance", "content_sha256")}
        item["url"] = redact_url(item["url"])
        source_index.append(item)
    report = {
        "schema_version": "1.0", "project": PROJECT, "analysis_method": "deterministic_rules_v1",
        "draft_method": "approved_text_templates_v1", "status": status, "decision": decision,
        "scope": {"product": product, "page_source_id": page_id, "source_ids": [s["id"] for s in normalized], "source_roles": [s["role"] for s in normalized], "topic_ids": [t["id"] for t in topics], "as_of": as_of},
        "summary": {"sources_analyzed": sum(s["status"] == "collected" and s["id"] not in conclusion_excluded for s in normalized), "sources_excluded": len(set(unavailable) | conclusion_excluded), "topics_analyzed": len(topics), "faq_rows": len(faq_edits)},
        "warnings": warnings, "source_index": source_index, "headlines": headline_alternatives,
        "headline_alternatives": headline_alternatives, "faqs": faq_edits, "faq_edits": faq_edits,
        "question_map": topic_rows, "proof_needed": proof_needed,
    }
    return report
