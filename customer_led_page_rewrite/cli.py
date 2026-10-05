"""Command-line interface with offline-by-default safety gates."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .brightdata import BrightDataError, collect, normalize_export, plan, resume, urllib_transport, validate_live_plan
from .core import InputError, analyze
from .export import render_csv, render_markdown


def _read_json(path: Path, *, max_bytes: int = 2 * 1024 * 1024):
    if path.stat().st_size > max_bytes:
        raise InputError("input exceeds 2 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    if path.stat().st_size > max_bytes:
        raise InputError("input exceeds 2 MiB")
    return path.read_text(encoding="utf-8")


def _atomic(path: Path, content: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise InputError(f"output already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False)
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _preflight_output(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise InputError(f"output already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    probe = tempfile.NamedTemporaryFile(dir=path.parent, prefix=".write-probe.", delete=False)
    probe_path = Path(probe.name)
    try:
        probe.close()
    finally:
        probe_path.unlink(missing_ok=True)


@contextmanager
def _output_reservation(path: Path, overwrite: bool):
    """Reserve a single output path across validation, network, and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.reservation"
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise InputError("output path is reserved by another operation") from exc
    try:
        os.close(lock_fd)
        _preflight_output(path, overwrite)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _atomic_group(directory: Path, outputs: dict[str, str], overwrite: bool) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".customer-led-page-rewrite.lock"
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise InputError("another report write is in progress") from exc
    stages: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    placed: set[Path] = set()
    try:
        os.close(lock_fd)
        targets = [directory / name for name in outputs]
        if not overwrite and any(target.exists() for target in targets):
            raise InputError("one or more report files already exist")
        for name, content in outputs.items():
            target = directory / name
            handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, prefix=f".{name}.", delete=False)
            stage = Path(handle.name)
            with handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            stages[target] = stage
        for target in targets:
            if target.exists():
                backup_handle = tempfile.NamedTemporaryFile(dir=directory, prefix=f".{target.name}.backup.", delete=False)
                backup = Path(backup_handle.name)
                backup_handle.close()
                backup.unlink()
                os.replace(target, backup)
                backups[target] = backup
        for target, stage in stages.items():
            os.replace(stage, target)
            placed.add(target)
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        for backup in backups.values():
            backup.unlink(missing_ok=True)
    except Exception:
        for target in placed:
            target.unlink(missing_ok=True)
        for target, backup in backups.items():
            if backup.exists():
                os.replace(backup, target)
        raise
    finally:
        for stage in stages.values():
            stage.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)


def _validate_collection_library(library) -> list[dict]:
    top_keys = {"schema_version", "project", "transport_contract_version", "sources", "receipt"}
    if not isinstance(library, dict) or set(library) != top_keys:
        raise InputError("source library keys do not match the contract")
    if library["schema_version"] != "1.0" or library["project"] != "customer-led-page-rewrite" or library["transport_contract_version"] != "1.0":
        raise InputError("source library schema, project, or transport version is invalid")
    sources = library["sources"]
    if not isinstance(sources, list) or len(sources) > 100 or any(not isinstance(source, dict) for source in sources):
        raise InputError("source library sources must be an array of at most 100 objects")
    ids = [source.get("id") for source in sources]
    if any(not isinstance(source_id, str) for source_id in ids) or len(ids) != len(set(ids)):
        raise InputError("source library IDs must be present and unique")
    receipt = library["receipt"]
    receipt_keys = {"schema_version", "project", "manifest_sha256", "status", "requests_made", "returned_records", "retained_records", "excluded_records", "jobs", "warnings", "provider_cost_usd"}
    if not isinstance(receipt, dict) or set(receipt) != receipt_keys:
        raise InputError("source library receipt keys do not match the contract")
    if receipt["schema_version"] != "1.0" or receipt["project"] != "customer-led-page-rewrite" or receipt["status"] not in {"complete", "partial", "failed", "pending", "completion_unknown"}:
        raise InputError("source library receipt identity or status is invalid")
    manifest_hash = receipt["manifest_sha256"]
    if manifest_hash is not None and (not isinstance(manifest_hash, str) or len(manifest_hash) != 64 or any(character not in "0123456789abcdef" for character in manifest_hash)):
        raise InputError("source library manifest hash is invalid")
    for key in ("requests_made", "returned_records", "retained_records", "excluded_records"):
        value = receipt[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InputError(f"source library receipt {key} is invalid")
    if receipt["retained_records"] != len(sources):
        raise InputError("source library retained count does not match sources")
    if not isinstance(receipt["jobs"], list) or not 1 <= len(receipt["jobs"]) <= 3 or not isinstance(receipt["warnings"], list) or receipt["provider_cost_usd"] is not None:
        raise InputError("source library receipt collections or cost field are invalid")
    if (manifest_hash is None and (receipt["requests_made"] != 0 or len(receipt["jobs"]) != 1 or receipt["jobs"][0].get("id") != "offline-import")) or (manifest_hash is not None and receipt["requests_made"] < 1):
        raise InputError("source library manifest and request provenance are inconsistent")
    job_keys = {"id", "kind", "state", "original_job", "approved_url_sha256", "approved_url_binding_sha256", "requested_records", "returned_records", "retained_records", "excluded_records", "snapshot_id", "error_code", "query_metadata"}
    job_ids = set()
    returned_sum = retained_sum = excluded_sum = 0
    for job in receipt["jobs"]:
        if not isinstance(job, dict) or set(job) != job_keys or not isinstance(job.get("id"), str) or job["id"] in job_ids:
            raise InputError("source library job schema or IDs are invalid")
        job_ids.add(job["id"])
        if job["state"] not in {"complete", "empty", "failed", "pending", "completion_unknown", "not_attempted"}:
            raise InputError("source library job state is invalid")
        if not isinstance(job["original_job"], dict) or not isinstance(job["approved_url_sha256"], list) or job["query_metadata"] is not None:
            raise InputError("source library job metadata is invalid")
        for key in ("returned_records", "retained_records", "excluded_records"):
            value = job[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InputError(f"source library job {key} is invalid")
        returned_sum += job["returned_records"]
        retained_sum += job["retained_records"]
        excluded_sum += job["excluded_records"]
    if receipt["jobs"]:
        if (returned_sum, retained_sum, excluded_sum) != (receipt["returned_records"], receipt["retained_records"], receipt["excluded_records"]):
            raise InputError("source library job counts do not match receipt totals")
    elif sources or receipt["requests_made"]:
        raise InputError("source library with sources or requests requires job receipts")
    return sources


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="customer-led-page-rewrite", description="Create evidence-linked page rewrite suggestions from approved product facts.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("analyze")
    command.add_argument("input", type=Path)
    command.add_argument("--out-dir", type=Path, required=True)
    command.add_argument("--sources", type=Path)
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--overwrite", action="store_true")
    command = commands.add_parser("import-provider")
    command.add_argument("file", type=Path)
    command.add_argument("--kind", required=True)
    command.add_argument("--role", required=True)
    command.add_argument("--source-url", required=True)
    command.add_argument("--observed-at", required=True)
    command.add_argument("--source-prefix", default="import")
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--overwrite", action="store_true")
    command = commands.add_parser("collect")
    command.add_argument("manifest", type=Path)
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--live", action="store_true")
    command.add_argument("--accept-charges", action="store_true")
    command.add_argument("--approval", type=Path)
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--overwrite", action="store_true")
    command = commands.add_parser("resume")
    command.add_argument("receipt", type=Path)
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--live", action="store_true", required=True)
    command.add_argument("--accept-charges", action="store_true", required=True)
    command.add_argument("--approval", type=Path, required=True)
    command.add_argument("--overwrite", action="store_true")
    return parser


def _emit_error(code: str, message: str, requests: int = 0, retry_after_seconds: int | None = None) -> None:
    payload = {"code": code, "message": message, "requests_made": requests}
    if retry_after_seconds is not None:
        payload["retry_after_seconds"] = retry_after_seconds
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "analyze":
            payload = _read_json(args.input)
            collection_receipt = None
            if args.sources:
                analyze(payload)
                library = _read_json(args.sources)
                additions = _validate_collection_library(library)
                collection_receipt = library["receipt"]
                existing = {source["id"] for source in payload.get("sources", [])}
                if existing.intersection(source.get("id") for source in additions):
                    raise InputError("duplicate source ID between input and library")
                payload = {**payload, "sources": payload.get("sources", []) + additions}
            report = analyze(payload)
            if collection_receipt is not None and (
                collection_receipt["status"] != "complete"
                or any(job["state"] not in {"complete"} for job in collection_receipt["jobs"])
            ):
                report["status"] = "needs_review"
                report["warnings"].append({"code": "collection_needs_review", "source_ids": [], "note": "The attached collection has pending, failed, empty, or not-attempted work; inspect its local receipt before drawing conclusions."})
            if args.dry_run:
                print(json.dumps({"input_sources": len(payload.get("sources", [])), "output_rows": len(report["faqs"]), "status": report["status"], "requests_made": 0}, sort_keys=True))
                return 0
            outputs = {"report.json": json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "rewrite.md": render_markdown(report), "rewrite.csv": render_csv(report)}
            _atomic_group(args.out_dir, outputs, args.overwrite)
            print(json.dumps({"status": report["status"], "decision": report["decision"], "requests_made": 0}, sort_keys=True))
            return 0
        if args.command == "import-provider":
            if args.kind == "web_page":
                records = _read_text(args.file)
            else:
                records = _read_json(args.file)
            with _output_reservation(args.out, args.overwrite):
                result = normalize_export(args.kind, records, role=args.role, source_url=args.source_url, observed_at=args.observed_at, source_prefix=args.source_prefix)
                _atomic(args.out, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", args.overwrite)
            print(json.dumps({"status": result["receipt"]["status"], "requests_made": 0}, sort_keys=True))
            return 4 if result["receipt"]["status"] == "partial" else 0
        if args.command == "collect":
            manifest = _read_json(args.manifest)
            planned = validate_live_plan(manifest) if args.live else plan(manifest)
            if args.dry_run:
                print(json.dumps({**planned, "requests_made": 0}, sort_keys=True))
                return 0
            if not args.live:
                raise InputError("collection requires --live; otherwise use --dry-run")
            if not args.accept_charges or not args.approval:
                raise InputError("live collection requires --accept-charges and --approval")
            with _output_reservation(args.out, args.overwrite):
                try:
                    result = collect(manifest, approval=_read_json(args.approval), api_key=os.environ.get("BRIGHT_DATA_API_KEY", ""), zones={"web_unlocker": os.environ.get("BRIGHT_DATA_WEB_UNLOCKER_ZONE", "")}, transport=urllib_transport, now=None, ledger_path=Path(str(args.approval) + ".ledger"))
                except BrightDataError as error:
                    if error.receipt is not None:
                        _atomic(args.out, json.dumps(error.receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", args.overwrite)
                    raise
                _atomic(args.out, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", args.overwrite)
            if result["receipt"]["status"] in {"failed", "completion_unknown"} or any(job.get("state") == "failed" for job in result["receipt"]["jobs"]):
                return 3
            return 4 if result["receipt"]["status"] in {"partial", "pending"} else 0
        receipt = _read_json(args.receipt)
        with _output_reservation(args.out, args.overwrite):
            try:
                result = resume(receipt, approval=_read_json(args.approval), api_key=os.environ.get("BRIGHT_DATA_API_KEY", ""), transport=urllib_transport, now=None, ledger_path=Path(str(args.approval) + ".ledger"))
            except BrightDataError as error:
                if error.receipt is not None:
                    _atomic(args.out, json.dumps(error.receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", args.overwrite)
                raise
            _atomic(args.out, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", args.overwrite)
        if result["receipt"]["status"] in {"failed", "completion_unknown"} or any(job.get("state") == "failed" for job in result["receipt"]["jobs"]):
            return 3
        return 4 if result["receipt"]["status"] in {"partial", "pending"} else 0
    except (InputError, BrightDataError, json.JSONDecodeError, UnicodeError, OSError) as exc:
        code = getattr(exc, "code", "invalid_input")
        requests = getattr(exc, "requests_made", 0)
        retry_after = getattr(exc, "retry_after_seconds", None)
        _emit_error(code, "The input or operation was rejected safely." if isinstance(exc, BrightDataError) else str(exc), requests, retry_after)
        return 3 if isinstance(exc, BrightDataError) and getattr(exc, "provider_failure", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())
