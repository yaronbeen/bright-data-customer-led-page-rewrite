"""Deterministic Markdown and CSV renderers."""

from __future__ import annotations

import csv
import html
import io
import re
import unicodedata

CSV_COLUMNS = [
    "row_type", "topic_id", "question_origin", "target_heading", "page_answer_state",
    "before_excerpt", "draft", "draft_state", "proof_needed", "audience_source_ids",
    "fact_source_ids", "evidence_urls", "provenance_state", "contains_synthetic_data",
]


def _md(value) -> str:
    value = " ".join(str(value).replace("\r\n", "\n").replace("\r", "\n").split())
    value = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{\[\]()#+\-.!|>}])", r"\\\1", value)


def _safe_csv(value) -> str:
    value = "" if value is None else str(value)
    index = 0
    ignored = {"\ufeff", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2060"}
    while index < len(value) and (value[index].isspace() or ord(value[index]) < 32 or ord(value[index]) == 127 or value[index] in ignored):
        index += 1
    visible = unicodedata.normalize("NFKC", value[index:])
    if visible.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _refs(row: dict) -> list[dict]:
    return row.get("before_refs", []) + row.get("audience_refs", []) + row.get("fact_refs", [])


def _csv_provenance(refs: list[dict], sources: dict[str, dict]) -> dict[str, str]:
    source_ids = list(dict.fromkeys(ref.get("source_id") for ref in refs if ref.get("source_id")))
    if not source_ids:
        return {"provenance_state": "uncited", "contains_synthetic_data": "unknown"}
    if any(source_id not in sources for source_id in source_ids):
        return {"provenance_state": "unknown", "contains_synthetic_data": "unknown"}
    provenance = {sources[source_id].get("provenance") for source_id in source_ids}
    known = {"synthetic_fixture", "operator_supplied", "bright_data"}
    if not provenance <= known:
        return {"provenance_state": "unknown", "contains_synthetic_data": "unknown"}
    contains_synthetic = "synthetic_fixture" in provenance
    state = "synthetic" if provenance == {"synthetic_fixture"} else "mixed" if contains_synthetic else "non_synthetic"
    return {
        "provenance_state": state,
        "contains_synthetic_data": "true" if contains_synthetic else "false",
    }


def render_markdown(report: dict) -> str:
    sources = {source["id"]: source for source in report.get("source_index", [])}
    lines = ["# Customer-Led Page Rewrite", ""]
    citation_rows = (
        report.get("question_map", [])
        + report.get("headlines", report.get("headline_alternatives", []))
        + report.get("faqs", report.get("faq_edits", []))
    )
    cited_ids = {
        ref["source_id"]
        for row in citation_rows
        for ref in _refs(row)
        if ref.get("source_id") in sources
    }
    cited_provenance = {sources[source_id].get("provenance") for source_id in cited_ids}
    if cited_provenance == {"synthetic_fixture"}:
        lines += ["> **Synthetic demonstration:** all cited source content in this report is invented fixture data.", ""]
    elif "synthetic_fixture" in cited_provenance and len(cited_provenance) > 1:
        lines += ["> **Mixed-provenance evidence:** this report cites synthetic and non-synthetic cited sources. Check each evidence entry before sharing.", ""]
    lines += [
        "> **Name and evidence scope:** Customer-Led is a workflow name. It does not establish customer identity or buying intent. The workflow uses public-contributor language selected by an operator.",
        "",
    ]
    lines += [
        f"**Decision:** `{report.get('decision', '')}`  ",
        f"**Status:** `{report.get('status', '')}`  ",
        f"**Method:** `{report.get('analysis_method', '')}` / `{report.get('draft_method', '')}`", "",
        "Headline templates combine operator-supplied product/question text with approved fact text. FAQ answer drafts use approved fact text only. They are suggestions for human review, not conversion promises or verified customer consensus.", "",
        "## Headline Alternatives", "",
    ]
    for index, item in enumerate(report.get("headlines", report.get("headline_alternatives", [])), 1):
        lines.append(f"{index}. {_md(item.get('text') or '[' + item.get('state', 'unavailable') + ']')}")
    lines += ["", "## FAQ Edits", ""]
    faqs = report.get("faqs", report.get("faq_edits", []))
    if not faqs:
        lines.append("No evidence-linked FAQ edit is supported by the selected public-contributor language.")
    for faq in faqs:
        lines += [
            f"### {_md(faq['question'])}", "",
            f"- Attribution: `{faq['question_origin']}`",
            f"- Selected section: {_md(faq['target_heading'])}",
            f"- Page answer state: `{faq['page_answer_state']}`",
            f"- Suggested draft: {_md(faq['draft']) if faq.get('draft') else '[' + faq['draft_state'] + ']'}",
        ]
        if faq.get("before_refs"):
            lines.append(f"- Existing copy: “{_md(faq['before_refs'][0]['quote'])}”")
        lines.append("")
    lines += ["## Proof Needed", ""]
    if report.get("proof_needed"):
        lines.extend(f"- {_md(note)}" for note in report["proof_needed"])
    else:
        lines.append("- No unresolved proof task was produced by the declared checks.")
    warnings = report.get("warnings", [])
    if warnings:
        lines += ["", "## Warnings", ""]
        for warning in warnings:
            lines.append(f"- `{_md(warning.get('code', 'warning'))}`: {_md(warning.get('note', 'Review this warning.'))}")
    lines += ["", "## Bounded Scope", "", f"- Product: {_md(report.get('scope', {}).get('product', ''))}", f"- As of: {_md(report.get('scope', {}).get('as_of') or 'not supplied')}", f"- Source IDs: {_md('; '.join(report.get('scope', {}).get('source_ids', [])))}", "", "## Evidence Appendix", ""]
    seen = set()
    for row in report.get("question_map", []) + report.get("headlines", []):
        for ref in _refs(row):
            key = (ref.get("source_id"), ref.get("block_id"), ref.get("quote"))
            if key in seen:
                continue
            seen.add(key)
            source = sources.get(ref["source_id"], {})
            locator = source.get("url") or "operator note"
            if source.get("record_id"):
                locator += f" (record {source['record_id']})"
            lines.append(f"- `{_md(ref['source_id'])}/{_md(ref['block_id'])}` “{_md(ref['quote'])}” — {_md(locator)}; observed {_md(source.get('observed_at', 'unknown'))}; SHA-256 `{_md(source.get('content_sha256', 'unknown'))}`")
    lines += ["", "## Limitations", "", "Literal phrase rules can miss paraphrases. Public contributors are not assumed to be customers and their language does not establish buying intent. Topic questions and product names are operator-selected. Approved facts are operator attestations, not independently verified claims. Inspect free text for personal or sensitive information before sharing.", ""]
    return "\n".join(lines)


def render_csv(report: dict) -> str:
    sources = {source["id"]: source for source in report.get("source_index", [])}
    rows = []
    headlines = report.get("headlines", report.get("headline_alternatives", []))
    for item in headlines:
        refs = item.get("audience_refs", []) + item.get("fact_refs", [])
        rows.append({
            "row_type": "headline",
            "topic_id": item.get("topic_id", ""),
            "draft": item.get("text"),
            "draft_state": item.get("state", ""),
            "audience_source_ids": ";".join(dict.fromkeys(r["source_id"] for r in item.get("audience_refs", []))),
            "fact_source_ids": ";".join(dict.fromkeys(r["source_id"] for r in item.get("fact_refs", []))),
            "evidence_urls": ";".join(dict.fromkeys(url for r in refs if (url := sources.get(r["source_id"], {}).get("url")))),
            **_csv_provenance(refs, sources),
        })
    for item in report.get("faqs", report.get("faq_edits", [])):
        refs = _refs(item)
        rows.append({
            "row_type": "faq",
            "topic_id": item["topic_id"],
            "question_origin": item["question_origin"],
            "target_heading": item["target_heading"],
            "page_answer_state": item["page_answer_state"],
            "before_excerpt": ";".join(r["quote"] for r in item.get("before_refs", [])),
            "draft": item.get("draft"),
            "draft_state": item["draft_state"],
            "proof_needed": ";".join(item.get("proof_needed", [])),
            "audience_source_ids": ";".join(dict.fromkeys(r["source_id"] for r in item.get("audience_refs", []))),
            "fact_source_ids": ";".join(dict.fromkeys(r["source_id"] for r in item.get("fact_refs", []))),
            "evidence_urls": ";".join(dict.fromkeys(url for r in refs if (url := sources.get(r["source_id"], {}).get("url")))),
            **_csv_provenance(refs, sources),
        })
    for note in report.get("proof_needed", []):
        rows.append({"row_type": "proof_needed", "proof_needed": note, **_csv_provenance([], sources)})
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _safe_csv(row.get(key, "")) for key in CSV_COLUMNS})
    return output.getvalue()
